"""Dependency-free Linux filesystem tests; also discovered by pytest."""

import hashlib
import io
import multiprocessing
import os
import stat
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import UUID, uuid4

from app.core.artifact_bytes import (
    ArtifactByteStore,
    ByteIntegrityError,
    StoredBytes,
    UnsafeStorageError,
    UnsupportedStorageError,
)


def crash_writer(root, identifier, boundary):
    """Terminate a real process at a filesystem boundary, not an exception."""
    from app.core import artifact_bytes

    original_link = os.link
    original_fsync = os.fsync

    def link(*args, **kwargs):
        if boundary == "before-link":
            os._exit(71)
        original_link(*args, **kwargs)
        if boundary == "after-link":
            os._exit(72)

    def fsync(fd):
        original_fsync(fd)
        if boundary == "after-unlink" and stat.S_ISDIR(os.fstat(fd).st_mode):
            os._exit(73)

    with (
        ArtifactByteStore(root) as store,
        patch.object(artifact_bytes.os, "link", link),
        patch.object(artifact_bytes.os, "fsync", fsync),
    ):
        store.put(identifier, io.BytesIO(b"complete"), max_bytes=8)


def concurrent_writer(root, identifier, barrier, outcomes):
    with ArtifactByteStore(root) as store:
        barrier.wait(timeout=5)
        try:
            store.put(identifier, io.BytesIO(b"complete"), max_bytes=8)
            outcomes.put("saved")
        except FileExistsError:
            outcomes.put("conflict")


@unittest.skipUnless(sys.platform == "linux", "Filesystem boundary requires Linux Docker")
class ArtifactByteTests(unittest.TestCase):
    def setUp(self):
        # Docker tests must use the approved named volume, not host temp storage.
        self.temp = tempfile.TemporaryDirectory(
            dir=os.environ["ARTIFACT_TEST_ROOT"]
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)

    def store(self):
        return ArtifactByteStore(str(self.root))

    def expected(self, identifier, data=b"complete"):
        return StoredBytes(identifier, hashlib.sha256(data).hexdigest(), len(data))

    def test_roundtrip_empty_and_multichunk_and_derived_locator(self):
        with self.store() as store:
            for data in (b"", b"x" * 150_000):
                identifier = uuid4()
                result = store.put(identifier, io.BytesIO(data), max_bytes=len(data))
                self.assertEqual(result, self.expected(identifier, data))
                self.assertEqual(result.storage_locator, f"artifacts/{identifier.hex}")
                self.assertEqual(store.read_verified(result, max_bytes=len(data)), data)
                target = self.root / result.storage_locator
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
                self.assertEqual(target.stat().st_nlink, 1)

    def test_existing_target_is_never_overwritten_even_identical(self):
        with self.store() as store:
            result = store.put(uuid4(), io.BytesIO(b"complete"), max_bytes=8)
            for data in (b"complete", b"different"):
                with self.assertRaises(FileExistsError):
                    store.put(result.id, io.BytesIO(data), max_bytes=9)
            self.assertEqual(store.read_verified(result, max_bytes=8), b"complete")
            self.assertEqual(len(list((self.root / "artifacts").iterdir())), 1)

    def test_overflow_bounded_requests_and_cleanup(self):
        class Stream:
            def __init__(self):
                self.requests = []

            def read(self, size):
                self.requests.append(size)
                return b"x" * size

        stream = Stream()
        with self.store() as store, self.assertRaises(ValueError):
            store.put(uuid4(), stream, max_bytes=70_000)
        self.assertLessEqual(max(stream.requests), 65536)
        self.assertEqual(sum(stream.requests), 70_001)
        self.assertEqual(list((self.root / "artifacts").iterdir()), [])

    def test_bad_stream_and_failure_remove_only_own_staging(self):
        class BadStream:
            def read(self, size):
                raise OSError("source failed")

        with self.store() as store:
            unrelated = self.root / "artifacts" / ".pending-unrelated"
            unrelated.write_bytes(b"leave alone")
            for source in (BadStream(), io.StringIO("text")):
                with self.assertRaises((OSError, TypeError)):
                    store.put(uuid4(), source, max_bytes=8)
            self.assertEqual(list(unrelated.parent.iterdir()), [unrelated])

    def test_oversupplying_stream_is_rejected(self):
        class BadStream:
            def read(self, size):
                return b"x" * (size + 1)

        with self.store() as store, self.assertRaises(ValueError):
            store.put(uuid4(), BadStream(), max_bytes=8)

    def test_partial_writes_and_storage_errors(self):
        original_write = os.write

        def partial_write(fd, data):
            return original_write(fd, data[:2])

        with self.store() as store:
            with patch("app.core.artifact_bytes.os.write", partial_write):
                result = store.put(uuid4(), io.BytesIO(b"complete"), max_bytes=8)
            self.assertEqual(store.read_verified(result, max_bytes=8), b"complete")
            for operation in ("write", "fsync"):
                identifier = uuid4()
                with (
                    patch(f"app.core.artifact_bytes.os.{operation}",
                          side_effect=OSError("storage failed")),
                    self.assertRaises(OSError),
                ):
                    store.put(identifier, io.BytesIO(b"complete"), max_bytes=8)
                self.assertFalse((self.root / "artifacts" / identifier.hex).exists())
            self.assertEqual(list((self.root / "artifacts").glob(".pending-*")), [])

    def test_post_publication_sync_error_does_not_rollback_bytes(self):
        original_fsync = os.fsync

        def fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("directory sync failed")
            original_fsync(fd)

        with self.store() as store:
            identifier = uuid4()
            with (
                patch("app.core.artifact_bytes.os.fsync", fsync),
                self.assertRaises(OSError),
            ):
                store.put(identifier, io.BytesIO(b"complete"), max_bytes=8)
            self.assertEqual(store.read_verified(self.expected(identifier), max_bytes=8),
                             b"complete")
            with self.assertRaises(FileExistsError):
                store.put(identifier, io.BytesIO(b"complete"), max_bytes=8)

    def test_staging_collision_is_not_deleted(self):
        collision = uuid4()
        with self.store() as store:
            pending = self.root / "artifacts" / f".pending-{collision.hex}"
            pending.symlink_to(self.root / "outside")
            with (
                patch("app.core.artifact_bytes.uuid4", return_value=collision),
                self.assertRaises(FileExistsError),
            ):
                store.put(uuid4(), io.BytesIO(b"complete"), max_bytes=8)
            self.assertTrue(pending.is_symlink())

    def test_integrity_and_read_limit_fail_before_returning_content(self):
        with self.store() as store:
            result = store.put(uuid4(), io.BytesIO(b"complete"), max_bytes=8)
            with self.assertRaises(ValueError):
                store.read_verified(result, max_bytes=7)
            for altered in (replace(result, sha256="0" * 64),
                            replace(result, byte_size=7),
                            replace(result, byte_size=9)):
                with self.assertRaises(ByteIntegrityError):
                    store.read_verified(altered, max_bytes=9)
            (self.root / result.storage_locator).write_bytes(b"tampered")
            with self.assertRaises(ByteIntegrityError):
                store.read_verified(result, max_bytes=8)

    def test_root_and_ancestor_symlinks_are_not_followed(self):
        actual = self.root / "actual"
        actual.mkdir(mode=0o700)
        alias = self.root / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        for root in (str(alias), str(alias / "child")):
            with self.assertRaises(OSError):
                ArtifactByteStore(root)

    def test_private_root_permissions_and_ownership_are_required(self):
        for mode in (0o755, 0o770, 0o1700):
            self.root.chmod(mode)
            with self.assertRaises(UnsafeStorageError):
                self.store()
        self.root.chmod(0o700)
        parent = self.root / "writable"
        parent.mkdir(mode=0o777)
        parent.chmod(0o777)
        child = parent / "private"
        child.mkdir(mode=0o700)
        with self.assertRaises(UnsafeStorageError):
            ArtifactByteStore(str(child))

    def test_foreign_uid_directory_is_rejected(self):
        # Provisioned by the disposable container's root bootstrap, not forged.
        foreign = Path(os.environ["ARTIFACT_TEST_ROOT"]) / "foreign"
        self.assertNotEqual(foreign.stat().st_uid, os.geteuid())
        with self.assertRaises(UnsafeStorageError):
            ArtifactByteStore(str(foreign))

    def test_changed_permissions_and_symlink_subdirectory_fail_closed(self):
        directory = self.root / "artifacts"
        directory.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            self.store()
        directory.unlink()
        with self.store() as store:
            directory.chmod(0o750)
            with self.assertRaises(UnsafeStorageError):
                store.put(uuid4(), io.BytesIO(b""), max_bytes=0)

    def test_pinned_root_permissions_are_rechecked(self):
        with self.store() as store:
            self.root.chmod(0o755)
            with self.assertRaises(UnsafeStorageError):
                store.put(uuid4(), io.BytesIO(b""), max_bytes=0)
        self.root.chmod(0o700)

    def test_symlink_hardlink_fifo_directory_and_file_modes_rejected(self):
        with self.store() as store:
            result = store.put(uuid4(), io.BytesIO(b"complete"), max_bytes=8)
            target = self.root / result.storage_locator
            alias = self.root / "hardlink"
            os.link(target, alias)
            with self.assertRaises(UnsafeStorageError):
                store.read_verified(result, max_bytes=8)
            alias.unlink()
            target.chmod(0o640)
            with self.assertRaises(UnsafeStorageError):
                store.read_verified(result, max_bytes=8)
            target.unlink()
            for kind in ("symlink", "fifo", "directory"):
                if kind == "symlink":
                    target.symlink_to(self.root / "outside")
                elif kind == "fifo":
                    os.mkfifo(target, mode=0o600)
                else:
                    target.mkdir(mode=0o700)
                with self.assertRaises(OSError):
                    store.read_verified(result, max_bytes=8)
                with self.assertRaises(FileExistsError):
                    store.put(result.id, io.BytesIO(b"complete"), max_bytes=8)
                if kind == "directory":
                    target.rmdir()
                else:
                    target.unlink()

    def test_invalid_ids_expectations_and_paths(self):
        for identifier in ("../escape", UUID(int=0)):
            with self.assertRaises((ValueError, TypeError)):
                StoredBytes(identifier, "a" * 64, 0)
            with self.store() as store, self.assertRaises((ValueError, TypeError)):
                store.put(identifier, io.BytesIO(b""), max_bytes=0)
        for digest, size in (("A" * 64, 0), ("g" * 64, 0), ("a" * 64, True),
                             ("a" * 64, -1), ("a" * 64, 2**63)):
            with self.assertRaises(ValueError):
                StoredBytes(uuid4(), digest, size)
        for path in ("relative", str(self.root) + "/../escape",
                     str(self.root) + "/./child"):
            with self.assertRaises(ValueError):
                ArtifactByteStore(path)
        with self.store() as store:
            for limit in (-1, True, 2**63):
                with self.assertRaises(ValueError):
                    store.put(uuid4(), io.BytesIO(b""), max_bytes=limit)

    def test_unsupported_capabilities_fail_closed(self):
        with (
            patch("app.core.artifact_bytes.sys.platform", "win32"),
            self.assertRaises(UnsupportedStorageError),
        ):
            self.store()
        with (
            patch("app.core.artifact_bytes.os.supports_dir_fd", set()),
            self.assertRaises(UnsupportedStorageError),
        ):
            self.store()

    def test_concurrent_writes_have_one_winner_same_instance_or_separate(self):
        for shared in (True, False):
            with self.store() as store:
                identifier = uuid4()
                barrier = Barrier(2)

                def attempt(index, barrier=barrier, shared=shared, identifier=identifier):
                    barrier.wait(timeout=5)
                    try:
                        if shared:
                            store.put(identifier, io.BytesIO(bytes([index])), max_bytes=1)
                        else:
                            with self.store() as other:
                                other.put(identifier, io.BytesIO(bytes([index])),
                                          max_bytes=1)
                        return "saved"
                    except FileExistsError:
                        return "conflict"

                with ThreadPoolExecutor(max_workers=2) as pool:
                    self.assertEqual(sorted(pool.map(attempt, range(2))),
                                     ["conflict", "saved"])

    def test_process_crash_states_are_not_swept_or_overwritten(self):
        with self.store():
            pass
        for boundary, exitcode in (("before-link", 71), ("after-link", 72),
                                   ("after-unlink", 73)):
            identifier = uuid4()
            process = multiprocessing.get_context("spawn").Process(
                target=crash_writer, args=(str(self.root), identifier, boundary)
            )
            process.start()
            process.join(timeout=10)
            if process.is_alive():
                process.kill()
                process.join()
                self.fail("crash worker hung")
            self.assertEqual(process.exitcode, exitcode)
            with self.store() as store:
                if boundary == "before-link":
                    with self.assertRaises(FileNotFoundError):
                        store.read_verified(self.expected(identifier), max_bytes=8)
                elif boundary == "after-link":
                    with self.assertRaises(UnsafeStorageError):
                        store.read_verified(self.expected(identifier), max_bytes=8)
                    with self.assertRaises(FileExistsError):
                        store.put(identifier, io.BytesIO(b"complete"), max_bytes=8)
                else:
                    self.assertEqual(store.read_verified(self.expected(identifier),
                                                         max_bytes=8), b"complete")
        self.assertEqual(len(list((self.root / "artifacts").glob(".pending-*"))), 2)

    def test_concurrent_processes_have_one_winner(self):
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        outcomes = context.Queue()
        identifier = uuid4()
        workers = [
            context.Process(target=concurrent_writer,
                            args=(str(self.root), identifier, barrier, outcomes))
            for _ in range(2)
        ]
        try:
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(sorted(outcomes.get(timeout=5) for _ in workers),
                             ["conflict", "saved"])
            with self.store() as store:
                self.assertEqual(store.read_verified(self.expected(identifier),
                                                     max_bytes=8), b"complete")
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.kill()
                    worker.join()
            outcomes.close()
            outcomes.join_thread()


class NativeUnsupportedTests(unittest.TestCase):
    def test_windows_refuses_before_filesystem_access(self):
        with (
            patch("app.core.artifact_bytes.sys.platform", "win32"),
            patch("app.core.artifact_bytes.os.open") as opened,
            self.assertRaises(UnsupportedStorageError),
        ):
            ArtifactByteStore("C:\\untrusted")
        opened.assert_not_called()


if __name__ == "__main__":
    if sys.platform != "linux":
        raise SystemExit("Run filesystem tests in Linux Docker")
    unittest.main()
