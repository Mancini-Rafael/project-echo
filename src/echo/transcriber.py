"""OpenAI audio transcription wrapper."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class TranscriberError(Exception):
    """Raised when transcription fails."""


def _normalize(text: str) -> str:
    """Lowercase and collapse all whitespace to single spaces."""
    return re.sub(r"\s+", " ", text).strip().lower()


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

    result = (response.text or "").strip()

    # Whisper-family models echo back the vocabulary prompt verbatim when there
    # is no actual speech to transcribe. Treat that as empty so the caller
    # doesn't paste the vocabulary list into the user's clipboard.
    if vocabulary_prompt and _normalize(result) == _normalize(vocabulary_prompt):
        return ""

    return result
