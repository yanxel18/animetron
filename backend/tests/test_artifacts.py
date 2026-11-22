import hashlib
import io
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import CheckConstraint, create_engine, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.core import artifacts as artifact_module
from app.core.artifact_bytes import (
    ArtifactAuditLimitExceeded,
    ArtifactByteStore,
    StoredBytes,
)
from app.core.artifacts import (
    ArtifactConflict,
    ArtifactMetadata,
    ArtifactNotFound,
    artifacts,
    get_artifact,
    save_artifact,
)
from app.core.database import create_database_engine

NON_UUID4_IDS = [
    pytest.param(UUID("12345678-1234-1234-8234-123456789abc"), id="uuid1"),
    pytest.param(UUID(int=0), id="nil"),
    pytest.param(UUID("12345678-1234-5234-8234-123456789abc"), id="uuid5"),
    pytest.param(UUID("12345678-1234-4234-0234-123456789abc"), id="ncs-variant"),
    pytest.param(UUID("12345678-1234-4234-c234-123456789abc"), id="microsoft-variant"),
    pytest.param(UUID("12345678-1234-4234-e234-123456789abc"), id="future-variant"),
]


def artifact():
    return ArtifactMetadata(
        id=uuid4(),
        owner_id="creator-1",
        revision="rev1",
        sha256="a" * 64,
        byte_size=123,
        media_type="video/mp4",
    )


class FakeByteStore:
    def __init__(self, inventory):
        self.inventory = inventory
        self.max_total_bytes = None
        self.max_entries = None

    def audit(self, *, max_total_bytes, max_entries):
        self.max_total_bytes = max_total_bytes
        self.max_entries = max_entries
        return self.inventory


def sqlite_artifact_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE artifact_metadata (
                id CHAR(32) PRIMARY KEY,
                owner_id TEXT NOT NULL,
                revision TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                storage_locator TEXT NOT NULL
            )
        """))
    return engine


@pytest.fixture
def engine():
    url = os.environ.get("ANIMETRON_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set ANIMETRON_TEST_DATABASE_URL to an isolated PostgreSQL database")
    engine = create_database_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_metadata_is_immutable_and_locator_is_derived() -> None:
    record = artifact()
    assert record.storage_locator == f"artifacts/{record.id.hex}"
    assert replace(record, byte_size=0).byte_size == 0
    assert replace(record, byte_size=2**63 - 1).byte_size == 2**63 - 1
    with pytest.raises(FrozenInstanceError):
        record.revision = "changed"


def test_audit_compares_complete_metadata_and_bytes_without_writing() -> None:
    engine = sqlite_artifact_engine()
    consistent_id, missing_id, corrupt_id, unsafe_id, orphan_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(),
    )
    rows = (
        replace(artifact(), id=consistent_id, sha256=hashlib.sha256(b"ok").hexdigest(),
                byte_size=2),
        replace(artifact(), id=missing_id),
        replace(artifact(), id=corrupt_id),
        replace(artifact(), id=unsafe_id),
    )
    inventory = SimpleNamespace(
        files=(
            StoredBytes(consistent_id, hashlib.sha256(b"ok").hexdigest(), 2),
            StoredBytes(corrupt_id, hashlib.sha256(b"bad").hexdigest(), 3),
            StoredBytes(orphan_id, hashlib.sha256(b"orphan").hexdigest(), 6),
        ),
        unsafe_ids=(unsafe_id,),
        pending_names=(".pending-a", ".pending-b"),
        unsafe_pending_names=(),
        unexpected_count=1,
    )
    byte_store = FakeByteStore(inventory)
    try:
        with engine.begin() as conn:
            for record in rows:
                conn.execute(insert(artifacts).values(
                    id=record.id,
                    owner_id=record.owner_id,
                    revision=record.revision,
                    sha256=record.sha256,
                    byte_size=record.byte_size,
                    media_type=record.media_type,
                    storage_locator=record.storage_locator,
                ))

            report = artifact_module.audit_artifacts(
                conn, byte_store, max_total_bytes=64, max_entries=10,
            )

            assert report.consistent == (consistent_id,)
            assert report.missing == (missing_id,)
            assert report.corrupt == (corrupt_id,)
            assert report.unsafe == (unsafe_id,)
            assert report.orphaned == (orphan_id,)
            assert report.pending_names == (".pending-a", ".pending-b")
            assert report.unsafe_pending_names == ()
            assert report.unexpected_count == 1
            assert report.invalid_metadata == ()
            assert byte_store.max_total_bytes == 64
            assert byte_store.max_entries == 10
            assert conn.scalar(text("SELECT count(*) FROM artifact_metadata")) == 4
    finally:
        engine.dispose()


@pytest.mark.skipif(sys.platform != "linux", reason="Real byte storage requires Linux")
def test_audit_reconciles_real_byte_store_with_metadata_without_mutation() -> None:
    root_parent = os.environ.get("ARTIFACT_TEST_ROOT")
    if not root_parent:
        pytest.skip("Set ARTIFACT_TEST_ROOT to an isolated private Linux directory")
    engine = sqlite_artifact_engine()
    try:
        with (
            tempfile.TemporaryDirectory(dir=root_parent) as root,
            ArtifactByteStore(root) as store,
            engine.begin() as conn,
        ):
            consistent_id, missing_id, corrupt_id, orphan_id = (uuid4() for _ in range(4))
            for identifier, data in (
                (consistent_id, b"match"), (corrupt_id, b"actual"), (orphan_id, b"orphan"),
            ):
                store.put(identifier, io.BytesIO(data), max_bytes=len(data))
            records = (
                replace(artifact(), id=consistent_id,
                        sha256=hashlib.sha256(b"match").hexdigest(), byte_size=5),
                replace(artifact(), id=missing_id),
                replace(artifact(), id=corrupt_id,
                        sha256=hashlib.sha256(b"expect").hexdigest(), byte_size=6),
            )
            for record in records:
                conn.execute(insert(artifacts).values(
                    id=record.id, owner_id=record.owner_id, revision=record.revision,
                    sha256=record.sha256, byte_size=record.byte_size,
                    media_type=record.media_type, storage_locator=record.storage_locator,
                ))
            directory = Path(root) / "artifacts"
            before_files = {
                path.name: (path.stat().st_ino, path.read_bytes()) for path in directory.iterdir()
            }
            before_rows = conn.execute(select(artifacts).order_by(artifacts.c.id)).all()

            report = artifact_module.audit_artifacts(conn, store, max_total_bytes=64, max_entries=10)

            assert report.consistent == (consistent_id,)
            assert report.missing == (missing_id,)
            assert report.corrupt == (corrupt_id,)
            assert report.orphaned == (orphan_id,)
            assert report.unsafe == report.invalid_metadata == ()
            assert report.pending_names == report.unsafe_pending_names == ()
            assert report.unexpected_count == 0
            assert conn.execute(select(artifacts).order_by(artifacts.c.id)).all() == before_rows
            after_files = {
                path.name: (path.stat().st_ino, path.read_bytes()) for path in directory.iterdir()
            }
            assert after_files == before_files
    finally:
        engine.dispose()


def test_audit_reads_postgresql_metadata_without_mutation(engine) -> None:
    consistent = replace(
        artifact(), sha256=hashlib.sha256(b"ok").hexdigest(), byte_size=2,
    )
    missing, digest_mismatch, size_mismatch, sentinel = (
        artifact(), artifact(), artifact(), artifact(),
    )
    orphan_id = uuid4()
    inventory = SimpleNamespace(
        files=(
            StoredBytes(consistent.id, consistent.sha256, consistent.byte_size),
            StoredBytes(
                digest_mismatch.id, hashlib.sha256(b"bad").hexdigest(),
                digest_mismatch.byte_size,
            ),
            StoredBytes(
                size_mismatch.id, size_mismatch.sha256, size_mismatch.byte_size + 1,
            ),
            StoredBytes(orphan_id, hashlib.sha256(b"orphan").hexdigest(), 6),
        ),
        unsafe_ids=(),
        pending_names=(),
        unsafe_pending_names=(),
        unexpected_count=0,
    )
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            save_artifact(conn, sentinel)
            conn.execute(text(
                "CREATE TEMP TABLE artifact_metadata "
                "(LIKE public.artifact_metadata INCLUDING ALL) ON COMMIT DROP"
            ))
            for record in (consistent, missing, digest_mismatch, size_mismatch):
                save_artifact(conn, record)
            before = conn.execute(select(artifacts).order_by(artifacts.c.id)).all()

            report = artifact_module.audit_artifacts(
                conn, FakeByteStore(inventory), max_total_bytes=64, max_entries=10,
            )

            assert transaction.is_active
            assert report.consistent == (consistent.id,)
            assert report.missing == (missing.id,)
            assert report.corrupt == tuple(sorted(
                (digest_mismatch.id, size_mismatch.id), key=lambda identifier: identifier.int,
            ))
            assert report.orphaned == (orphan_id,)
            assert conn.execute(select(artifacts).order_by(artifacts.c.id)).all() == before
        finally:
            if transaction.is_active:
                transaction.rollback()
    with engine.connect() as conn, pytest.raises(ArtifactNotFound):
        get_artifact(conn, sentinel.id)


@pytest.mark.skipif(sys.platform != "linux", reason="Real byte storage requires Linux")
def test_audit_reconciles_postgresql_and_real_byte_store(engine) -> None:
    root_parent = os.environ.get("ARTIFACT_TEST_ROOT")
    if not root_parent:
        pytest.skip("Set ARTIFACT_TEST_ROOT to an isolated private Linux directory")
    sentinel = artifact()
    with (
        tempfile.TemporaryDirectory(dir=root_parent) as root,
        ArtifactByteStore(root) as store,
        engine.connect() as conn,
    ):
        transaction = conn.begin()
        try:
            save_artifact(conn, sentinel)
            conn.execute(text(
                "CREATE TEMP TABLE artifact_metadata "
                "(LIKE public.artifact_metadata INCLUDING ALL) ON COMMIT DROP"
            ))
            consistent_id, missing_id, corrupt_id, orphan_id = (uuid4() for _ in range(4))
            for identifier, data in (
                (consistent_id, b"match"), (corrupt_id, b"actual"), (orphan_id, b"orphan"),
            ):
                store.put(identifier, io.BytesIO(data), max_bytes=len(data))
            for record in (
                replace(artifact(), id=consistent_id,
                        sha256=hashlib.sha256(b"match").hexdigest(), byte_size=5),
                replace(artifact(), id=missing_id),
                replace(artifact(), id=corrupt_id,
                        sha256=hashlib.sha256(b"expect").hexdigest(), byte_size=6),
            ):
                save_artifact(conn, record)
            directory = Path(root) / "artifacts"
            before_files = {
                path.name: (path.stat().st_ino, path.read_bytes())
                for path in directory.iterdir()
            }
            before_rows = conn.execute(select(artifacts).order_by(artifacts.c.id)).all()

            report = artifact_module.audit_artifacts(
                conn, store, max_total_bytes=64, max_entries=10,
            )

            assert transaction.is_active
            assert report.consistent == (consistent_id,)
            assert report.missing == (missing_id,)
            assert report.corrupt == (corrupt_id,)
            assert report.orphaned == (orphan_id,)
            assert report.unsafe == report.invalid_metadata == ()
            assert report.pending_names == report.unsafe_pending_names == ()
            assert report.unexpected_count == 0
            assert conn.execute(select(artifacts).order_by(artifacts.c.id)).all() == before_rows
            after_files = {
                path.name: (path.stat().st_ino, path.read_bytes())
                for path in directory.iterdir()
            }
            assert after_files == before_files
        finally:
            if transaction.is_active:
                transaction.rollback()
    with engine.connect() as conn, pytest.raises(ArtifactNotFound):
        get_artifact(conn, sentinel.id)


def test_audit_excludes_invalid_metadata_ids_from_orphaned_bytes() -> None:
    engine = sqlite_artifact_engine()
    identifier = uuid4()
    inventory = SimpleNamespace(
        files=(StoredBytes(identifier, hashlib.sha256(b"content").hexdigest(), 7),),
        unsafe_ids=(),
        pending_names=(),
        unsafe_pending_names=(),
        unexpected_count=0,
    )
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO artifact_metadata
                VALUES (:id, 'owner', 'rev1', 'invalid', 7, 'video/mp4',
                        :locator)
            """), {"id": identifier.hex, "locator": f"artifacts/{identifier.hex}"})

            report = artifact_module.audit_artifacts(
                conn, FakeByteStore(inventory), max_total_bytes=64, max_entries=10,
            )

            assert report.invalid_metadata == (identifier,)
            assert report.orphaned == ()
            assert report.consistent == ()
    finally:
        engine.dispose()


def test_audit_reports_invalid_locator_without_classifying_bytes_as_orphaned() -> None:
    engine = sqlite_artifact_engine()
    record = replace(artifact(), sha256=hashlib.sha256(b"content").hexdigest(), byte_size=7)
    inventory = SimpleNamespace(
        files=(StoredBytes(record.id, record.sha256, record.byte_size),),
        unsafe_ids=(), pending_names=(), unsafe_pending_names=(), unexpected_count=0,
    )
    try:
        with engine.begin() as conn:
            conn.execute(insert(artifacts).values(
                id=record.id, owner_id=record.owner_id, revision=record.revision,
                sha256=record.sha256, byte_size=record.byte_size,
                media_type=record.media_type, storage_locator="artifacts/wrong",
            ))
            before = conn.execute(select(artifacts)).all()

            report = artifact_module.audit_artifacts(
                conn, FakeByteStore(inventory), max_total_bytes=64, max_entries=10,
            )

            assert report.invalid_metadata == (record.id,)
            assert report.consistent == report.orphaned == ()
            assert conn.execute(select(artifacts)).all() == before
    finally:
        engine.dispose()


def test_audit_rejects_metadata_over_entry_limit_before_scanning_bytes() -> None:
    engine = sqlite_artifact_engine()
    byte_store = FakeByteStore(SimpleNamespace(
        files=(), unsafe_ids=(), pending_names=(), unsafe_pending_names=(),
        unexpected_count=0,
    ))
    try:
        with engine.begin() as conn:
            for _ in range(2):
                record = artifact()
                conn.execute(insert(artifacts).values(
                    id=record.id,
                    owner_id=record.owner_id,
                    revision=record.revision,
                    sha256=record.sha256,
                    byte_size=record.byte_size,
                    media_type=record.media_type,
                    storage_locator=record.storage_locator,
                ))

            with pytest.raises(ArtifactAuditLimitExceeded):
                artifact_module.audit_artifacts(
                    conn, byte_store, max_total_bytes=64, max_entries=1,
                )

            assert byte_store.max_entries is None
    finally:
        engine.dispose()


def test_audit_requires_a_caller_owned_transaction() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as conn, pytest.raises(RuntimeError, match="transaction"):
            artifact_module.audit_artifacts(
                conn, FakeByteStore(SimpleNamespace(
                    files=(), unsafe_ids=(), pending_names=(),
                    unsafe_pending_names=(), unexpected_count=0,
                )), max_total_bytes=64, max_entries=10,
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("identifier", NON_UUID4_IDS)
def test_metadata_requires_uuid4_rfc_variant(identifier) -> None:
    with pytest.raises(ValueError, match="UUID4"):
        replace(artifact(), id=identifier)


@pytest.mark.parametrize("variant_digit", "89ab")
def test_metadata_accepts_uuid4_shape_without_proving_randomness(variant_digit) -> None:
    identifier = UUID(f"00000000-0000-4000-{variant_digit}000-000000000000")
    assert replace(artifact(), id=identifier).id == identifier


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "not-a-uuid"),
        ("owner_id", ""),
        ("owner_id", " owner"),
        ("owner_id", "x" * 129),
        ("owner_id", "owner\n"),
        ("revision", ""),
        ("revision", "rev\x00"),
        ("revision", "x" * 129),
        ("sha256", "A" * 64),
        ("sha256", "g" * 64),
        ("sha256", "a" * 63),
        ("byte_size", -1),
        ("byte_size", True),
        ("byte_size", 1.5),
        ("byte_size", 2**63),
        ("media_type", "Video/mp4"),
        ("media_type", "text/plain; charset=utf-8"),
        ("media_type", "not-a-type"),
        ("media_type", "video/mp4\n"),
    ],
)
def test_invalid_metadata_is_rejected(field, value) -> None:
    with pytest.raises((TypeError, ValueError)):
        replace(artifact(), **{field: value})


def test_save_replay_conflict_and_reconnect(engine) -> None:
    record = artifact()
    with engine.begin() as conn:
        assert save_artifact(conn, record) == record
        assert save_artifact(conn, record) == record
        for field, value in [
            ("owner_id", "creator-2"),
            ("revision", "rev2"),
            ("sha256", "b" * 64),
            ("byte_size", 456),
            ("media_type", "image/png"),
        ]:
            with pytest.raises(ArtifactConflict):
                save_artifact(conn, replace(record, **{field: value}))
    engine.dispose()
    with engine.connect() as conn:
        assert get_artifact(conn, record.id) == record
        with pytest.raises(ArtifactNotFound):
            get_artifact(conn, uuid4())


def test_rollback_includes_other_transactional_work(engine) -> None:
    record = artifact()
    with pytest.raises(RuntimeError, match="abort"), engine.begin() as conn:
        save_artifact(conn, record)
        conn.execute(text("CREATE TABLE artifact_atomicity_probe (id integer)"))
        raise RuntimeError("abort")
    with engine.connect() as conn:
        with pytest.raises(ArtifactNotFound):
            get_artifact(conn, record.id)
        assert conn.scalar(text("SELECT to_regclass('artifact_atomicity_probe')")) is None


def test_transaction_recovers_after_constraint_failure(engine) -> None:
    rolled_back = artifact()
    committed = artifact()
    invalid = artifact()
    with engine.connect() as conn:
        with pytest.raises(IntegrityError), conn.begin():
            save_artifact(conn, rolled_back)
            conn.execute(
                insert(artifacts).values(
                    id=invalid.id,
                    owner_id=invalid.owner_id,
                    revision=invalid.revision,
                    sha256=invalid.sha256,
                    byte_size=-1,
                    media_type=invalid.media_type,
                    storage_locator=invalid.storage_locator,
                )
            )

        with conn.begin():
            assert save_artifact(conn, committed) == committed

        with pytest.raises(ArtifactNotFound):
            get_artifact(conn, rolled_back.id)
        assert get_artifact(conn, committed.id) == committed


def test_writes_require_transaction_and_reject_autocommit(engine) -> None:
    with engine.connect() as conn, pytest.raises(RuntimeError, match="transaction"):
        save_artifact(conn, artifact())
    with (
        engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn,
        conn.begin(),
        pytest.raises(RuntimeError, match="transaction"),
    ):
        save_artifact(conn, artifact())


def test_metadata_constraints_match_migrated_table(engine) -> None:
    declared = {
        constraint.name
        for constraint in artifacts.constraints
        if isinstance(constraint, CheckConstraint)
    }
    actual = {
        constraint["name"]
        for constraint in inspect(engine).get_check_constraints("artifact_metadata")
    }
    assert declared == actual


@pytest.mark.parametrize("identical", [True, False])
def test_concurrent_writes_are_idempotent_or_conflict(engine, identical) -> None:
    record = artifact()
    barrier = Barrier(2)

    def attempt(index):
        candidate = record if identical else replace(record, byte_size=index)
        try:
            with engine.begin() as conn:
                conn.execute(text("SET LOCAL statement_timeout = '5s'"))
                barrier.wait(timeout=5)
                save_artifact(conn, candidate)
            return "saved"
        except ArtifactConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(attempt, range(2)))
    assert outcomes == (["saved", "saved"] if identical else ["conflict", "saved"])
    with engine.connect() as conn:
        rows = conn.execute(select(artifacts).where(artifacts.c.id == record.id)).all()
        assert len(rows) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", None),
        ("owner_id", None),
        ("owner_id", ""),
        ("owner_id", "owner\n"),
        ("revision", ""),
        ("sha256", "a" * 63),
        ("sha256", "A" * 64),
        ("byte_size", -1),
        ("media_type", "video/mp4\n"),
        ("media_type", "text/plain; charset=utf-8"),
        ("storage_locator", "../outside"),
        ("storage_locator", "C:\\outside"),
        ("storage_locator", f"artifacts/{uuid4().hex}"),
    ],
)
def test_database_constraints_reject_invalid_direct_inserts(engine, field, value) -> None:
    record = artifact()
    values = {
        "id": record.id,
        "owner_id": record.owner_id,
        "revision": record.revision,
        "sha256": record.sha256,
        "byte_size": record.byte_size,
        "media_type": record.media_type,
        "storage_locator": record.storage_locator,
    }
    values[field] = value
    with engine.begin() as conn, pytest.raises(IntegrityError), conn.begin_nested():
        conn.execute(insert(artifacts).values(**values))


@pytest.mark.parametrize("identifier", NON_UUID4_IDS)
def test_database_requires_uuid4_rfc_variant(engine, identifier) -> None:
    with (
        engine.begin() as conn,
        pytest.raises(IntegrityError) as error,
        conn.begin_nested(),
    ):
        conn.execute(
            insert(artifacts).values(
                id=identifier,
                owner_id="creator-1",
                revision="rev1",
                sha256="a" * 64,
                byte_size=0,
                media_type="video/mp4",
                storage_locator=f"artifacts/{identifier.hex}",
            )
        )
    assert error.value.orig.diag.constraint_name == "ck_artifact_uuid4"
