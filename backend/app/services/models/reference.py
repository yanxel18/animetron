import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelReference:
    provider: str
    repository: str
    revision: str

    def __post_init__(self) -> None:
        if self.provider != "huggingface":
            raise ValueError("Unsupported model provider")
        if not isinstance(self.repository, str):
            raise TypeError("Invalid model repository")
        parts = self.repository.split("/")
        if len(parts) not in (1, 2) or any(
            re.fullmatch(r"[A-Za-z0-9_](?:[A-Za-z0-9_.-]{0,94}[A-Za-z0-9_])?", part)
            is None
            or "--" in part
            or ".." in part
            for part in parts
        ):
            raise ValueError("Invalid model repository")
        if (
            not isinstance(self.revision, str)
            or re.fullmatch(r"[0-9a-f]{40}", self.revision) is None
        ):
            raise ValueError("Model revision must be a full lowercase commit hash")
