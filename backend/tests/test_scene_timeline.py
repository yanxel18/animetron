import json
from dataclasses import FrozenInstanceError

import pytest

from app.engines.scene_plan import InvalidScenePlan
from app.engines.scene_timeline import build_scene_timeline


def encoded_plan(durations: list[int]) -> bytes:
    return json.dumps({
        "language": "en",
        "characters": [],
        "scenes": [
            {"id": f"scene_{i}", "narration": "A story.", "shot_prompt": "A scene",
             "character_ids": [], "duration_ms": duration}
            for i, duration in enumerate(durations)
        ],
    }).encode()


def test_timeline_is_contiguous_and_preserves_plan_order() -> None:
    result = build_scene_timeline(encoded_plan([1200, 3300, 100]))
    assert [(s.scene_id, s.start_ms, s.end_ms) for s in result.scenes] == [
        ("scene_0", 0, 1200), ("scene_1", 1200, 4500), ("scene_2", 4500, 4600),
    ]
    assert result.duration_ms == 4600


def test_boundary_is_exact_and_output_is_immutable() -> None:
    result = build_scene_timeline(encoded_plan([1, 89999]))
    assert result.duration_ms == result.scenes[-1].end_ms == 90000
    with pytest.raises(FrozenInstanceError):
        result.scenes[0].start_ms = 9
    assert isinstance(result.scenes, tuple)


@pytest.mark.parametrize("raw", [encoded_plan([1, 90000]), encoded_plan([]), b"bad json"])
def test_invalid_plans_do_not_produce_a_timeline(raw: bytes) -> None:
    with pytest.raises(InvalidScenePlan):
        build_scene_timeline(raw)
