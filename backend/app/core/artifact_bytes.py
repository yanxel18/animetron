"""Internal Linux-only bytes, independent of database transactions and HTTP."""

import errno
import hashlib
import os
import re
import stat
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import BinaryIO, Self
from uuid import RFC_4122, UUID, uuid4

if sys.platform == "linux":
    import fcntl

_CHUNK = 65536


class UnsupportedStorageError(RuntimeError):
    pass


class UnsafeStorageError(OSError):
    pass


class ByteIntegrityError(OSError):
    pass


class ArtifactAuditLimitExceeded(ValueError):
    pass


def _identifier(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise TypeError("Artifact identifier must be UUID4")
    if value.version != 4 or value.variant != RFC_4122:
        raise ValueError("Artifact identifier must be RFC-variant UUID4")


def _size(value: int) -> None:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError("Invalid byte limit or size")


@dataclass(frozen=True)
class StoredBytes:
    """Byte facts compatible with ArtifactMetadata, not authorization evidence."""

    id: UUID
    sha256: str
    byte_size: int

    def __post_init__(self) -> None:
        _identifier(self.id)
        _size(self.byte_size)
        if not isinstance(self.sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", self.sha256
        ) is None:
            raise ValueError("Invalid artifact digest")

    @property
    def storage_locator(self) -> str:
        return f"artifacts/{self.id.hex}"


@dataclass(frozen=True)
class ByteStoreInventory:
    files: tuple[StoredBytes, ...]
    unsafe_ids: tuple[UUID, ...]
    pending_names: tuple[str, ...]
    unsafe_pending_names: tuple[str, ...]
    unexpected_count: int


def _capabilities() -> None:
    if (
        sys.platform != "linux"
        or any(not hasattr(os, name) for name in (
            "O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK", "geteuid"
        ))
        or not {os.open, os.mkdir, os.unlink, os.link} <= os.supports_dir_fd
        or os.link not in os.supports_follow_symlinks
        or "fcntl" not in globals()
        or not hasattr(fcntl, "flock")
    ):
        raise UnsupportedStorageError("Secure Linux descriptor operations required")


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _private_directory(fd: int) -> None:
    info = os.fstat(fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise UnsafeStorageError("Storage directory must be service-owned mode 0700")


def _private_file(fd: int) -> os.stat_result:
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise UnsafeStorageError("Storage file must be private, regular and single-link")
    return info


class ArtifactByteStore:
    """Pinned private volume root. All service writers must use this protocol.

    Operations may share an instance; close must not race operations. Streams
    are caller-owned and synchronous. No orphan sweeps or DB writes; an exact
    object may be removed only when its caller still holds matching byte facts.
    """

    def __init__(self, root: str) -> None:
        _capabilities()
        if not isinstance(root, str) or not root.startswith("/") or "\0" in root:
            raise ValueError("An absolute Linux root is required")
        parts = root.split("/")[1:]
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise ValueError("Root components must be literal directory names")
        self._root_fd = -1
        fd = os.open("/", _directory_flags())
        try:
            # Never resolve a string path then open it. Walk pinned descriptors.
            for part in parts:
                info = os.fstat(fd)
                if (
                    info.st_uid not in (0, os.geteuid())
                    or info.st_mode & 0o022
                ):
                    raise UnsafeStorageError("Untrusted writable storage ancestor")
                child = os.open(part, _directory_flags(), dir_fd=fd)
                os.close(fd)
                fd = child
            _private_directory(fd)
            self._root_fd = fd
        except BaseException:
            os.close(fd)
            raise
        try:
            with self._locked(exclusive=True) as root_fd:
                try:
                    os.mkdir("artifacts", mode=0o700, dir_fd=root_fd)
                    os.fsync(root_fd)
                except FileExistsError:
                    pass
                with self._artifacts(root_fd):
                    pass
        except BaseException:
            self.close()
            raise

    @contextmanager
    def _locked(self, *, exclusive: bool) -> Iterator[int]:
        if self._root_fd == -1:
            raise RuntimeError("Storage is closed")
        # flock attaches to open descriptions, not Python instances or dup fds.
        # https://man7.org/linux/man-pages/man2/flock.2.html
        fd = os.open(".", _directory_flags(), dir_fd=self._root_fd)
        try:
            deadline = time.monotonic() + 5
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            while True:
                try:
                    fcntl.flock(fd, operation | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            _private_directory(fd)
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def _artifacts(self, root_fd: int) -> Iterator[int]:
        fd = os.open("artifacts", _directory_flags(), dir_fd=root_fd)
        try:
            _private_directory(fd)
            if os.fstat(fd).st_dev != os.fstat(root_fd).st_dev:
                raise UnsafeStorageError("Storage must be on one local volume")
            yield fd
        finally:
            os.close(fd)

    def put(
        self, artifact_id: UUID, source: BinaryIO, *, max_bytes: int
    ) -> StoredBytes:
        """Compute facts, publish once, never replace even identical content.

        Caller generates and retains the ID. A post-publication error has an
        unknown outcome; reconcile using trusted size/hash, never overwrite.
        """
        _identifier(artifact_id)
        _size(max_bytes)
        with self._locked(exclusive=True) as root_fd, self._artifacts(root_fd) as fd:
            pending = f".pending-{uuid4().hex}"
            output = os.open(
                pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                | os.O_CLOEXEC, 0o600, dir_fd=fd
            )
            try:
                # umask may only restrict creation; set exact private mode.
                os.fchmod(output, 0o600)
                _private_file(output)
                digest = hashlib.sha256()
                size = 0
                while True:
                    request = min(_CHUNK, max_bytes - size + 1)
                    chunk = source.read(request)
                    if not isinstance(chunk, bytes):
                        raise TypeError("Stream must return bytes")
                    if len(chunk) > request or size + len(chunk) > max_bytes:
                        raise ValueError("Artifact exceeds byte limit")
                    if not chunk:
                        break
                    view = memoryview(chunk)
                    while view:
                        written = os.write(output, view)
                        if written <= 0:
                            raise OSError("Storage write made no progress")
                        view = view[written:]
                    digest.update(chunk)
                    size += len(chunk)
                result = StoredBytes(artifact_id, digest.hexdigest(), size)
                _private_file(output)
                os.fsync(output)
                # linkat is atomic and EEXIST never overwrites a target.
                # https://man7.org/linux/man-pages/man2/link.2.html
                os.link(pending, artifact_id.hex, src_dir_fd=fd, dst_dir_fd=fd,
                        follow_symlinks=False)
            finally:
                try:
                    os.close(output)
                finally:
                    # Only this attempt's O_EXCL-created name, under pinned fd.
                    # Never remove a published name or scan other pending files.
                    os.unlink(pending, dir_fd=fd)
                    os.fsync(fd)
            return result

    def remove_if_matches(self, expected: StoredBytes) -> bool:
        """Remove one exact object after its caller proves it is unreferenced.

        Refuse missing, unsafe, changed or mismatched bytes. This is a narrow
        compensation primitive, not an orphan scanner or garbage collector.
        """
        if not isinstance(expected, StoredBytes):
            raise TypeError("Validated byte expectations required")
        with self._locked(exclusive=True) as root_fd, self._artifacts(root_fd) as fd:
            try:
                content = os.open(
                    expected.id.hex,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                    dir_fd=fd,
                )
            except FileNotFoundError:
                return False
            try:
                before = _private_file(content)
                if before.st_size != expected.byte_size:
                    return False
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = os.read(content, min(_CHUNK, expected.byte_size - size + 1))
                    if size + len(chunk) > expected.byte_size:
                        return False
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                after = _private_file(content)
                if (
                    size != expected.byte_size
                    or digest.hexdigest() != expected.sha256
                    or (
                        before.st_dev,
                        before.st_ino,
                        before.st_size,
                        before.st_mtime_ns,
                        before.st_ctime_ns,
                    )
                    != (
                        after.st_dev,
                        after.st_ino,
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                    )
                ):
                    return False
                named = os.stat(expected.id.hex, dir_fd=fd, follow_symlinks=False)
                if (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino):
                    return False
            finally:
                os.close(content)
            os.unlink(expected.id.hex, dir_fd=fd)
            os.fsync(fd)
            return True

    def read_verified(self, expected: StoredBytes, *, max_bytes: int) -> bytes:
        """Return bounded content only after complete size/hash verification."""
        _size(max_bytes)
        if not isinstance(expected, StoredBytes):
            raise TypeError("Validated byte expectations required")
        if expected.byte_size > max_bytes:
            raise ValueError("Artifact exceeds read limit")
        with self._locked(exclusive=False) as root_fd, self._artifacts(root_fd) as fd:
            content = os.open(
                expected.id.hex,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=fd,
            )
            try:
                before = _private_file(content)
                if before.st_size != expected.byte_size:
                    raise ByteIntegrityError("Artifact size mismatch")
                data = bytearray()
                digest = hashlib.sha256()
                while True:
                    chunk = os.read(content, min(_CHUNK, expected.byte_size - len(data) + 1))
                    if len(data) + len(chunk) > expected.byte_size:
                        raise ByteIntegrityError("Artifact grew during read")
                    if not chunk:
                        break
                    data.extend(chunk)
                    digest.update(chunk)
                after = _private_file(content)
                if (
                    len(data) != expected.byte_size
                    or digest.hexdigest() != expected.sha256
                    or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                ):
                    raise ByteIntegrityError("Artifact integrity mismatch")
                return bytes(data)
            finally:
                os.close(content)

    def audit(
        self, *, max_total_bytes: int, max_entries: int
    ) -> ByteStoreInventory:
        """Hash a bounded inventory without changing the volume or exposing paths."""
        _size(max_total_bytes)
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("Artifact audit entry limit must be positive")

        with self._locked(exclusive=True) as root_fd, self._artifacts(root_fd) as fd:
            names: list[str] = []
            with os.scandir(fd) as entries:
                for index, entry in enumerate(entries):
                    if index == max_entries:
                        raise ArtifactAuditLimitExceeded(
                            "Artifact audit exceeds configured entry limit"
                        )
                    names.append(entry.name)
            names.sort()

            files: list[StoredBytes] = []
            unsafe_ids: list[UUID] = []
            pending_names: list[str] = []
            unsafe_pending_names: list[str] = []
            unexpected_count = 0
            total_bytes = 0
            for name in names:
                if re.fullmatch(r"\.pending-[0-9a-f]{32}", name) is not None:
                    try:
                        content = os.open(
                            name,
                            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                            dir_fd=fd,
                        )
                    except OSError as exc:
                        if exc.errno in (errno.EACCES, errno.ELOOP, errno.EPERM):
                            unsafe_pending_names.append(name)
                            continue
                        raise
                    try:
                        try:
                            _private_file(content)
                        except UnsafeStorageError:
                            unsafe_pending_names.append(name)
                        else:
                            pending_names.append(name)
                    finally:
                        os.close(content)
                    continue
                try:
                    identifier = UUID(hex=name)
                except ValueError:
                    unexpected_count += 1
                    continue
                if identifier.hex != name:
                    unexpected_count += 1
                    continue
                try:
                    _identifier(identifier)
                except ValueError:
                    unexpected_count += 1
                    continue

                try:
                    content = os.open(
                        name,
                        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                        dir_fd=fd,
                    )
                except OSError as exc:
                    if exc.errno in (errno.EACCES, errno.ELOOP, errno.EPERM):
                        unsafe_ids.append(identifier)
                        continue
                    raise
                try:
                    try:
                        before = _private_file(content)
                    except UnsafeStorageError:
                        unsafe_ids.append(identifier)
                        continue
                    if total_bytes + before.st_size > max_total_bytes:
                        raise ArtifactAuditLimitExceeded(
                            "Artifact audit exceeds configured byte limit"
                        )

                    digest = hashlib.sha256()
                    size = 0
                    while size < before.st_size:
                        chunk = os.read(content, min(_CHUNK, before.st_size - size))
                        if not chunk:
                            break
                        digest.update(chunk)
                        size += len(chunk)
                    after = _private_file(content)
                    if (
                        size != before.st_size
                        or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                        != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    ):
                        raise ByteIntegrityError("Artifact changed during audit")
                    total_bytes += size
                    files.append(StoredBytes(identifier, digest.hexdigest(), size))
                finally:
                    os.close(content)

            return ByteStoreInventory(
                tuple(files), tuple(unsafe_ids), tuple(pending_names),
                tuple(unsafe_pending_names), unexpected_count,
            )

    def close(self) -> None:
        if self._root_fd != -1:
            os.close(self._root_fd)
            self._root_fd = -1

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None,
        exc: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        self.close()
