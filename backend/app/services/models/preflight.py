from enum import StrEnum

from app.services.models.manifest import ModelManifest
from app.services.models.policy import ModelReferenceAllowlist


class AcquisitionBlocker(StrEnum):
    REFERENCE_NOT_ALLOWED = "REFERENCE_NOT_ALLOWED"
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


def check_manifest_acquisition(
    *,
    manifest: ModelManifest,
    allowlist: ModelReferenceAllowlist,
    license_accepted: bool,
    access_confirmed: bool,
    available_bytes: int,
) -> tuple[AcquisitionBlocker, ...]:
    """Evaluate trusted caller-supplied facts, not authorization or readiness."""
    if type(manifest) is not ModelManifest or type(allowlist) is not ModelReferenceAllowlist:
        raise TypeError("A model manifest and trusted allowlist are required")
    blockers = check_acquisition(
        license_accepted=license_accepted,
        access_confirmed=access_confirmed,
        required_bytes=manifest.estimated_bytes,
        available_bytes=available_bytes,
    )
    if not allowlist.allows(manifest.reference):
        return (AcquisitionBlocker.REFERENCE_NOT_ALLOWED, *blockers)
    return blockers
