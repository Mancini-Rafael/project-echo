"""Microphone capture as a thread-friendly session.

`RecordingSession` opens an input stream on `start()`, captures into an
in-memory buffer, and writes a 16-bit PCM WAV on `stop()`. It can be driven
from any thread; start/stop are independent of stdin or terminal state.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


class RecorderError(Exception):
    """Raised when audio capture fails."""


@dataclass
class RecordingResult:
    wav_path: Path
    duration_seconds: float


class RecordingSession:
    """Captures audio from the default mic into an in-memory buffer.

    Lifecycle: construct → start() → (later, possibly from another thread) stop().
    A single instance is single-use; create a new one for each recording.
    """

    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        min_duration: float = 0.5,
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._min_duration = min_duration
        self._chunks: list[np.ndarray] = []
        self._chunks_lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._start_time: float | None = None
        self._stopped = False

    @property
    def is_recording(self) -> bool:
        return self._stream is not None and not self._stopped

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        # Drop sounddevice status flags silently; they are non-fatal warnings.
        with self._chunks_lock:
            self._chunks.append(indata.copy())

    def start(self) -> None:
        if self._stream is not None:
            raise RecorderError("RecordingSession already started")
        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="int16",
                callback=self._callback,
            )
            self._stream.start()
        except Exception as e:
            self._stream = None
            raise RecorderError(
                f"Failed to open microphone: {e}. "
                "Grant Terminal mic access in System Settings → Privacy & Security → Microphone."
            ) from e
        self._start_time = time.monotonic()

    def stop(self, output_path: Path) -> RecordingResult:
        if self._stream is None or self._start_time is None:
            raise RecorderError("RecordingSession was never started")
        if self._stopped:
            raise RecorderError("RecordingSession already stopped")
        self._stopped = True

        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None

        duration = time.monotonic() - self._start_time

        with self._chunks_lock:
            if not self._chunks or duration < self._min_duration:
                raise RecorderError(
                    f"Recording too short ({duration:.2f}s); discarded"
                )
            audio = np.concatenate(self._chunks, axis=0)

        sf.write(str(output_path), audio, self._sample_rate, subtype="PCM_16")
        return RecordingResult(wav_path=output_path, duration_seconds=duration)
