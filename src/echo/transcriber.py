"""OpenAI audio transcription wrapper."""
from __future__ import annotations

from pathlib import Path
from typing import Any


class TranscriberError(Exception):
    """Raised when transcription fails."""


def transcribe(
    *,
    client: Any,
    wav_path: Path,
    model: str,
    vocabulary_prompt: str,
    language: str,
) -> str:
    kwargs: dict[str, Any] = {
        "model": model,
        "prompt": vocabulary_prompt,
    }
    if language:
        kwargs["language"] = language

    try:
        with wav_path.open("rb") as f:
            kwargs["file"] = f
            response = client.audio.transcriptions.create(**kwargs)
    except Exception as e:
        raise TranscriberError(f"OpenAI transcription failed: {e}") from e

    return (response.text or "").strip()
