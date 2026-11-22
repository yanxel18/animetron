import json

import pytest

from app.engines.draft_subtitles import InvalidSubtitleText, make_draft_srt
from app.engines.scene_plan import InvalidScenePlan


def plan(narrations: list[str], durations: list[int]) -> bytes:
    return json.dumps({
        "language": "ja", "characters": [],
        "scenes": [
            {"id": f"scene_{i}", "narration": text, "shot_prompt": "Scene",
             "character_ids": [], "duration_ms": duration}
            for i, (text, duration) in enumerate(zip(narrations, durations, strict=True))
        ],
    }).encode()


def test_generates_utf8_srt_using_scene_boundaries() -> None:
    output = make_draft_srt(plan(["こんにちは", "A boat sails."], [1200, 88800]))
    assert output.decode("utf-8") == (
        "1\n00:00:00,000 --> 00:00:01,200\nこんにちは\n\n"
        "2\n00:00:01,200 --> 00:01:30,000\nA boat sails.\n\n"
    )


def test_newlines_and_controls_cannot_inject_subtitle_cues() -> None:
    output = make_draft_srt(plan(["first\n\n2\r\n00:00:00,000 --> 00:00:01,000\x00end"], [1000]))
    assert output.decode() == "1\n00:00:00,000 --> 00:00:01,000\nfirst 2 00:00:00,000 --&gt; 00:00:01,000 end\n\n"


def test_unencodable_narration_fails_explicitly() -> None:
    with pytest.raises(InvalidScenePlan):
        make_draft_srt(plan(["\ud800"], [1000]))


def test_markup_is_escaped_and_empty_cleaned_text_is_rejected() -> None:
    output = make_draft_srt(plan(["<b>A & B</b>"], [1000])).decode()
    assert "&lt;b&gt;A &amp; B&lt;/b&gt;" in output
    with pytest.raises(InvalidSubtitleText):
        make_draft_srt(plan(["\x00\x01"], [1000]))


def test_invalid_plan_is_rejected() -> None:
    with pytest.raises(InvalidScenePlan):
        make_draft_srt(plan(["one", "two"], [1, 90000]))
