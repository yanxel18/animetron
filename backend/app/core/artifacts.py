"""Internal immutable metadata only; no byte access or authorization."""

import re
from dataclasses import dataclass
from uuid import RFC_4122, UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    MetaData,
    String,
    Table,
    Uuid,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from app.core.artifact_bytes import (
    ArtifactAuditLimitExceeded,
    ArtifactByteStore,
    StoredBytes,
)

metadata = MetaData()
artifacts = Table(
    "artifact_metadata",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("owner_id", String(128), nullable=False),
    Column("revision", String(128), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("byte_size", BigInteger, nullable=False),
    Column("media_type", String(255), nullable=False),
    Column("storage_locator", String(42), nullable=False),
    CheckConstraint(
        "substr(id::text, 15, 1) = '4' AND "
        "substr(id::text, 20, 1) IN ('8', '9', 'a', 'b')",
        name="ck_artifact_uuid4",
    ),
    CheckConstraint(
        "owner_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$'",
        name="ck_artifact_owner",
    ),
    CheckConstraint(
        "revision ~ '^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$'",
        name="ck_artifact_revision",
    ),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_artifact_sha256"),
    CheckConstraint("byte_size >= 0", name="ck_artifact_byte_size"),
    CheckConstraint(
        "media_type ~ '^[a-z0-9][a-z0-9!#$&^_.+-]*/"
        "[a-z0-9][a-z0-9!#$&^_.+-]*$'",
        name="ck_artifact_media_type",
    ),
    CheckConstraint(
        "storage_locator = 'artifacts/' || replace(id::text, '-', '')",
        name="ck_artifact_locator",
    ),
)

_IDENTIFIER = r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}"
_MEDIA_TYPE = r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*"


@dataclass(frozen=True)
class ArtifactMetadata:
    """One revision per ID; trusted server-side code must generate UUID4 IDs.

    Version/variant validation checks shape only, not randomness or provenance.
    """

    id: UUID
    owner_id: str
    revision: str
    sha256: str
    byte_size: int
    media_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("Invalid artifact identifier")
        if self.id.version != 4 or self.id.variant != RFC_4122:
            raise ValueError("Artifact identifier must be an RFC-variant UUID4")
        for value in (self.owner_id, self.revision):
            if not isinstance(value, str) or re.fullmatch(_IDENTIFIER, value) is None:
                raise ValueError("Invalid artifact owner or revision")
        if (
            not isinstance(self.sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None
        ):
            raise ValueError("Invalid artifact digest")
        if type(self.byte_size) is not int or not 0 <= self.byte_size <= 2**63 - 1:
            raise ValueError("Invalid artifact byte size")
        if (
            not isinstance(self.media_type, str)
            or len(self.media_type) > 255
            or re.fullmatch(_MEDIA_TYPE, self.media_type) is None
        ):
            raise ValueError("Invalid artifact media type")

    @property
    def storage_locator(self) -> str:
        return f"artifacts/{self.id.hex}"


class ArtifactNotFound(LookupError):
    pass


class ArtifactConflict(Exception):
    pass


@dataclass(frozen=True)
class ArtifactAuditReport:
    consistent: tuple[UUID, ...]
    missing: tuple[UUID, ...]
    orphaned: tuple[UUID, ...]
    corrupt: tuple[UUID, ...]
    unsafe: tuple[UUID, ...]
    invalid_metadata: tuple[UUID, ...]
    pending_names: tuple[str, ...]
    unsafe_pending_names: tuple[str, ...]
    unexpected_count: int


def audit_artifacts(
    connection: Connection,
    store: ArtifactByteStore,
    *,
    max_total_bytes: int,
    max_entries: int,
) -> ArtifactAuditReport:
    """Compare stopped-writer metadata and byte inventories without changing either."""
    if not connection.in_transaction():
        raise RuntimeError("An explicit transaction is required")
    if type(max_total_bytes) is not int or not 0 <= max_total_bytes <= 2**63 - 1:
        raise ValueError("Artifact audit byte limit is invalid")
    if type(max_entries) is not int or not 1 <= max_entries <= 2**31 - 1:
        raise ValueError("Artifact audit entry limit is invalid")

    rows = connection.execute(select(artifacts).limit(max_entries + 1)).all()
    if len(rows) > max_entries:
        raise ArtifactAuditLimitExceeded("Artifact audit exceeds configured entry limit")

    expected: dict[UUID, StoredBytes] = {}
    invalid_metadata: set[UUID] = set()
    for row in rows:
        try:
            metadata_record = ArtifactMetadata(
                row.id, row.owner_id, row.revision, row.sha256, row.byte_size, row.media_type,
            )
        except (TypeError, ValueError):
            if isinstance(row.id, UUID):
                invalid_metadata.add(row.id)
            continue
        expected[metadata_record.id] = StoredBytes(
            metadata_record.id, metadata_record.sha256, metadata_record.byte_size,
        )

    inventory = store.audit(
        max_total_bytes=max_total_bytes, max_entries=max_entries,
    )
    actual = {record.id: record for record in inventory.files}
    unsafe = set(inventory.unsafe_ids)
    consistent: list[UUID] = []
    missing: list[UUID] = []
    corrupt: list[UUID] = []
    for identifier, expected_bytes in expected.items():
        if identifier in unsafe:
            continue
        stored = actual.get(identifier)
        if stored is None:
            missing.append(identifier)
        elif stored != expected_bytes:
            corrupt.append(identifier)
        else:
            consistent.append(identifier)

    return ArtifactAuditReport(
        consistent=tuple(sorted(consistent, key=lambda value: value.int)),
        missing=tuple(sorted(missing, key=lambda value: value.int)),
        orphaned=tuple(sorted(
            actual.keys() - expected.keys() - invalid_metadata,
            key=lambda value: value.int,
        )),
        corrupt=tuple(sorted(corrupt, key=lambda value: value.int)),
        unsafe=tuple(sorted(unsafe, key=lambda value: value.int)),
        invalid_metadata=tuple(sorted(invalid_metadata, key=lambda value: value.int)),
        pending_names=inventory.pending_names,
        unsafe_pending_names=inventory.unsafe_pending_names,
        unexpected_count=inventory.unexpected_count,
    )


def get_artifact(connection: Connection, artifact_id: UUID) -> ArtifactMetadata:
    """Internal lookup only. The caller must enforce any access policy."""
    row = connection.execute(
        select(artifacts).where(artifacts.c.id == artifact_id)
    ).one_or_none()
    if row is None:
        raise ArtifactNotFound("Artifact metadata not found")
    return ArtifactMetadata(
        id=row.id,
        owner_id=row.owner_id,
        revision=row.revision,
        sha256=row.sha256,
        byte_size=row.byte_size,
        media_type=row.media_type,
    )


def save_artifact(
    connection: Connection, record: ArtifactMetadata
) -> ArtifactMetadata:
    """Insert or replay identical metadata without committing the transaction."""
    from psycopg import Connection as PsycopgConnection

    driver = connection.connection.driver_connection
    if (
        not connection.in_transaction()
        or not isinstance(driver, PsycopgConnection)
        or driver.autocommit
    ):
        raise RuntimeError("An explicit non-autocommit transaction is required")
    result = connection.execute(
        insert(artifacts)
        .values(
            id=record.id,
            owner_id=record.owner_id,
            revision=record.revision,
            sha256=record.sha256,
            byte_size=record.byte_size,
            media_type=record.media_type,
            storage_locator=record.storage_locator,
        )
        .on_conflict_do_nothing(index_elements=[artifacts.c.id])
        .returning(artifacts.c.id)
    )
    if result.scalar_one_or_none() is not None:
        return record
    existing = get_artifact(connection, record.id)
    if existing != record:
        raise ArtifactConflict("Artifact ID already contains different metadata")
    return existing
