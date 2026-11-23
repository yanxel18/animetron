"""Check supplied media facts; no decoding or media probing is performed here."""

from dataclasses import dataclass


class InvalidMediaProbe(ValueError):
    """The supplied facts do not meet the hard output requirements."""


@dataclass(frozen=True)
class MediaProbe:
    """Trusted facts: final display dimensions, measured duration, audio track.

    Callers must account for rotation and sample aspect ratio in dimensions,
    and must not round duration down to fit the millisecond hard limit.
    An audio-track flag does not establish that the audio decodes or is audible.
    """

    width: int
    height: int
    duration_ms: int
    has_audio: bool


@dataclass(frozen=True)
class MediaProbeValidation:
    """Hard requirements passed; the duration target is reported separately."""

    meets_duration_target: bool


def validate_media_probe(probe: MediaProbe) -> MediaProbeValidation:
    """Require portrait 9:16, an audio track and at most 90 seconds.

    This checks facts only. It cannot establish decodability, provenance,
    visual quality or real output acceptance.
    """
    if type(probe) is not MediaProbe:
        raise InvalidMediaProbe("Invalid media probe")
    if (
        type(probe.width) is not int
        or type(probe.height) is not int
        or type(probe.duration_ms) is not int
        or probe.width <= 0
        or probe.height <= 0
        or probe.width * 16 != probe.height * 9
        or not 0 < probe.duration_ms <= 90_000
        or type(probe.has_audio) is not bool
        or not probe.has_audio
    ):
        raise InvalidMediaProbe("Invalid media probe")
    return MediaProbeValidation(30_000 <= probe.duration_ms <= 60_000)
