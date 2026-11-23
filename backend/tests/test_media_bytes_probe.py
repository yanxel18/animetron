import hashlib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.engines import media_bytes_probe
from app.engines.media_probe import InvalidMediaProbe, MediaProbe


@pytest.fixture
def inputs(tmp_path):
    return b"exact supplied media bytes", tmp_path / "ffprobe.exe", tmp_path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def test_exact_payload_result_and_private_stage_cleanup(inputs, monkeypatch):
    raw, executable, root = inputs
    paths = []
    facts = MediaProbe(1080, 1920, 45000, True)

    def probe(path, tool, *, timeout_seconds):
        paths.append(path)
        assert path.name == "media.bin"
        assert path.parent.parent == root.resolve()
        assert path.read_bytes() == raw
        assert tool == executable
        assert timeout_seconds == 3
        return facts

    monkeypatch.setattr(media_bytes_probe, "probe_local_media", probe)
    results = [media_bytes_probe.probe_media_bytes(
        raw, digest(raw), executable, root, max_bytes=len(raw), timeout_seconds=3,
    ) for _ in range(2)]
    assert paths[0].parent != paths[1].parent
    assert not any(path.parent.exists() for path in paths)
    assert list(root.iterdir()) == []
    for result in results:
        assert result.probe is facts
        assert result.sha256 == digest(raw)
        assert result.size_bytes == len(raw)
        with pytest.raises(FrozenInstanceError):
            result.size_bytes = 1


@pytest.mark.parametrize("raw", [b"", "bytes", bytearray(b"x"), None])
def test_invalid_payload_rejected_before_staging(inputs, monkeypatch, raw):
    _, executable, root = inputs
    monkeypatch.setattr(media_bytes_probe, "TemporaryDirectory", lambda **kw: pytest.fail("staged"))
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        media_bytes_probe.probe_media_bytes(raw, "0" * 64, executable, root)


@pytest.mark.parametrize("expected", ["0" * 64, "A" * 64, "a" * 63, "a" * 65, None, 123])
def test_digest_mismatch_or_bad_shape_rejected_before_staging(inputs, monkeypatch, expected):
    raw, executable, root = inputs
    monkeypatch.setattr(media_bytes_probe, "TemporaryDirectory", lambda **kw: pytest.fail("staged"))
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        media_bytes_probe.probe_media_bytes(raw, expected, executable, root)


@pytest.mark.parametrize("limit", [True, 0, -1, 64 * 1024 * 1024 + 1, 1.0, "64", None, 1])
def test_invalid_or_exceeded_size_limit_rejected_before_staging(inputs, monkeypatch, limit):
    raw, executable, root = inputs
    monkeypatch.setattr(media_bytes_probe, "TemporaryDirectory", lambda **kw: pytest.fail("staged"))
    with pytest.raises(InvalidMediaProbe):
        media_bytes_probe.probe_media_bytes(raw, digest(raw), executable, root, max_bytes=limit)


@pytest.mark.parametrize("timeout", [True, 0, -1, 31, float("inf"), float("nan"), "1", 10**1000])
def test_timeout_rejected_before_staging(inputs, monkeypatch, timeout):
    raw, executable, root = inputs
    monkeypatch.setattr(media_bytes_probe, "TemporaryDirectory", lambda **kw: pytest.fail("staged"))
    with pytest.raises(InvalidMediaProbe):
        media_bytes_probe.probe_media_bytes(raw, digest(raw), executable, root, timeout_seconds=timeout)


@pytest.mark.parametrize("mutation", [b"changed", b"x" * 100, b"", "same-size"])
def test_staged_payload_mutation_is_rejected_and_cleaned(inputs, monkeypatch, mutation):
    raw, executable, root = inputs

    def probe(path, *args, **kwargs):
        path.write_bytes(b"x" * len(raw) if mutation == "same-size" else mutation)
        return MediaProbe(1080, 1920, 45000, True)

    monkeypatch.setattr(media_bytes_probe, "probe_local_media", probe)
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        media_bytes_probe.probe_media_bytes(raw, digest(raw), executable, root, max_bytes=len(raw))
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("error", [OSError, RuntimeError, InvalidMediaProbe])
def test_probe_failure_is_generic_and_stage_is_removed(inputs, monkeypatch, error):
    raw, executable, root = inputs

    def fail(*args, **kwargs):
        raise error("private paths and metadata")

    monkeypatch.setattr(media_bytes_probe, "probe_local_media", fail)
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        media_bytes_probe.probe_media_bytes(raw, digest(raw), executable, root)
    assert list(root.iterdir()) == []


def test_partial_write_fails_before_probing_and_cleans_stage(inputs, monkeypatch):
    raw, executable, root = inputs
    monkeypatch.setattr(Path, "write_bytes", lambda *args: 1)
    monkeypatch.setattr(media_bytes_probe, "probe_local_media", lambda *a, **kw: pytest.fail("probed"))
    with pytest.raises(InvalidMediaProbe):
        media_bytes_probe.probe_media_bytes(raw, digest(raw), executable, root)
    assert list(root.iterdir()) == []


def test_invalid_root_is_generic(inputs):
    raw, executable, root = inputs
    for invalid in [root / "missing", Path(__file__)]:
        with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
            media_bytes_probe.probe_media_bytes(raw, digest(raw), executable, invalid)


def test_cleanup_failure_cannot_return_success(inputs, monkeypatch):
    raw, executable, root = inputs
    original = media_bytes_probe.TemporaryDirectory

    class FailingCleanup(original):
        def __exit__(self, *args):
            super().__exit__(*args)
            raise OSError("private cleanup path")

    monkeypatch.setattr(media_bytes_probe, "TemporaryDirectory", FailingCleanup)
    monkeypatch.setattr(media_bytes_probe, "probe_local_media", lambda *a, **kw:
                        MediaProbe(1080, 1920, 45000, True))
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        media_bytes_probe.probe_media_bytes(raw, digest(raw), executable, root)
    assert list(root.iterdir()) == []


def test_write_failure_removes_private_stage(inputs, monkeypatch):
    raw, executable, root = inputs

    def fail(*args):
        raise OSError("private write path")

    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        media_bytes_probe.probe_media_bytes(raw, digest(raw), executable, root)
    assert list(root.iterdir()) == []
