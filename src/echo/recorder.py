"""Microphone capture with spacebar stop.

Records from the default input device into an in-memory buffer until the user
presses space (or Ctrl-C). Writes the buffer to a WAV file at the requested path.
"""
from __future__ import annotations

import select
import sys
import termios
import time
import tty
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd
import soundfile as sf


class RecorderError(Exception):
    """Raised when audio capture fails."""


@dataclass
class RecordingResult:
    wav_path: Path
    duration_seconds: float


def record_until_space(
    *,
    output_path: Path,
    sample_rate: int,
    channels: int,
    on_tick: Callable[[int], None] | None = None,
    min_duration: float = 0.5,
) -> RecordingResult:
    """Record from the default mic until space is pressed.

    Calls `on_tick(elapsed_seconds)` once per second so the caller can
    update a status line. Raises RecorderError if the recording is shorter
    than `min_duration`.
    """
    chunks: list[np.ndarray] = []

    def callback(indata, frames, time_info, status):  # noqa: ARG001
        if status:
            # Drop input overflow warnings silently; non-fatal.
            pass
        chunks.append(indata.copy())

    try:
        stream = sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            callback=callback,
        )
    except Exception as e:
        raise RecorderError(
            f"Failed to open microphone: {e}. "
            "Grant Terminal mic access in System Settings → Privacy & Security → Microphone."
        ) from e

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    start = time.monotonic()
    last_tick = -1

    try:
        tty.setcbreak(fd)
        stream.start()
        while True:
            elapsed = int(time.monotonic() - start)
            if elapsed != last_tick and on_tick is not None:
                on_tick(elapsed)
                last_tick = elapsed

            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch = sys.stdin.read(1)
                if ch == " ":
                    break
    finally:
        try:
            stream.stop()
            stream.close()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    duration = time.monotonic() - start
    if duration < min_duration or not chunks:
        raise RecorderError(f"Recording too short ({duration:.2f}s); discarded")

    audio = np.concatenate(chunks, axis=0)
    sf.write(str(output_path), audio, sample_rate, subtype="PCM_16")
    return RecordingResult(wav_path=output_path, duration_seconds=duration)
