import hashlib
import io

import pytest

from app.services.models.integrity import ModelIntegrityError, verify_model_file
from app.services.models.preflight import AcquisitionBlocker, check_acquisition
from app.services.models.reference import ModelReference


def test_model_file_integrity_accepts_exact_size_and_hash() -> None:
    data = b"model weights"
    verify_model_file(
        io.BytesIO(data),
        expected_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


@pytest.mark.parametrize(
    ("data", "size", "digest"),
    [
        (b"abc", 2, hashlib.sha256(b"ab").hexdigest()),
        (b"ab", 3, hashlib.sha256(b"abc").hexdigest()),
        (b"abc", 3, hashlib.sha256(b"xyz").hexdigest()),
    ],
)
def test_model_file_integrity_rejects_truncation_extra_data_or_wrong_hash(
    data: bytes, size: int, digest: str
) -> None:
    with pytest.raises(ModelIntegrityError):
        verify_model_file(io.BytesIO(data), expected_size=size, sha256=digest)


def test_model_file_integrity_handles_partial_reads() -> None:
    class PartialReader(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            return super().read(min(size, 2))

    data = b"abcdef"
    verify_model_file(
        PartialReader(data),
        expected_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def test_model_file_integrity_bounds_reads_for_large_files() -> None:
    class BoundedReader(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            assert 0 < size <= 1024 * 1024
            return super().read(size)

    data = b"x" * (1024 * 1024 + 3)
    verify_model_file(
        BoundedReader(data),
        expected_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def test_model_file_integrity_rejects_nonblocking_end_of_stream() -> None:
    class NotReady(io.RawIOBase):
        def readinto(self, buffer: bytearray) -> None:
            return None

    with pytest.raises(TypeError):
        verify_model_file(
            NotReady(), expected_size=0, sha256=hashlib.sha256(b"").hexdigest()
        )


@pytest.mark.parametrize(
    ("size", "digest"), [(-1, "a" * 64), (True, "a" * 64), (0, "A" * 64)]
)
def test_model_file_integrity_rejects_invalid_expectations(
    size: int, digest: str
) -> None:
    with pytest.raises(ValueError):
        verify_model_file(io.BytesIO(), expected_size=size, sha256=digest)


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
