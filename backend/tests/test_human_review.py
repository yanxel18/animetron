from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from app.services.reviews.scope import ReviewDestination, ReviewScope


def make_scope(**changes: object) -> ReviewScope:
    values = {
        "run_id": uuid4(),
        "artifact_revision": "render-1",
        "artifact_sha256": "a" * 64,
        "caption_sha256": "b" * 64,
        "destinations": (
            ReviewDestination("facebook", "page-1"),
            ReviewDestination("youtube", "channel-1"),
        ),
    }
    values.update(changes)
    return ReviewScope(**values)


def test_scope_is_immutable_and_destination_order_does_not_change_identity() -> None:
    original = make_scope()
    reordered = make_scope(
        run_id=original.run_id, destinations=tuple(reversed(original.destinations))
    )
    assert original == reordered
    with pytest.raises(FrozenInstanceError):
        original.artifact_revision = "other"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", uuid4()),
        ("artifact_revision", "render-2"),
        ("artifact_sha256", "c" * 64),
        ("caption_sha256", "c" * 64),
        ("destinations", (ReviewDestination("facebook", "page-2"),)),
    ],
)
def test_any_scope_change_invalidates_exact_match(field: str, value: object) -> None:
    original = make_scope()
    assert original != make_scope(**({"run_id": original.run_id} | {field: value}))


@pytest.mark.parametrize("digest", ["", "A" * 64, "g" * 64, "a" * 63, "a" * 65])
@pytest.mark.parametrize("field", ["artifact_sha256", "caption_sha256"])
def test_scope_rejects_noncanonical_digests(field: str, digest: str) -> None:
    with pytest.raises(ValueError):
        make_scope(**{field: digest})


def test_scope_rejects_missing_duplicate_or_mutable_destinations() -> None:
    destination = ReviewDestination("facebook", "page-1")
    for destinations in ((), (destination, destination), [destination]):
        with pytest.raises(ValueError):
            make_scope(destinations=destinations)


@pytest.mark.parametrize(
    ("provider", "account_id"),
    [("", "page"), ("facebook", " "), (" facebook", "page"), ("x", "a\x00b")],
)
def test_invalid_destination_is_rejected(provider: str, account_id: str) -> None:
    with pytest.raises(ValueError):
        ReviewDestination(provider, account_id)


def test_scope_rejects_invalid_revision_and_run_id() -> None:
    with pytest.raises(ValueError):
        make_scope(artifact_revision=" ")
    with pytest.raises(TypeError):
        make_scope(run_id="not-a-uuid")
