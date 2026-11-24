import io
import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.artifact_bytes import ArtifactByteStore, ByteIntegrityError, StoredBytes
from app.engines.media_bytes_probe import VerifiedMediaProbe
from app.engines.media_probe import InvalidMediaProbe, MediaProbe
from app.services.artifact_media_probe import probe_stored_media


class Store:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def read_verified(self, expected, *, max_bytes):
        self.calls.append((expected, max_bytes))
        if self.error:
            raise self.error
        return b"content"


@pytest.fixture
def facts():
    return StoredBytes(uuid4(), "a" * 64, 7)


def test_verified_bytes_and_identity_reach_probe(facts, monkeypatch):
    store = Store()
    result = VerifiedMediaProbe(MediaProbe(9, 16, 30000, True), facts.sha256, 7)
    seen = []
    def probe(raw, digest, executable, root, **kwargs):
        seen.append((raw, digest, executable, root, kwargs))
        return result
    monkeypatch.setattr("app.services.artifact_media_probe.probe_media_bytes", probe)
    assert probe_stored_media(store, facts, Path("tool"), Path("stage"), max_bytes=7, timeout_seconds=3) == result
    assert store.calls == [(facts, 7)]
    assert seen == [(b"content", facts.sha256, Path("tool"), Path("stage"), {"max_bytes": 7, "timeout_seconds": 3})]


@pytest.mark.parametrize("error", [FileNotFoundError("secret"), ByteIntegrityError("secret"), OSError("secret")])
def test_store_failure_fails_closed_without_probe(facts, monkeypatch, error):
    monkeypatch.setattr("app.services.artifact_media_probe.probe_media_bytes", lambda *a, **kw: pytest.fail("probe called"))
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        probe_stored_media(Store(error), facts, Path("tool"), Path("stage"))


@pytest.mark.parametrize("limit", [0, -1, True, 67108865, 6, "7"])
def test_invalid_or_too_small_limit_fails_before_read(facts, monkeypatch, limit):
    store = Store()
    monkeypatch.setattr("app.services.artifact_media_probe.probe_media_bytes", lambda *a, **kw: pytest.fail("probe called"))
    with pytest.raises(InvalidMediaProbe):
        probe_stored_media(store, facts, Path("tool"), Path("stage"), max_bytes=limit)
    assert store.calls == []


@pytest.mark.parametrize("timeout", [0, True, 31, float("nan"), float("inf"), "10", 10**1000])
def test_invalid_timeout_fails_before_read(facts, timeout):
    store = Store()
    with pytest.raises(InvalidMediaProbe):
        probe_stored_media(store, facts, Path("tool"), Path("stage"), timeout_seconds=timeout)
    assert store.calls == []


@pytest.mark.skipif(sys.platform != "linux" or not os.environ.get("ARTIFACT_TEST_ROOT"),
                    reason="requires owned Linux artifact volume")
def test_real_store_rejects_tampering_before_probe(monkeypatch):
    with tempfile.TemporaryDirectory(dir=os.environ["ARTIFACT_TEST_ROOT"]) as root:
        Path(root).chmod(0o700)
        with ArtifactByteStore(root) as store:
            facts = store.put(uuid4(), io.BytesIO(b"content"), max_bytes=7)
            seen = []
            def probe(raw, digest, *args, **kwargs):
                seen.append((raw, digest))
                return VerifiedMediaProbe(MediaProbe(9, 16, 30000, True), digest, len(raw))
            monkeypatch.setattr("app.services.artifact_media_probe.probe_media_bytes", probe)
            probe_stored_media(store, facts, Path("tool"), Path("stage"), max_bytes=7)
            assert seen == [(b"content", facts.sha256)]
            (Path(root) / facts.storage_locator).write_bytes(b"changed")
            with pytest.raises(InvalidMediaProbe):
                probe_stored_media(store, facts, Path("tool"), Path("stage"), max_bytes=7)
            assert len(seen) == 1
