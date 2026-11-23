import json
import subprocess
import sys
import time

import pytest

from app.engines import local_media_probe
from app.engines.media_probe import InvalidMediaProbe, MediaProbe


@pytest.fixture
def paths(tmp_path):
    media = tmp_path / "clip with spaces.mp4"
    executable = tmp_path / "ffprobe.exe"
    media.write_bytes(b"fixture")
    executable.write_bytes(b"fixture")
    return media, executable


def report():
    return {"format": {"duration": "45", "start_time": "0"}, "streams": [
        {"index": 0, "codec_type": "video", "width": 1080, "height": 1920,
         "duration": "45", "start_time": "0", "sample_aspect_ratio": "1:1",
         "disposition": {"attached_pic": 0}},
        {"index": 1, "codec_type": "audio", "duration": "45", "start_time": "0"},
    ]}


def launch(monkeypatch, script):
    original = subprocess.Popen
    children = []
    commands = []

    def start(command, **kwargs):
        commands.append((command, kwargs))
        child = original([sys.executable, "-c", script], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(local_media_probe.subprocess, "Popen", start)
    return children, commands


def test_probe_parses_child_output_and_uses_fixed_local_argv(paths, monkeypatch):
    payload = json.dumps(report())
    children, commands = launch(monkeypatch, f"print({payload!r})")
    media, executable = paths
    assert local_media_probe.probe_local_media(media, executable) == MediaProbe(
        1080, 1920, 45000, True,
    )
    command, kwargs = commands[0]
    assert command == [str(executable.resolve()), "-v", "error", "-protocol_whitelist",
                       "file", "-show_streams", "-show_format", "-of", "json",
                       "-i", str(media.resolve())]
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert not kwargs.get("shell", False)
    assert children[0].poll() == 0


@pytest.mark.parametrize("script", [
    "import sys;sys.stdout.buffer.write(b'x'*65537);sys.stdout.flush();__import__('time').sleep(10)",
    "import sys;sys.stderr.buffer.write(b'x'*8193);sys.stderr.flush();__import__('time').sleep(10)",
    "import time;time.sleep(10)",
    "import sys;print('private-error',file=sys.stderr);sys.exit(3)",
    "print('malformed-private-json')",
])
def test_child_failures_are_generic_and_reaped(paths, monkeypatch, script):
    children, _ = launch(monkeypatch, script)
    started = time.monotonic()
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        local_media_probe.probe_local_media(
            *paths, timeout_seconds=10 if "buffer.write" in script else 0.5,
        )
    assert time.monotonic() - started < 4
    assert children[0].poll() is not None
    assert children[0].stdout.closed
    assert children[0].stderr.closed


@pytest.mark.parametrize("timeout", [True, 0, -1, 31, float("nan"), float("inf"), "10",
                                    pytest.param(10**10000, id="huge-integer")])
def test_invalid_timeout_does_not_start_process(paths, monkeypatch, timeout):
    def forbidden(*args, **kwargs):
        pytest.fail("process started")
    monkeypatch.setattr(local_media_probe.subprocess, "Popen", forbidden)
    with pytest.raises(InvalidMediaProbe):
        local_media_probe.probe_local_media(*paths, timeout_seconds=timeout)


def test_missing_path_and_spawn_failure_are_generic(paths, monkeypatch):
    with pytest.raises(InvalidMediaProbe):
        local_media_probe.probe_local_media(paths[0].parent, paths[1])
    def fail(*args, **kwargs):
        raise OSError("private executable path")
    monkeypatch.setattr(local_media_probe.subprocess, "Popen", fail)
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        local_media_probe.probe_local_media(*paths)


@pytest.mark.parametrize("suffix", [".bat", ".CMD"])
def test_shell_scripts_are_rejected_before_spawn(paths, suffix, monkeypatch):
    script = paths[1].with_suffix(suffix)
    script.write_text("echo ignored")
    def forbidden(*args, **kwargs):
        pytest.fail("process started")
    monkeypatch.setattr(local_media_probe.subprocess, "Popen", forbidden)
    with pytest.raises(InvalidMediaProbe):
        local_media_probe.probe_local_media(paths[0], script)


@pytest.mark.parametrize("failure_number", [1, 2])
def test_reader_start_failure_kills_and_reaps_child(paths, monkeypatch, failure_number):
    children, _ = launch(monkeypatch, "import time;time.sleep(10)")
    original = local_media_probe.threading.Thread.start
    calls = []
    def start(reader):
        calls.append(reader)
        if len(calls) == failure_number:
            raise RuntimeError("private-thread-error")
        original(reader)
    monkeypatch.setattr(local_media_probe.threading.Thread, "start", start)
    started = time.monotonic()
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        local_media_probe.probe_local_media(*paths)
    assert time.monotonic() - started < 4
    assert children[0].poll() is not None
    assert children[0].stdout.closed and children[0].stderr.closed
    assert not any(reader.is_alive() for reader in calls)


def test_cleanup_wait_error_is_generic_without_unbounded_retry(paths, monkeypatch):
    original_popen = subprocess.Popen
    children = []
    calls = []
    def spawn(command, **kwargs):
        child = original_popen([sys.executable, "-c", "import time;time.sleep(10)"], **kwargs)
        original_wait = child.wait
        def wait(timeout=None):
            calls.append(timeout)
            original_wait(timeout=timeout)
            raise subprocess.TimeoutExpired("private-command", timeout)
        monkeypatch.setattr(child, "wait", wait)
        children.append(child)
        return child
    monkeypatch.setattr(local_media_probe.subprocess, "Popen", spawn)
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        local_media_probe.probe_local_media(*paths, timeout_seconds=0.1)
    assert calls == [1]
    assert children[0].poll() is not None
    assert children[0].stdout.closed and children[0].stderr.closed


@pytest.mark.parametrize("component", ["Event", "Thread"])
def test_postspawn_setup_failure_still_reaps_child(paths, monkeypatch, component):
    children, _ = launch(monkeypatch, "import time;time.sleep(10)")

    def fail(*args, **kwargs):
        raise RuntimeError("private setup failure")

    monkeypatch.setattr(local_media_probe.threading, component, fail)
    try:
        with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
            local_media_probe.probe_local_media(*paths)
        assert children[0].poll() is not None
        assert children[0].stdout.closed and children[0].stderr.closed
    finally:
        # The regression's failing stage must not leave its sleeping child alive.
        if children[0].poll() is None:
            children[0].kill()
        children[0].wait(timeout=2)
        children[0].stdout.close()
        children[0].stderr.close()


def test_kill_error_does_not_skip_wait_and_pipe_cleanup(paths, monkeypatch):
    original_popen = subprocess.Popen
    children, waits = [], []

    def spawn(command, **kwargs):
        child = original_popen([sys.executable, "-c", "import time;time.sleep(10)"], **kwargs)
        kill, wait = child.kill, child.wait

        def kill_then_error():
            kill()
            raise OSError("private kill error")

        def bounded_wait(timeout=None):
            waits.append(timeout)
            return wait(timeout=timeout)

        monkeypatch.setattr(child, "kill", kill_then_error)
        monkeypatch.setattr(child, "wait", bounded_wait)
        children.append(child)
        return child

    monkeypatch.setattr(local_media_probe.subprocess, "Popen", spawn)
    with pytest.raises(InvalidMediaProbe, match="^Invalid media probe$"):
        local_media_probe.probe_local_media(*paths, timeout_seconds=0.1)
    assert waits == [1]
    assert children[0].poll() is not None
    assert children[0].stdout.closed and children[0].stderr.closed
