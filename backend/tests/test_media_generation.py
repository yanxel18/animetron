import json

import pytest

from app.engines.scene_plan import InvalidScenePlan, parse_scene_plan


def plan() -> dict:
    return {
        "language": "en",
        "characters": [{"id": "boat", "description": "A blue paper boat"}],
        "scenes": [
            {"id": "one", "narration": "The boat sailed.", "shot_prompt": "Boat on pond", "character_ids": ["boat"], "duration_ms": 30000},
            {"id": "two", "narration": "It found home.", "shot_prompt": "Boat at shore", "character_ids": ["boat"], "duration_ms": 60000},
        ],
    }


def parse(value: dict):
    return parse_scene_plan(json.dumps(value).encode())


def test_plan_preserves_scene_order_and_accepts_90_seconds() -> None:
    result = parse(plan())
    assert [scene.id for scene in result.scenes] == ["one", "two"]
    assert sum(scene.duration_ms for scene in result.scenes) == 90000


@pytest.mark.parametrize("change", ["over_budget", "duplicate_scene", "unknown_character", "empty_prompt", "boolean_duration", "extra_field"])
def test_rejects_invalid_model_output(change: str) -> None:
    value = plan()
    if change == "over_budget":
        value["scenes"][1]["duration_ms"] += 1
    elif change == "duplicate_scene":
        value["scenes"][1]["id"] = "one"
    elif change == "unknown_character":
        value["scenes"][0]["character_ids"] = ["missing"]
    elif change == "empty_prompt":
        value["scenes"][0]["shot_prompt"] = "  "
    elif change == "boolean_duration":
        value["scenes"][0]["duration_ms"] = True
    else:
        value["scenes"][0]["unexpected"] = "value"
    with pytest.raises(InvalidScenePlan):
        parse(value)


@pytest.mark.parametrize("raw", [b"not json", b'{"language":"en","language":"fr"}', b"\xff", b" " * 65537])
def test_rejects_malformed_or_oversized_json(raw: bytes) -> None:
    with pytest.raises(InvalidScenePlan):
        parse_scene_plan(raw)
