"""Bounded validation for untrusted story-planning model output."""

import json
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class InvalidScenePlan(ValueError):
    """The model output cannot be used as a scene plan."""


Text = Annotated[str, Field(min_length=1, max_length=4096)]
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


class PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="after")
    @classmethod
    def reject_blank_text(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            raise ValueError("blank text")
        return value


class Character(PlanModel):
    id: Identifier
    description: Text


class Scene(PlanModel):
    id: Identifier
    narration: Text
    shot_prompt: Text
    character_ids: list[Identifier] = Field(max_length=64)
    duration_ms: int = Field(gt=0, le=90000)


class ScenePlan(PlanModel):
    language: Annotated[str, Field(min_length=1, max_length=64)]
    characters: list[Character] = Field(max_length=64)
    scenes: list[Scene] = Field(min_length=1, max_length=90)

    @model_validator(mode="after")
    def check_relationships_and_budget(self) -> "ScenePlan":
        characters = {character.id for character in self.characters}
        if len(characters) != len(self.characters):
            raise ValueError("duplicate character id")
        if len({scene.id for scene in self.scenes}) != len(self.scenes):
            raise ValueError("duplicate scene id")
        if sum(scene.duration_ms for scene in self.scenes) > 90000:
            raise ValueError("duration budget exceeded")
        for scene in self.scenes:
            if len(set(scene.character_ids)) != len(scene.character_ids):
                raise ValueError("duplicate character reference")
            if not set(scene.character_ids) <= characters:
                raise ValueError("unknown character reference")
        return self


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_scene_plan(raw: bytes) -> ScenePlan:
    """Validate a UTF-8 JSON plan without exposing model output in errors."""
    if len(raw) > 65536:
        raise InvalidScenePlan("Invalid scene plan")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        return ScenePlan.model_validate(value)
    except (UnicodeDecodeError, ValueError, ValidationError, RecursionError):
        raise InvalidScenePlan("Invalid scene plan") from None
