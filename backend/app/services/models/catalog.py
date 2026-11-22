"""In-memory selection of manifests supplied by trusted configuration."""

from dataclasses import dataclass

from app.services.models.manifest import ModelManifest
from app.services.models.reference import ModelReference


@dataclass(frozen=True)
class ModelManifestCatalog:
    """Select exact pins without loading models or granting acquisition consent."""

    manifests: tuple[ModelManifest, ...]

    def __post_init__(self) -> None:
        if type(self.manifests) is not tuple or any(
            type(manifest) is not ModelManifest for manifest in self.manifests
        ):
            raise TypeError("Model catalog requires an immutable tuple of manifests")
        references = {manifest.reference for manifest in self.manifests}
        if len(references) != len(self.manifests):
            raise ValueError("Model catalog contains duplicate pinned references")

    def resolve(self, reference: ModelReference) -> ModelManifest | None:
        if type(reference) is not ModelReference:
            raise TypeError("A pinned model reference is required")
        return next(
            (manifest for manifest in self.manifests if manifest.reference == reference),
            None,
        )
