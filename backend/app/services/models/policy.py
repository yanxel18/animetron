"""Pure allowlist policy for trusted, immutable model references."""

from dataclasses import dataclass

from app.services.models.reference import ModelReference


@dataclass(frozen=True)
class ModelReferenceAllowlist:
    """Exact pins supplied by trusted configuration, not acquisition consent."""

    references: frozenset[ModelReference]

    def __post_init__(self) -> None:
        if type(self.references) is not frozenset or any(
            type(reference) is not ModelReference for reference in self.references
        ):
            raise TypeError("Model allowlist requires immutable pinned references")

    def allows(self, reference: ModelReference) -> bool:
        if type(reference) is not ModelReference:
            raise TypeError("A pinned model reference is required")
        return reference in self.references
