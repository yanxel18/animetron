import hashlib
import io

import pytest

from app.services.models.catalog import ModelManifestCatalog
from app.services.models.integrity import ModelIntegrityError, verify_model_file
from app.services.models.manifest import ModelFile, ModelManifest
from app.services.models.policy import ModelReferenceAllowlist
from app.services.models.preflight import (
    AcquisitionBlocker,
    check_acquisition,
    check_catalog_acquisition,
    check_manifest_acquisition,
)
from app.services.models.reference import ModelReference


def test_manifest_preserves_pinned_reference_and_file_metadata() -> None:
    reference = ModelReference("huggingface", "creator/model", "a" * 40)
    weights = ModelFile("weights/model.safetensors", 20, "b" * 64)
    config = ModelFile("config.json", 10, "c" * 64)
    manifest = ModelManifest(reference, "comfyui", "license-1", (weights, config), 40)
    assert manifest.reference == reference
    assert manifest.files == (weights, config)
    assert manifest.estimated_bytes == 40


@pytest.mark.parametrize(
    "path",
    ["", "/weights", "../weights", "a/../b", "a//b", "a\\b", "C:weights", "a/"],
)
def test_manifest_file_rejects_unsafe_relative_names(path: str) -> None:
    with pytest.raises(ValueError):
        ModelFile(path, 1, "a" * 64)


@pytest.mark.parametrize(
    ("size", "digest"), [(-1, "a" * 64), (True, "a" * 64), (1, "a" * 63), (1, "A" * 64)]
)
def test_manifest_file_rejects_invalid_integrity_metadata(
    size: int, digest: str
) -> None:
    with pytest.raises(ValueError):
        ModelFile("model.safetensors", size, digest)


def test_manifest_rejects_duplicate_file_names_and_insufficient_estimate() -> None:
    ref = ModelReference("huggingface", "creator/model", "a" * 40)
    file = ModelFile("model.safetensors", 10, "b" * 64)
    duplicate = ModelFile("MODEL.safetensors", 1, "c" * 64)
    with pytest.raises(ValueError):
        ModelManifest(ref, "comfyui", "license-1", (file, duplicate), 20)
    with pytest.raises(ValueError):
        ModelManifest(ref, "comfyui", "license-1", (file,), 9)


def test_manifest_rejects_files_that_are_also_parent_directories() -> None:
    ref = ModelReference("huggingface", "creator/model", "a" * 40)
    parent = ModelFile("model", 1, "b" * 64)
    child = ModelFile("MODEL/weights", 1, "c" * 64)
    with pytest.raises(ValueError):
        ModelManifest(ref, "comfyui", "license-1", (parent, child), 2)


def test_manifest_requires_files_and_explicit_engine_and_license() -> None:
    ref = ModelReference("huggingface", "creator/model", "a" * 40)
    file = ModelFile("model.safetensors", 10, "b" * 64)
    for engine, license_id, files in [
        ("", "license-1", (file,)),
        ("comfyui", " ", (file,)),
        ("comfyui", "license-1", ()),
    ]:
        with pytest.raises(ValueError):
            ModelManifest(ref, engine, license_id, files, 10)


def test_manifest_catalog_resolves_only_full_pinned_reference() -> None:
    first = ModelReference("huggingface", "creator-a/model", "a" * 40)
    second = ModelReference("huggingface", "creator-b/model", "a" * 40)
    file = ModelFile("model.safetensors", 10, "b" * 64)
    manifest = ModelManifest(first, "comfyui", "license-1", (file,), 20)
    other = ModelManifest(second, "comfyui", "license-2", (file,), 30)
    untrusted = ModelManifest(first, "comfyui", "license-1", (file,), 10)
    catalog = ModelManifestCatalog((manifest, other))

    assert catalog.resolve(first) == manifest
    assert catalog.resolve(untrusted.reference) != untrusted
    assert catalog.resolve(second) == other
    assert catalog.resolve(ModelReference("huggingface", "creator-a/model", "c" * 40)) is None
    assert ModelManifestCatalog(()).resolve(first) is None


def test_manifest_catalog_rejects_duplicate_pins_and_untrusted_shapes() -> None:
    reference = ModelReference("huggingface", "creator/model", "a" * 40)
    file = ModelFile("model.safetensors", 10, "b" * 64)
    manifest = ModelManifest(reference, "comfyui", "license-1", (file,), 20)
    conflicting = ModelManifest(reference, "comfyui", "license-2", (file,), 20)
    for values in ((manifest, manifest), (manifest, conflicting)):
        with pytest.raises(ValueError):
            ModelManifestCatalog(values)
    for values in ([manifest], ("model",)):
        with pytest.raises(TypeError):
            ModelManifestCatalog(values)
    with pytest.raises(TypeError):
        ModelManifestCatalog(()).resolve("creator/model")


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


def test_reference_allowlist_requires_an_exact_pinned_reference() -> None:
    allowed = ModelReference("huggingface", "creator-a/model", "a" * 40)
    policy = ModelReferenceAllowlist(frozenset({allowed}))

    assert policy.allows(ModelReference("huggingface", "creator-a/model", "a" * 40))
    assert not policy.allows(ModelReference("huggingface", "creator-b/model", "a" * 40))
    assert not policy.allows(ModelReference("huggingface", "creator-a/model", "b" * 40))
    assert not policy.allows(ModelReference("huggingface", "Creator-a/model", "a" * 40))


def test_reference_allowlist_denies_empty_and_rejects_mutable_or_invalid_values() -> None:
    reference = ModelReference("huggingface", "creator/model", "a" * 40)
    assert not ModelReferenceAllowlist(frozenset()).allows(reference)
    for invalid in ({reference}, frozenset({"creator/model"})):
        with pytest.raises(TypeError):
            ModelReferenceAllowlist(invalid)
    with pytest.raises(TypeError):
        ModelReferenceAllowlist(frozenset()).allows("creator/model")


def test_manifest_preflight_requires_exact_pin_and_sufficient_manifest_estimate() -> None:
    ref = ModelReference("huggingface", "creator/model", "a" * 40)
    file = ModelFile("model.safetensors", 10, "b" * 64)
    manifest = ModelManifest(ref, "comfyui", "license-1", (file,), 20)
    allowed = ModelReferenceAllowlist(frozenset({ref}))
    assert check_manifest_acquisition(
        manifest=manifest, allowlist=allowed, license_accepted=True,
        access_confirmed=True, available_bytes=20,
    ) == ()
    assert check_manifest_acquisition(
        manifest=manifest, allowlist=allowed, license_accepted=True,
        access_confirmed=True, available_bytes=19,
    ) == (AcquisitionBlocker.INSUFFICIENT_STORAGE,)


def test_manifest_preflight_reports_all_independent_blockers() -> None:
    ref = ModelReference("huggingface", "creator/model", "a" * 40)
    manifest = ModelManifest(ref, "comfyui", "license-1", (ModelFile("model", 1, "b" * 64),), 2)
    policy = ModelReferenceAllowlist(frozenset({
        ModelReference("huggingface", "creator/model", "c" * 40),
    }))
    assert check_manifest_acquisition(
        manifest=manifest, allowlist=policy, license_accepted=False,
        access_confirmed=False, available_bytes=1,
    ) == (
        AcquisitionBlocker.REFERENCE_NOT_ALLOWED,
        AcquisitionBlocker.LICENSE_NOT_ACCEPTED,
        AcquisitionBlocker.ACCESS_NOT_CONFIRMED,
        AcquisitionBlocker.INSUFFICIENT_STORAGE,
    )


def test_manifest_preflight_rejects_untrusted_shapes_and_unknown_facts() -> None:
    ref = ModelReference("huggingface", "creator/model", "a" * 40)
    manifest = ModelManifest(ref, "comfyui", "license-1", (ModelFile("model", 1, "b" * 64),), 1)
    policy = ModelReferenceAllowlist(frozenset())
    for bad_manifest, bad_policy in ((None, policy), (manifest, {ref})):
        with pytest.raises(TypeError):
            check_manifest_acquisition(
                manifest=bad_manifest, allowlist=bad_policy, license_accepted=True,
                access_confirmed=True, available_bytes=1,
            )
    with pytest.raises(ValueError):
        check_manifest_acquisition(
            manifest=manifest, allowlist=policy, license_accepted=None,
            access_confirmed=True, available_bytes=1,
        )
    with pytest.raises(ValueError):
        check_manifest_acquisition(
            manifest=manifest, allowlist=policy, license_accepted=True,
            access_confirmed=True, available_bytes=None,
        )


def test_catalog_preflight_uses_stored_manifest_and_exact_pin() -> None:
    ref = ModelReference("huggingface", "creator/model", "a" * 40)
    manifest = ModelManifest(ref, "comfyui", "license-1", (ModelFile("model", 1, "b" * 64),), 20)
    catalog = ModelManifestCatalog((manifest,))
    policy = ModelReferenceAllowlist(frozenset({ref}))
    assert check_catalog_acquisition(
        reference=ref, catalog=catalog, allowlist=policy, license_accepted=True,
        access_confirmed=True, available_bytes=19,
    ) == (AcquisitionBlocker.INSUFFICIENT_STORAGE,)
    assert check_catalog_acquisition(
        reference=ref, catalog=catalog, allowlist=policy, license_accepted=True,
        access_confirmed=True, available_bytes=20,
    ) == ()
    assert check_catalog_acquisition(
        reference=ModelReference("huggingface", "creator/model", "c" * 40),
        catalog=catalog, allowlist=policy, license_accepted=True,
        access_confirmed=True, available_bytes=20,
    ) == (AcquisitionBlocker.MANIFEST_NOT_IN_CATALOG,)
    assert check_catalog_acquisition(
        reference=ModelReference("huggingface", "other/model", "a" * 40),
        catalog=catalog, allowlist=policy, license_accepted=False,
        access_confirmed=False, available_bytes=0,
    ) == (AcquisitionBlocker.MANIFEST_NOT_IN_CATALOG,)


def test_catalog_preflight_preserves_blockers_and_rejects_invalid_inputs() -> None:
    ref = ModelReference("huggingface", "creator/model", "a" * 40)
    manifest = ModelManifest(ref, "comfyui", "license-1", (ModelFile("model", 1, "b" * 64),), 2)
    catalog = ModelManifestCatalog((manifest,))
    policy = ModelReferenceAllowlist(frozenset())
    assert check_catalog_acquisition(
        reference=ref, catalog=catalog, allowlist=policy, license_accepted=False,
        access_confirmed=False, available_bytes=1,
    ) == (
        AcquisitionBlocker.REFERENCE_NOT_ALLOWED,
        AcquisitionBlocker.LICENSE_NOT_ACCEPTED,
        AcquisitionBlocker.ACCESS_NOT_CONFIRMED,
        AcquisitionBlocker.INSUFFICIENT_STORAGE,
    )
    for bad_ref, bad_catalog, bad_policy in (("model", catalog, policy), (ref, (), policy), (ref, catalog, set())):
        with pytest.raises(TypeError):
            check_catalog_acquisition(
                reference=bad_ref, catalog=bad_catalog, allowlist=bad_policy,
                license_accepted=True, access_confirmed=True, available_bytes=2,
            )
    for facts in ((None, True, 1), (True, None, 1), (True, True, None),
                  (True, True, -1), (True, True, True)):
        with pytest.raises(ValueError):
            check_catalog_acquisition(
                reference=ref, catalog=ModelManifestCatalog(()), allowlist=policy,
                license_accepted=facts[0], access_confirmed=facts[1], available_bytes=facts[2],
            )


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
