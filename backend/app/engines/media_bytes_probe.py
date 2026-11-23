"""Probe bounded supplied bytes staged beneath a trusted server directory.

The caller controls the root and executable; untrusted actors must not be able
to modify staging files. Before/after hashes detect ordinary changes, not a
replacement-and-restoration attack or a compromised probe. The expected digest
checks consistency, not authenticity or authorization. No immutable artifact or
decodability guarantee is established. OS cleanup failure may leave temporary
files behind, but cannot produce a successful result.
"""

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.engines.local_media_probe import probe_local_media
from app.engines.media_probe import InvalidMediaProbe, MediaProbe


@dataclass(frozen=True)
class VerifiedMediaProbe:
    """Probe facts associated with a checked supplied payload digest and size."""

    probe: MediaProbe
    sha256: str
    size_bytes: int


def probe_media_bytes(
    raw: bytes,
    expected_sha256: str,
    ffprobe_path: Path,
    staging_root: Path,
    *,
    max_bytes: int = 64 * 1024 * 1024,
    timeout_seconds: float = 10,
) -> VerifiedMediaProbe:
    """Check, stage, probe and recheck bytes, cleaning the stage before success."""
    try:
        if (type(max_bytes) is not int or not 1 <= max_bytes <= 64 * 1024 * 1024
                or type(raw) is not bytes or not 0 < len(raw) <= max_bytes
                or type(expected_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", expected_sha256, re.ASCII) is None
                or type(timeout_seconds) not in (int, float)
                or not 0 < timeout_seconds <= 30 or not math.isfinite(timeout_seconds)):
            raise ValueError("invalid input")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != expected_sha256:
            raise ValueError("digest mismatch")
        root = staging_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("invalid staging root")
        with TemporaryDirectory(dir=root, prefix="media-probe-") as directory:
            path = Path(directory) / "media.bin"
            if path.write_bytes(raw) != len(raw):
                raise ValueError("incomplete write")
            probe = probe_local_media(path, ffprobe_path, timeout_seconds=timeout_seconds)
            with path.open("rb") as staged:
                checked = staged.read(max_bytes + 1)
            if len(checked) != len(raw) or hashlib.sha256(checked).hexdigest() != digest:
                raise ValueError("staged payload changed")
        return VerifiedMediaProbe(probe, digest, len(raw))
    except (OSError, RuntimeError, ValueError):
        raise InvalidMediaProbe("Invalid media probe") from None
