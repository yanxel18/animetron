"""Compose verified storage reads with internal media probing.

The caller owns authorization and trusts the store, staging directory and tool.
FFprobe's file protocol can access other local files: do not pass untrusted media
without separately established isolation. This does not establish decodability.
"""

import math
from pathlib import Path

from app.core.artifact_bytes import ArtifactByteStore, StoredBytes
from app.engines.media_bytes_probe import VerifiedMediaProbe, probe_media_bytes
from app.engines.media_probe import InvalidMediaProbe


def probe_stored_media(
    store: ArtifactByteStore,
    expected: StoredBytes,
    ffprobe_path: Path,
    staging_root: Path,
    *,
    max_bytes: int = 64 * 1024 * 1024,
    timeout_seconds: float = 10,
) -> VerifiedMediaProbe:
    """Read verified bytes, then stage and probe them; no access control is added."""
    try:
        if (not isinstance(expected, StoredBytes) or type(max_bytes) is not int
                or not 1 <= max_bytes <= 64 * 1024 * 1024
                or not 0 < expected.byte_size <= max_bytes
                or type(timeout_seconds) not in (int, float)
                or not 0 < timeout_seconds <= 30 or not math.isfinite(timeout_seconds)):
            raise ValueError("invalid artifact")
        raw = store.read_verified(expected, max_bytes=max_bytes)
        return probe_media_bytes(raw, expected.sha256, ffprobe_path, staging_root,
                                 max_bytes=max_bytes, timeout_seconds=timeout_seconds)
    except (OSError, RuntimeError, ValueError):
        raise InvalidMediaProbe("Invalid media probe") from None
