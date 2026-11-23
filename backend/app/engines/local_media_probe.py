"""Bounded FFprobe invocation for trusted server-owned local paths.

The executable and media must be controlled by the server. The executable must
not spawn descendants holding its pipes; this is not a sandbox or a provenance
check. Metadata inspection does not establish media decodability or audible audio.
"""

import math
import subprocess
import threading
import time
from pathlib import Path
from typing import IO, BinaryIO

from app.engines.ffprobe_metadata import parse_ffprobe_metadata
from app.engines.media_probe import InvalidMediaProbe, MediaProbe


def probe_local_media(
    media_path: Path, ffprobe_path: Path, *, timeout_seconds: float = 10,
) -> MediaProbe:
    """Read bounded metadata; timeout starts after OS process creation returns."""
    try:
        if (type(timeout_seconds) not in (int, float)
                or not 0 < timeout_seconds <= 30 or not math.isfinite(timeout_seconds)):
            raise ValueError("invalid timeout")
        media, executable = media_path.resolve(strict=True), ffprobe_path.resolve(strict=True)
        if (not media.is_file() or not executable.is_file()
                or executable.suffix.lower() in {".bat", ".cmd"}):
            raise ValueError("invalid local paths")
        command = [str(executable), "-v", "error", "-protocol_whitelist", "file",
                   "-show_streams", "-show_format", "-of", "json", "-i", str(media)]
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        started: list[threading.Thread] = []
        owned_pipes: set[IO[bytes]] = set()
        try:
            assert process.stdout is not None and process.stderr is not None
            failed = threading.Event()
            output: list[bytes] = [b"", b""]

            def read(pipe: BinaryIO, index: int, limit: int) -> None:
                try:
                    data = pipe.read(limit + 1)
                    if len(data) > limit:
                        failed.set()
                    else:
                        output[index] = data
                except OSError:
                    failed.set()
                finally:
                    pipe.close()

            readers = [
                threading.Thread(target=read, args=(process.stdout, 0, 65536), daemon=True),
                threading.Thread(target=read, args=(process.stderr, 1, 8192), daemon=True),
            ]
            for reader in readers:
                reader.start()
                started.append(reader)
                owned_pipes.add(process.stdout if len(started) == 1 else process.stderr)
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                if failed.is_set() or time.monotonic() >= deadline:
                    raise ValueError("probe failed")
                failed.wait(min(0.02, max(0, deadline - time.monotonic())))
            for reader in readers:
                reader.join(timeout=1)
            if failed.is_set() or any(reader.is_alive() for reader in readers):
                raise ValueError("probe failed")
            if process.returncode != 0:
                raise ValueError("probe failed")
            return parse_ffprobe_metadata(output[0])
        finally:
            try:
                if process.poll() is None:
                    process.kill()
            finally:
                try:
                    process.wait(timeout=1)
                finally:
                    for reader in started:
                        reader.join(timeout=1)
                    for pipe in (process.stdout, process.stderr):
                        if pipe is not None and pipe not in owned_pipes:
                            pipe.close()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        raise InvalidMediaProbe("Invalid media probe") from None
