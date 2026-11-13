import pytest

from app.services.models.preflight import AcquisitionBlocker, check_acquisition
from app.services.models.reference import ModelReference


def test_model_reference_distinguishes_full_repository_and_revision() -> None:
    first = ModelReference("huggingface", "creator-a/model", "a" * 40)
    assert first != ModelReference("huggingface", "creator-b/model", "a" * 40)
    assert first != ModelReference("huggingface", "creator-a/model", "b" * 40)
    assert len({first, ModelReference("huggingface", "creator-a/model", "a" * 40)}) == 1


@pytest.mark.parametrize(
    "repository",
    ["", "../model", "a/../model", "https://example.com/model", "a\\model", "a//b"],
)
def test_model_reference_rejects_urls_and_invalid_repository_ids(
    repository: str,
) -> None:
    with pytest.raises(ValueError):
        ModelReference("huggingface", repository, "a" * 40)


@pytest.mark.parametrize("revision", ["main", "a" * 7, "a" * 39, "g" * 40, "A" * 40])
def test_model_reference_requires_a_full_canonical_commit_hash(revision: str) -> None:
    with pytest.raises(ValueError):
        ModelReference("huggingface", "creator/model", revision)


def test_model_reference_does_not_accept_unknown_providers() -> None:
    with pytest.raises(ValueError):
        ModelReference("other", "creator/model", "a" * 40)


def test_accepted_access_and_sufficient_space_pass_preflight() -> None:
    assert (
        check_acquisition(
            license_accepted=True,
            access_confirmed=True,
            required_bytes=100,
            available_bytes=100,
        )
        == ()
    )


def test_all_unsatisfied_requirements_are_reported() -> None:
    assert check_acquisition(
        license_accepted=False,
        access_confirmed=False,
        required_bytes=100,
        available_bytes=99,
    ) == (
        AcquisitionBlocker.LICENSE_NOT_ACCEPTED,
        AcquisitionBlocker.ACCESS_NOT_CONFIRMED,
        AcquisitionBlocker.INSUFFICIENT_STORAGE,
    )


@pytest.mark.parametrize(
    ("required_bytes", "available_bytes"),
    [(0, 100), (-1, 100), (100, -1), (100, None), (True, 100)],
)
def test_invalid_or_unknown_storage_is_not_eligible(
    required_bytes: object, available_bytes: object
) -> None:
    with pytest.raises(ValueError):
        check_acquisition(
            license_accepted=True,
            access_confirmed=True,
            required_bytes=required_bytes,
            available_bytes=available_bytes,
        )


@pytest.mark.parametrize(
    ("license_accepted", "access_confirmed"), [(None, True), (True, "yes"), (1, True)]
)
def test_implicit_consent_and_access_are_rejected(
    license_accepted: object, access_confirmed: object
) -> None:
    with pytest.raises(ValueError):
        check_acquisition(
            license_accepted=license_accepted,
            access_confirmed=access_confirmed,
            required_bytes=1,
            available_bytes=1,
        )
