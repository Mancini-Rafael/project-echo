"""Audio extraction from video files via FFmpeg."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

Runner = Callable[..., subprocess.CompletedProcess[str]]

# 16 kHz mono 16-bit PCM is whisper.cpp's native input, so no resampling
# happens inside the model and timestamps line up with the source.
_SAMPLE_RATE = "16000"
_NO_AUDIO_MARKER = "matches no streams"


class MediaError(Exception):
    """Raised when audio can't be extracted from a media file."""


def extract_audio(
    video_path: Path,
    wav_path: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    run: Runner = subprocess.run,
) -> None:
    """Write the first audio stream of `video_path` to `wav_path` as 16 kHz mono WAV."""
    if not video_path.is_file():
        raise MediaError(f"input file not found: {video_path}")

    argv = [
        ffmpeg_binary,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        _SAMPLE_RATE,
        "-c:a",
        "pcm_s16le",
        str(wav_path),
    ]
    try:
        completed = run(argv, check=False, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise MediaError(
            f"{ffmpeg_binary} not found. Install it with `brew install ffmpeg`."
        ) from e

    if completed.returncode == 0:
        return
    stderr = (completed.stderr or "").strip()
    if _NO_AUDIO_MARKER in stderr:
        raise MediaError(f"no audio stream in {video_path.name}")
    raise MediaError(f"ffmpeg failed (exit {completed.returncode}): {stderr}")
