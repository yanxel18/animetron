from enum import StrEnum


class AcquisitionBlocker(StrEnum):
    LICENSE_NOT_ACCEPTED = "LICENSE_NOT_ACCEPTED"
    ACCESS_NOT_CONFIRMED = "ACCESS_NOT_CONFIRMED"
    INSUFFICIENT_STORAGE = "INSUFFICIENT_STORAGE"


def check_acquisition(
    *,
    license_accepted: bool,
    access_confirmed: bool,
    required_bytes: int,
    available_bytes: int,
) -> tuple[AcquisitionBlocker, ...]:
    if type(license_accepted) is not bool or type(access_confirmed) is not bool:
        raise ValueError("License acceptance and access confirmation must be explicit")
    if (
        type(required_bytes) is not int
        or type(available_bytes) is not int
        or required_bytes <= 0
        or available_bytes < 0
    ):
        raise ValueError("Storage values must be known, valid byte counts")

    blockers = []
    if not license_accepted:
        blockers.append(AcquisitionBlocker.LICENSE_NOT_ACCEPTED)
    if not access_confirmed:
        blockers.append(AcquisitionBlocker.ACCESS_NOT_CONFIRMED)
    if available_bytes < required_bytes:
        blockers.append(AcquisitionBlocker.INSUFFICIENT_STORAGE)
    return tuple(blockers)
