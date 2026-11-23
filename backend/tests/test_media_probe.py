from dataclasses import FrozenInstanceError, replace

import pytest

from app.engines.media_probe import (
    InvalidMediaProbe,
    MediaProbe,
    MediaProbeValidation,
    validate_media_probe,
)


@pytest.fixture
def probe():
    return MediaProbe(width=1080, height=1920, duration_ms=45000, has_audio=True)


@pytest.mark.parametrize(
    ("duration_ms", "meets_target"),
    [(1, False), (29999, False), (30000, True), (60000, True),
     (60001, False), (90000, False)],
)
def test_duration_target_is_inclusive_without_rejecting_other_valid_budgets(
    probe, duration_ms, meets_target,
):
    result = validate_media_probe(replace(probe, duration_ms=duration_ms))
    assert isinstance(result, MediaProbeValidation)
    assert result.meets_duration_target is meets_target


@pytest.mark.parametrize(("width", "height"), [(9, 16), (720, 1280), (1080, 1920)])
def test_exact_portrait_ratio_is_independent_of_resolution(probe, width, height):
    assert validate_media_probe(replace(probe, width=width, height=height)).meets_duration_target


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("duration_ms", 0), ("duration_ms", -1), ("duration_ms", 90001),
        ("duration_ms", True), ("duration_ms", 45000.0),
        ("duration_ms", float("nan")), ("duration_ms", float("inf")),
        ("duration_ms", "45000"), ("duration_ms", None),
        ("width", 0), ("width", -1080), ("width", True),
        ("width", 1080.0), ("width", float("nan")),
        ("width", float("inf")), ("width", "1080"), ("width", None),
        ("height", 0), ("height", -1920), ("height", True),
        ("height", 1920.0), ("height", "1920"), ("height", None),
        ("has_audio", False), ("has_audio", 1), ("has_audio", 0),
        ("has_audio", "true"), ("has_audio", None),
    ],
)
def test_invalid_facts_fail_without_coercion(probe, field, value):
    with pytest.raises(InvalidMediaProbe):
        validate_media_probe(replace(probe, **{field: value}))


@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1080, 1919), (1081, 1920)])
def test_landscape_and_near_portrait_ratios_are_rejected(probe, width, height):
    with pytest.raises(InvalidMediaProbe):
        validate_media_probe(replace(probe, width=width, height=height))


def test_invalid_fact_error_does_not_include_supplied_data(probe):
    private_value = "private-probe-metadata"
    with pytest.raises(InvalidMediaProbe) as caught:
        validate_media_probe(replace(probe, width=private_value))
    assert private_value not in str(caught.value)
    assert str(caught.value)


@pytest.mark.parametrize("value", [None, {}, True])
def test_untyped_probe_is_rejected(value):
    with pytest.raises(InvalidMediaProbe, match="Invalid media probe"):
        validate_media_probe(value)


def test_probe_and_validation_result_are_immutable(probe):
    with pytest.raises(FrozenInstanceError):
        probe.width = 720
    result = validate_media_probe(probe)
    with pytest.raises(FrozenInstanceError):
        result.meets_duration_target = False
