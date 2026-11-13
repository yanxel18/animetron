import re
from dataclasses import dataclass
from uuid import UUID

from app.services.workflows.document import validate_revision_identifier


@dataclass(frozen=True, order=True)
class ReviewDestination:
    provider: str
    account_id: str

    def __post_init__(self) -> None:
        for value in (self.provider, self.account_id):
            if not isinstance(value, str) or value != value.strip():
                raise ValueError("Invalid review destination")
            try:
                validate_revision_identifier(value)
            except ValueError:
                raise ValueError("Invalid review destination") from None


@dataclass(frozen=True)
class ReviewScope:
    run_id: UUID
    artifact_revision: str
    artifact_sha256: str
    caption_sha256: str
    destinations: tuple[ReviewDestination, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, UUID):
            raise TypeError("Invalid review run identifier")
        if not isinstance(self.artifact_revision, str):
            raise TypeError("Invalid artifact revision identifier")
        validate_revision_identifier(self.artifact_revision)
        for digest in (self.artifact_sha256, self.caption_sha256):
            if (
                not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise ValueError("Invalid review content digest")
        if (
            not isinstance(self.destinations, tuple)
            or not self.destinations
            or any(
                type(destination) is not ReviewDestination
                for destination in self.destinations
            )
            or len(set(self.destinations)) != len(self.destinations)
        ):
            raise ValueError("Invalid review destinations")
        object.__setattr__(self, "destinations", tuple(sorted(self.destinations)))
