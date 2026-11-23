"""Bounded validation for raster artifacts accepted by the upload API."""

import struct
import zlib
from typing import Any, BinaryIO

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PNG_DIMENSION = 4096
MAX_PNG_DECODED_BYTES = 16 * 1024 * 1024
MAX_PNG_CHUNKS = 4096
_PNG_CHANNELS = {2: 3, 6: 4}


class ArtifactMediaError(ValueError):
    """The input is not a supported, bounded PNG image."""


def _read_exact(source: BinaryIO, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = source.read(size - len(data))
        if not isinstance(chunk, bytes) or not chunk:
            raise ArtifactMediaError("Truncated PNG")
        data.extend(chunk)
    return bytes(data)


def validate_png(
    source: BinaryIO,
    *,
    max_bytes: int = 128 * 1024 * 1024,
    max_decoded_bytes: int = MAX_PNG_DECODED_BYTES,
) -> tuple[int, int]:
    """Validate a non-interlaced 8-bit RGB/RGBA PNG with bounded inflation.

    Metadata and ancillary chunks are rejected; accepted files contain only
    IHDR, consecutive IDAT chunks and IEND. Pixel rows are inflated only up to
    the declared, capped dimensions, and chunk CRCs are verified.
    """
    if type(max_bytes) is not int or max_bytes < len(PNG_SIGNATURE):
        raise ValueError("PNG byte limit is invalid")
    if type(max_decoded_bytes) is not int or max_decoded_bytes < 1:
        raise ValueError("PNG decoded-byte limit is invalid")
    if _read_exact(source, len(PNG_SIGNATURE)) != PNG_SIGNATURE:
        raise ArtifactMediaError("Unsupported artifact signature")

    total_bytes = len(PNG_SIGNATURE)
    chunk_count = 0
    width = height = row_bytes = decoded_size = 0
    channels = 0
    # The standard-library zlib extension does not expose a mypy type.
    inflater: Any = None
    decoded = bytearray()
    seen_idat = False
    ended_idat = False
    seen_iend = False

    while not seen_iend:
        chunk_count += 1
        if chunk_count > MAX_PNG_CHUNKS:
            raise ArtifactMediaError("PNG contains too many chunks")
        if total_bytes + 8 > max_bytes:
            raise ArtifactMediaError("PNG exceeds byte limit")
        header = _read_exact(source, 8)
        total_bytes += len(header)
        chunk_length = struct.unpack(">I", header[:4])[0]
        chunk_type = header[4:]
        if total_bytes + chunk_length + 4 > max_bytes:
            raise ArtifactMediaError("PNG exceeds byte limit")
        if chunk_type not in (b"IHDR", b"IDAT", b"IEND"):
            raise ArtifactMediaError("Unsupported PNG chunk")
        if chunk_type == b"IHDR":
            if chunk_count != 1 or chunk_length != 13:
                raise ArtifactMediaError("Invalid PNG header")
            data = _read_exact(source, chunk_length)
            total_bytes += chunk_length
            checksum = zlib.crc32(data, zlib.crc32(chunk_type))
            if struct.unpack(">I", _read_exact(source, 4))[0] != checksum:
                raise ArtifactMediaError("Invalid PNG checksum")
            total_bytes += 4
            width, height, bit_depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", data)
            )
            channels = _PNG_CHANNELS.get(color_type, 0)
            if (
                width < 1
                or height < 1
                or width > MAX_PNG_DIMENSION
                or height > MAX_PNG_DIMENSION
                or bit_depth != 8
                or channels == 0
                or compression != 0
                or filtering != 0
                or interlace != 0
            ):
                raise ArtifactMediaError("Unsupported PNG format")
            row_bytes = width * channels
            decoded_size = (row_bytes + 1) * height
            if decoded_size > min(max_decoded_bytes, MAX_PNG_DECODED_BYTES):
                raise ArtifactMediaError("PNG decoded data exceeds limit")
            inflater = zlib.decompressobj()
            continue

        if chunk_type == b"IDAT":
            if inflater is None or ended_idat:
                raise ArtifactMediaError("Invalid PNG data order")
            seen_idat = True
            checksum = zlib.crc32(chunk_type)
            remaining = chunk_length
            while remaining:
                compressed = _read_exact(source, min(64 * 1024, remaining))
                remaining -= len(compressed)
                total_bytes += len(compressed)
                checksum = zlib.crc32(compressed, checksum)
                try:
                    output = inflater.decompress(
                        compressed, decoded_size + 1 - len(decoded)
                    )
                except zlib.error as exc:
                    raise ArtifactMediaError("Invalid PNG data") from exc
                decoded.extend(output)
                if (
                    len(decoded) > decoded_size
                    or inflater.unused_data
                    or inflater.unconsumed_tail
                ):
                    raise ArtifactMediaError("PNG decoded data exceeds limit")
            if struct.unpack(">I", _read_exact(source, 4))[0] != checksum:
                raise ArtifactMediaError("Invalid PNG checksum")
            total_bytes += 4
            continue

        if chunk_type == b"IEND":
            if chunk_length != 0 or not seen_idat or inflater is None:
                raise ArtifactMediaError("Invalid PNG ending")
            ended_idat = True
            checksum = zlib.crc32(chunk_type)
            if struct.unpack(">I", _read_exact(source, 4))[0] != checksum:
                raise ArtifactMediaError("Invalid PNG checksum")
            total_bytes += 4
            seen_iend = True

    if total_bytes > max_bytes or source.read(1) != b"":
        raise ArtifactMediaError("PNG exceeds byte limit or has trailing data")
    if not inflater.eof or len(decoded) != decoded_size:
        raise ArtifactMediaError("Incomplete PNG data")
    if any(decoded[offset] > 4 for offset in range(0, decoded_size, row_bytes + 1)):
        raise ArtifactMediaError("Invalid PNG row filter")
    return width, height
