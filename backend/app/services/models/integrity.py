import hashlib
import re
from typing import BinaryIO


class ModelIntegrityError(ValueError):
    pass


def verify_model_file(stream: BinaryIO, *, expected_size: int, sha256: str) -> None:
    if type(expected_size) is not int or expected_size < 0:
        raise ValueError("Expected size must be a nonnegative byte count")
    if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
        raise ValueError("Expected SHA-256 must be a lowercase digest")

    digest = hashlib.sha256()
    remaining = expected_size
    while remaining:
        limit = min(remaining, 1024 * 1024)
        chunk = stream.read(limit)
        if not isinstance(chunk, bytes) or len(chunk) > limit:
            raise TypeError("Model stream returned invalid data")
        if not chunk:
            raise ModelIntegrityError("Model file size does not match")
        digest.update(chunk)
        remaining -= len(chunk)
    extra = stream.read(1)
    if not isinstance(extra, bytes) or len(extra) > 1:
        raise TypeError("Model stream returned invalid data")
    if extra:
        raise ModelIntegrityError("Model file size does not match")
    if digest.hexdigest() != sha256:
        raise ModelIntegrityError("Model file digest does not match")
