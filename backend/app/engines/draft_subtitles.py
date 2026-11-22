"""Generate scene-timed draft SRT; this does not perform speech alignment."""

import html
import unicodedata

from app.engines.scene_plan import parse_scene_plan
from app.engines.scene_timeline import build_scene_timeline


class InvalidSubtitleText(ValueError):
    """Narration cannot be represented as a subtitle."""


def _timestamp(ms: int) -> str:
    seconds, milliseconds = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def _safe_text(text: str) -> str:
    # SRT is line-oriented; control characters could create additional cues.
    cleaned = " ".join("".join(
        " " if unicodedata.category(char) == "Cc" else char for char in text
    ).split())
    if not cleaned:
        raise InvalidSubtitleText("Invalid subtitle text")
    return html.escape(cleaned, quote=False)


def make_draft_srt(raw_plan: bytes) -> bytes:
    """Return UTF-8 SRT using entire scene budgets, not measured voice timing."""
    plan = parse_scene_plan(raw_plan)
    timeline = build_scene_timeline(raw_plan)
    cues = []
    for index, (scene, timing) in enumerate(zip(plan.scenes, timeline.scenes, strict=True), 1):
        cues.append(
            f"{index}\n{_timestamp(timing.start_ms)} --> {_timestamp(timing.end_ms)}\n"
            f"{_safe_text(scene.narration)}\n\n"
        )
    try:
        return "".join(cues).encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidSubtitleText("Invalid subtitle text") from None
