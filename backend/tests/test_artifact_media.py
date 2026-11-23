import io
import struct
import zlib

import pytest

from app.core.artifact_media import ArtifactMediaError, validate_png


def chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(data, zlib.crc32(kind))
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)


def png(width: int = 1, height: int = 1, *, pixels: bytes | None = None) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw_pixels = pixels if pixels is not None else b"\x00\xff\x00\x00\xff" * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw_pixels))
        + chunk(b"IEND", b"")
    )


def test_validate_png_returns_dimensions_after_bounded_decode() -> None:
    assert validate_png(io.BytesIO(png())) == (1, 1)


@pytest.mark.parametrize("content", [b"not a png", png() + b"trailing"])
def test_validate_png_rejects_signature_and_trailing_bytes(content: bytes) -> None:
    with pytest.raises(ArtifactMediaError):
        validate_png(io.BytesIO(content))


def test_validate_png_rejects_bad_chunk_crc() -> None:
    content = bytearray(png())
    content[-1] ^= 1

    with pytest.raises(ArtifactMediaError):
        validate_png(io.BytesIO(content))


def test_validate_png_rejects_decoded_data_over_budget() -> None:
    with pytest.raises(ArtifactMediaError):
        validate_png(io.BytesIO(png()), max_decoded_bytes=4)


def test_validate_png_rejects_dimensions_over_limit_before_inflation() -> None:
    with pytest.raises(ArtifactMediaError):
        validate_png(io.BytesIO(png(width=4097)))


def test_validate_png_rejects_invalid_row_filter() -> None:
    with pytest.raises(ArtifactMediaError):
        validate_png(io.BytesIO(png(pixels=b"\x05\xff\x00\x00\xff")))
