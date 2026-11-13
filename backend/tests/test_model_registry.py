import pytest

from app.services.models.preflight import AcquisitionBlocker, check_acquisition


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
