"""Opaque PostgreSQL sessions; no passwords, tokens or claimed roles from clients."""

import hashlib
import json
import re
import secrets
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection, Engine

Role = Literal["owner", "operator", "viewer"]
metadata = sa.MetaData()
login_states = sa.Table(
    "auth_login_states", metadata,
    sa.Column("state_hash", sa.String(64), primary_key=True),
    sa.Column("browser_hash", sa.String(64), nullable=False),
    sa.Column("config_hash", sa.String(64), nullable=False),
    sa.Column("nonce", sa.String(128), nullable=False),
    sa.Column("verifier", sa.String(128), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
)
sessions = sa.Table(
    "auth_sessions", metadata,
    sa.Column("handle_hash", sa.String(64), primary_key=True),
    sa.Column("subject", sa.String(255), nullable=False),
    sa.Column("principal_id", sa.String(64), nullable=False, unique=True),
    sa.Column("config_hash", sa.String(64), nullable=False),
    sa.Column("csrf", sa.String(64), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
)
audit_events = sa.Table(
    "auth_audit_events", metadata,
    sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
    sa.Column("event", sa.String(32), nullable=False),
    sa.Column("principal_id", sa.String(64)),
    sa.Column("request_id", sa.String(36), nullable=False),
    sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
)
auth_rate = sa.Table(
    "auth_rate", metadata,
    sa.Column("bucket", sa.BigInteger(), primary_key=True),
    sa.Column("attempts", sa.Integer(), nullable=False),
)
denial_counters = sa.Table(
    "auth_denial_counters", metadata,
    sa.Column("event", sa.String(32), primary_key=True),
    sa.Column("slot", sa.Integer(), primary_key=True),
    sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
    sa.Column("occurrences", sa.BigInteger(), nullable=False),
    sa.Column("last_request_id", sa.String(36), nullable=False),
    sa.Column("last_occurred_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("event IN ('access_denied', 'login_failed')", name="ck_denial_event"),
    sa.CheckConstraint("slot >= 0 AND slot < 96", name="ck_denial_slot"),
    sa.CheckConstraint("occurrences > 0", name="ck_denial_occurrences"),
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthDenied(Exception):
    def __init__(self, code: str = "UNAUTHENTICATED", status: int = 401) -> None:
        self.code = code
        self.status = status


@dataclass(frozen=True)
class AuthConfig:
    issuer: str
    client_id: str
    client_secret: str = field(repr=False)
    origin: str
    owner_subject: str
    grants: Mapping[str, Role] = field(default_factory=dict)
    session_seconds: int = 28800
    idle_seconds: int = 1800
    allow_loopback_provider_http: bool = False

    def __post_init__(self) -> None:
        for value in (self.client_id, self.client_secret, self.owner_subject):
            if not value or len(value) > 255 or any(ord(c) < 33 for c in value):
                raise ValueError("Explicit client credentials and owner subject are required")
        self.validate_provider_url(self.issuer)
        issuer = urlsplit(self.issuer)
        origin = urlsplit(self.origin)
        if issuer.query or issuer.fragment or self.issuer.endswith("/"):
            raise ValueError("An exact issuer is required")
        if (
            origin.scheme != "https" or not origin.hostname
            or origin.username or origin.password or origin.path
            or origin.query or origin.fragment or origin.netloc != origin.netloc.lower()
            or "\\" in self.origin or any(ord(c) < 33 for c in self.origin)
        ):
            raise ValueError("A canonical HTTPS browser origin without a path is required")
        _ = origin.port
        if not 60 <= self.session_seconds <= 28800 or not 60 <= self.idle_seconds <= 1800:
            raise ValueError("Session duration is outside the permitted bounds")
        for subject, role in self.grants.items():
            if not subject or len(subject) > 255 or role not in ("operator", "viewer"):
                raise ValueError("Only explicitly granted operator/viewer subjects are permitted")
        object.__setattr__(self, "grants", MappingProxyType(dict(self.grants)))

    def validate_provider_url(self, value: str) -> None:
        parsed = urlsplit(value)
        loopback = parsed.hostname in ("127.0.0.1", "::1", "localhost")
        if (
            not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or parsed.query or "\\" in value
            or any(ord(c) < 33 for c in value)
            or not (parsed.scheme == "https" or (
                parsed.scheme == "http" and loopback and self.allow_loopback_provider_http
            ))
        ):
            raise ValueError("Trusted HTTPS provider URL required")
        _ = parsed.port

    @property
    def fingerprint(self) -> str:
        return digest(json.dumps(
            [self.issuer, self.client_id, self.client_secret, self.origin,
             self.owner_subject, sorted(self.grants.items()),
             self.session_seconds, self.idle_seconds],
            separators=(",", ":"),
        ))

    @property
    def callback_uri(self) -> str:
        return self.origin + "/api/v1/auth/callback"

    def role(self, subject: str) -> Role:
        if subject == self.owner_subject:
            return "owner"
        role = self.grants.get(subject)
        if role is None:
            raise AuthDenied("FORBIDDEN", 403)
        return role


@dataclass(frozen=True)
class Principal:
    id: str
    role: Role
    csrf: str = field(repr=False)
    expires_at: datetime


class AuthStore:
    def __init__(self, engine: Engine, config: AuthConfig) -> None:
        self.engine = engine
        self.config = config

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        with self.engine.begin() as connection:
            connection.execute(sa.text("SET LOCAL statement_timeout = '3s'"))
            connection.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
            yield connection

    @staticmethod
    def record(
        conn: Connection, event: str, request_id: str, principal_id: str | None = None,
        *, now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        if event in ("access_denied", "login_failed"):
            bucket = int(now.timestamp()) // 900
            window = datetime.fromtimestamp(bucket * 900, UTC)
            AuthStore.prune_denials(conn, window)
            statement = insert(denial_counters).values(
                event=event, slot=bucket % 96, window_start=window,
                occurrences=1, last_request_id=request_id, last_occurred_at=now,
            )
            # Two server-owned categories x 96 slots: at most 192 durable rows,
            # irrespective of client/actor/request cardinality or clock changes.
            conn.execute(statement.on_conflict_do_update(
                index_elements=[denial_counters.c.event, denial_counters.c.slot],
                set_={
                    "window_start": window,
                    "occurrences": sa.case(
                        (denial_counters.c.window_start == window,
                         denial_counters.c.occurrences + 1), else_=1,
                    ),
                    "last_request_id": request_id, "last_occurred_at": now,
                },
            ))
            return
        conn.execute(audit_events.insert().values(
            event=event, principal_id=principal_id,
            request_id=request_id, occurred_at=now,
        ))

    @staticmethod
    def prune_denials(conn: Connection, window: datetime) -> None:
        conn.execute(denial_counters.delete().where(
            denial_counters.c.window_start <= window - timedelta(days=1)
        ))
        # Also expire legacy append-only history without requiring a login start.
        conn.execute(audit_events.delete().where(
            audit_events.c.occurred_at < window - timedelta(days=90)
        ))

    def denial_counts(self, *, now: datetime | None = None) -> list[Mapping[str, object]]:
        now = now or datetime.now(UTC)
        window = datetime.fromtimestamp(int(now.timestamp()) // 900 * 900, UTC)
        with self.transaction() as conn:
            self.prune_denials(conn, window)
            return [dict(row) for row in conn.execute(
                sa.select(denial_counters)
                .order_by(denial_counters.c.window_start, denial_counters.c.event)
            ).mappings()]

    def audit(self, event: str, request_id: str, principal_id: str | None = None) -> None:
        with self.transaction() as conn:
            self.record(conn, event, request_id, principal_id)

    def start_login(self, nonce: str, verifier: str, request_id: str) -> tuple[str, str]:
        now = datetime.now(UTC)
        state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        bucket = int(now.timestamp()) // 900
        with self.transaction() as conn:
            # Global, shared limiter intentionally conservative for a single-creator plane.
            count = conn.scalar(insert(auth_rate).values(bucket=bucket, attempts=1)
                .on_conflict_do_update(
                    index_elements=[auth_rate.c.bucket],
                    set_={"attempts": auth_rate.c.attempts + 1},
                ).returning(auth_rate.c.attempts))
            if count is None or count > 30:
                raise AuthDenied("RATE_LIMITED", 429)
            conn.execute(auth_rate.delete().where(auth_rate.c.bucket < bucket))
            conn.execute(login_states.delete().where(login_states.c.expires_at <= now))
            conn.execute(sessions.delete().where(
                sa.or_(sessions.c.expires_at <= now,
                       sessions.c.last_seen_at <= now - timedelta(seconds=self.config.idle_seconds))
            ))
            conn.execute(audit_events.delete().where(
                audit_events.c.occurred_at < now - timedelta(days=90)
            ))
            conn.execute(login_states.insert().values(
                state_hash=digest(state), browser_hash=digest(browser),
                config_hash=self.config.fingerprint, nonce=nonce, verifier=verifier,
                expires_at=now + timedelta(minutes=5),
            ))
            self.record(conn, "login_started", request_id)
        return state, browser

    def consume_login(
        self, state: str, browser: str, *, now: datetime | None = None,
    ) -> Mapping[str, object]:
        now = now or datetime.now(UTC)
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", state) or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}", browser
        ):
            raise AuthDenied("INVALID_STATE", 400)
        with self.transaction() as conn:
            row = conn.execute(login_states.delete().where(
                login_states.c.state_hash == digest(state),
                login_states.c.browser_hash == digest(browser),
                login_states.c.config_hash == self.config.fingerprint,
                login_states.c.expires_at > now,
            ).returning(login_states.c.nonce, login_states.c.verifier)).mappings().first()
        if row is None:
            raise AuthDenied("INVALID_STATE", 400)
        return dict(row)

    def create_session(self, subject: str, request_id: str) -> tuple[str, Principal]:
        role = self.config.role(subject)
        principal_id = digest(self.config.issuer + "\0" + subject)
        handle, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=self.config.session_seconds)
        with self.transaction() as conn:
            # Serialize rotation across workers; exactly one active session per principal.
            conn.execute(sa.text("SELECT pg_advisory_xact_lock(:key)"), {
                "key": int(principal_id[:15], 16),
            })
            conn.execute(sessions.delete().where(sessions.c.principal_id == principal_id))
            conn.execute(sessions.insert().values(
                handle_hash=digest(handle), subject=subject, principal_id=principal_id,
                config_hash=self.config.fingerprint, csrf=csrf,
                expires_at=expires, last_seen_at=now,
            ))
            self.record(conn, "login_succeeded", request_id, principal_id)
        return handle, Principal(principal_id, role, csrf, expires)

    def authenticate(
        self, handle: str, *, now: datetime | None = None, touch: bool = True,
    ) -> Principal:
        now = now or datetime.now(UTC)
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", handle):
            raise AuthDenied()
        with self.transaction() as conn:
            predicates = (
                sessions.c.handle_hash == digest(handle),
                sessions.c.config_hash == self.config.fingerprint,
                sessions.c.expires_at > now,
                sessions.c.last_seen_at > now - timedelta(seconds=self.config.idle_seconds),
            )
            query = (
                sessions.update().where(*predicates).values(last_seen_at=now).returning(sessions)
                if touch else sa.select(sessions).where(*predicates)
            )
            row = conn.execute(query).mappings().first()
        if row is None:
            raise AuthDenied()
        return Principal(
            row["principal_id"], self.config.role(row["subject"]), row["csrf"], row["expires_at"],
        )

    def revoke(self, handle: str, request_id: str) -> None:
        with self.transaction() as conn:
            principal_id = conn.scalar(sessions.delete().where(
                sessions.c.handle_hash == digest(handle),
                sessions.c.config_hash == self.config.fingerprint,
            ).returning(sessions.c.principal_id))
            self.record(conn, "logout", request_id, principal_id)

    def audit_page(self, cursor: int, limit: int) -> list[Mapping[str, object]]:
        with self.transaction() as conn:
            return [dict(row) for row in conn.execute(
                sa.select(audit_events).where(audit_events.c.id > cursor)
                .order_by(audit_events.c.id).limit(limit)
            ).mappings()]


def request_id() -> str:
    # Never echo attacker-controlled correlation values into the durable audit.
    return str(uuid4())
