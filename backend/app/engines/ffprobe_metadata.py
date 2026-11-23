"""Parse a restricted full ffprobe JSON report, without probing or decoding.

Requires square pixels, no rotation/side data, zero starts, one video and one
audio stream with known durations. Valid but unsupported media is rejected.
Supplied JSON is not trusted proof of media properties or decodability.
See https://ffmpeg.org/ffprobe.html (-show_streams -show_format -of json).
"""

import json
import math
import re
from typing import Any

from app.engines.media_probe import InvalidMediaProbe, MediaProbe, validate_media_probe

_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,9})?", re.ASCII)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError("nonfinite JSON")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite JSON")
    return result


def _nanoseconds(value: Any) -> int:
    if type(value) is not str or len(value) > 32 or not _DECIMAL.fullmatch(value):
        raise ValueError("invalid timestamp")
    whole, _, fraction = value.partition(".")
    return int(whole) * 1_000_000_000 + int(fraction.ljust(9, "0"))


def parse_ffprobe_metadata(raw: bytes) -> MediaProbe:
    """Convert bounded supplied metadata to validated facts, rounding duration up."""
    try:
        if type(raw) is not bytes or len(raw) > 65536:
            raise ValueError("invalid bytes")
        report = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                            parse_constant=_reject_constant, parse_float=_finite_float)
        if type(report) is not dict or "error" in report:
            raise ValueError("invalid report")
        streams, container = report.get("streams"), report.get("format")
        if (type(streams) is not list or len(streams) != 2
                or type(container) is not dict or "error" in container):
            raise ValueError("invalid sections")
        durations = []
        indexes = set()
        for stream in streams:
            if type(stream) is not dict:
                raise ValueError("invalid stream")
            index = stream.get("index")
            if type(index) is not int or index < 0 or index in indexes:
                raise ValueError("invalid index")
            indexes.add(index)
        for section in [container, *streams]:
            if _nanoseconds(section.get("start_time")) != 0:
                raise ValueError("offset unsupported")
            duration = _nanoseconds(section.get("duration"))
            if not 0 < duration <= 90_000_000_000:
                raise ValueError("invalid duration")
            durations.append(duration)
        videos = [s for s in streams if s.get("codec_type") == "video"]
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        if len(videos) != 1 or len(audios) != 1:
            raise ValueError("ambiguous streams")
        video = videos[0]
        disposition, tags = video.get("disposition"), video.get("tags", {})
        if (
            video.get("sample_aspect_ratio") != "1:1"
            or video.get("display_aspect_ratio", "9:16") != "9:16"
            or type(disposition) is not dict
            or type(disposition.get("attached_pic")) is not int
            or disposition["attached_pic"] != 0
            or type(tags) is not dict or "rotate" in tags
            or video.get("side_data_list", []) != []
        ):
            raise ValueError("unsupported geometry")
        milliseconds = (max(durations) + 999_999) // 1_000_000
        probe = MediaProbe(video.get("width"), video.get("height"), milliseconds, True)
        validate_media_probe(probe)
        return probe
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidMediaProbe("Invalid media probe") from None
