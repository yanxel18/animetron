from dataclasses import dataclass

from app.services.models.integrity import validate_sha256
from app.services.models.reference import ModelReference


@dataclass(frozen=True)
class ModelFile:
    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, str):
            raise TypeError("Invalid model file name")
        try:
            encoded = self.path.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Invalid model file name") from None
        if (
            not encoded
            or len(encoded) > 1024
            or "\\" in self.path
            or ":" in self.path
            or any(ord(char) < 32 or ord(char) == 127 for char in self.path)
            or any(part in ("", ".", "..") for part in self.path.split("/"))
        ):
            raise ValueError("Invalid model file name")
        if type(self.size) is not int or self.size < 0:
            raise ValueError("Invalid model file size")
        validate_sha256(self.sha256)


@dataclass(frozen=True)
class ModelManifest:
    reference: ModelReference
    engine: str
    license_id: str
    files: tuple[ModelFile, ...]
    estimated_bytes: int

    def __post_init__(self) -> None:
        if type(self.reference) is not ModelReference:
            raise TypeError("Invalid model reference")
        for value in (self.engine, self.license_id):
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > 128
                or any(ord(char) < 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError("Invalid model manifest identifier")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError("Invalid model manifest identifier") from None
        if (
            type(self.files) is not tuple
            or not self.files
            or any(type(file) is not ModelFile for file in self.files)
        ):
            raise ValueError("Invalid model manifest files")
        names = {file.path.casefold() for file in self.files}
        if len(names) != len(self.files):
            raise ValueError("Duplicate model manifest file")
        for name in names:
            parts = name.split("/")
            if any("/".join(parts[:index]) in names for index in range(1, len(parts))):
                raise ValueError("Model file cannot also be a directory")
        if (
            type(self.estimated_bytes) is not int
            or self.estimated_bytes < 1
            or self.estimated_bytes < sum(file.size for file in self.files)
        ):
            raise ValueError("Invalid model storage estimate")
