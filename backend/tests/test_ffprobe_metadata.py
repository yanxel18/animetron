import json
from decimal import localcontext

import pytest

from app.engines.ffprobe_metadata import parse_ffprobe_metadata
from app.engines.media_probe import InvalidMediaProbe, MediaProbe


@pytest.fixture
def metadata():
    return {
        "format": {"duration": "45.000000", "start_time": "0.000000"},
        "streams": [
            {"index": 0, "codec_type": "video", "width": 1080, "height": 1920,
             "sample_aspect_ratio": "1:1", "duration": "45", "start_time": "0",
             "disposition": {"attached_pic": 0}},
            {"index": 1, "codec_type": "audio", "duration": "45", "start_time": "0"},
        ],
    }


def parse(value):
    return parse_ffprobe_metadata(json.dumps(value).encode())


def test_supported_metadata(metadata):
    assert parse(metadata) == MediaProbe(1080, 1920, 45000, True)


def test_rounding_is_independent_of_ambient_decimal_precision(metadata):
    metadata["streams"][1]["duration"] = "45.123456789"
    with localcontext() as context:
        context.prec = 2
        assert parse(metadata).duration_ms == 45124


@pytest.mark.parametrize("field,value", [("tags", None), ("tags", []),
    ("disposition", None), ("disposition", []), ("side_data_list", None)])
def test_malformed_nested_geometry_sections_are_rejected(metadata, field, value):
    metadata["streams"][0][field] = value
    with pytest.raises(InvalidMediaProbe):
        parse(metadata)


@pytest.mark.parametrize("field", ["duration", "start_time"])
def test_missing_format_timing_fails(metadata, field):
    del metadata["format"][field]
    with pytest.raises(InvalidMediaProbe):
        parse(metadata)


def test_missing_audio_fails(metadata):
    metadata["streams"].pop()
    with pytest.raises(InvalidMediaProbe):
        parse(metadata)


@pytest.mark.parametrize("duration,expected", [("0.000000001", 1), ("30", 30000),
                                              ("60.000000001", 60001), ("90", 90000)])
def test_duration_rounds_up_and_uses_longest_measurement(metadata, duration, expected):
    for section in [metadata["format"], *metadata["streams"]]:
        section["duration"] = duration
    assert parse(metadata).duration_ms == expected
    metadata["streams"][1]["duration"] = "90"
    assert parse(metadata).duration_ms == 90000


@pytest.mark.parametrize("duration", ["0", "-1", "91", "90.000000001", "NaN", "Infinity",
                                      "1e1", "01", "1.1234567890", "N/A", 45, True, None])
@pytest.mark.parametrize("section", ["format", 0, 1])
def test_bad_or_missing_duration_fails(metadata, duration, section):
    target = metadata["format"] if section == "format" else metadata["streams"][section]
    target["duration"] = duration
    with pytest.raises(InvalidMediaProbe):
        parse(metadata)
    del target["duration"]
    with pytest.raises(InvalidMediaProbe):
        parse(metadata)


@pytest.mark.parametrize("field,value", [("width", True), ("height", 1920.0),
    ("width", 1920), ("sample_aspect_ratio", "N/A"), ("sample_aspect_ratio", "2:1"),
    ("disposition", {"attached_pic": 1}), ("disposition", {"attached_pic": False}),
    ("side_data_list", [{"rotation": 90}]), ("tags", {"rotate": "0"}),
    ("start_time", "0.000001"), ("display_aspect_ratio", "16:9")])
def test_ambiguous_video_geometry_or_timing_fails(metadata, field, value):
    metadata["streams"][0][field] = value
    with pytest.raises(InvalidMediaProbe):
        parse(metadata)


@pytest.mark.parametrize("streams", [[], [{"codec_type": "video"}], [None, None],
    [{"codec_type": "audio"}, {"codec_type": "audio"}]])
def test_ambiguous_streams_fail(metadata, streams):
    metadata["streams"] = streams
    with pytest.raises(InvalidMediaProbe):
        parse(metadata)


@pytest.mark.parametrize("index", [0, -1, True, "1", None])
def test_invalid_or_duplicate_stream_indexes_fail(metadata, index):
    metadata["streams"][1]["index"] = index
    with pytest.raises(InvalidMediaProbe):
        parse(metadata)


@pytest.mark.parametrize("section", ["root", "format"])
def test_reported_probe_error_is_rejected(metadata, section):
    target = metadata if section == "root" else metadata["format"]
    target["error"] = {"string": "private-filename"}
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        parse(metadata)


@pytest.mark.parametrize("raw", [b"{}", b"[]", b"null", b"\xff", b"{" , b" " * 65537,
    b'{"format":{},"format":{}}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e99999}',
    b"[" * 2000 + b"]" * 2000])
def test_malformed_unbounded_or_duplicate_json_fails_without_echoing_input(raw):
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        parse_ffprobe_metadata(raw)
