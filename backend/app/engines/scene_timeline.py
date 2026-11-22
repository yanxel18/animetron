"""Derive contiguous scene timing budgets from a validated story plan."""

from dataclasses import dataclass

from app.engines.scene_plan import parse_scene_plan


@dataclass(frozen=True, slots=True)
class SceneTiming:
    scene_id: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class SceneTimeline:
    scenes: tuple[SceneTiming, ...]
    duration_ms: int


def build_scene_timeline(raw_plan: bytes) -> SceneTimeline:
    """Build half-open [start, end) budgets; not measured media timing."""
    plan = parse_scene_plan(raw_plan)
    position = 0
    timings = []
    for scene in plan.scenes:
        end = position + scene.duration_ms
        timings.append(SceneTiming(scene.id, position, end))
        position = end
    return SceneTimeline(tuple(timings), position)
