import re
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    Uuid,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.engine import Connection

metadata = MetaData()
outbox = Table(
    "outbox_intents",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("topic", String(80), nullable=False),
    Column("resource_id", Uuid, nullable=False),
    Column(
        "created_at", DateTime(timezone=True), nullable=False, server_default=func.now()
    ),
    Column("lease_token", Uuid, nullable=True),
    Column("lease_until", DateTime(timezone=True), nullable=True),
    Column("delivered_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "(lease_token IS NULL) = (lease_until IS NULL)", name="ck_outbox_lease_pair"
    ),
)
Index(
    "ix_outbox_pending",
    outbox.c.topic,
    outbox.c.created_at,
    outbox.c.id,
    postgresql_where=outbox.c.delivered_at.is_(None),
)


class OutboxConflict(Exception):
    pass


@dataclass(frozen=True)
class ClaimedIntent:
    id: UUID
    topic: str
    resource_id: UUID
    lease_token: UUID


def _validate_topic(topic: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9._-]{0,79}", topic):
        raise ValueError("Invalid outbox topic")


def enqueue(
    connection: Connection, intent_id: UUID, topic: str, resource_id: UUID
) -> None:
    if not connection.in_transaction():
        raise RuntimeError("An explicit transaction is required")
    _validate_topic(topic)
    connection.execute(
        insert(outbox).values(id=intent_id, topic=topic, resource_id=resource_id)
    )


def claim(
    connection: Connection, *, topic: str, limit: int, lease_seconds: int
) -> list[ClaimedIntent]:
    if not connection.in_transaction():
        raise RuntimeError("An explicit transaction is required")
    _validate_topic(topic)
    if not 1 <= limit <= 500 or not 1 <= lease_seconds <= 86400:
        raise ValueError("Invalid claim limit or lease duration")
    rows = connection.execute(
        select(outbox.c.id, outbox.c.resource_id)
        .where(
            outbox.c.topic == topic,
            outbox.c.delivered_at.is_(None),
            or_(
                outbox.c.lease_until.is_(None),
                outbox.c.lease_until <= func.clock_timestamp(),
            ),
        )
        .order_by(outbox.c.created_at, outbox.c.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    claimed = []
    for row in rows:
        lease_token = uuid4()
        connection.execute(
            update(outbox)
            .where(outbox.c.id == row.id)
            .values(
                lease_token=lease_token,
                lease_until=func.clock_timestamp() + timedelta(seconds=lease_seconds),
            )
        )
        claimed.append(ClaimedIntent(row.id, topic, row.resource_id, lease_token))
    return claimed


def acknowledge(connection: Connection, intent_id: UUID, lease_token: UUID) -> None:
    if not connection.in_transaction():
        raise RuntimeError("An explicit transaction is required")
    result = connection.execute(
        update(outbox)
        .where(
            outbox.c.id == intent_id,
            outbox.c.lease_token == lease_token,
            outbox.c.lease_until > func.clock_timestamp(),
            outbox.c.delivered_at.is_(None),
        )
        .values(delivered_at=func.clock_timestamp(), lease_token=None, lease_until=None)
        .returning(outbox.c.id)
    )
    if result.scalar_one_or_none() is None:
        raise OutboxConflict(
            "Intent is missing, delivered, or lease is no longer valid"
        )
