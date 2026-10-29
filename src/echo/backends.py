"""Transcription backends for dictation (`ec`, `ec listen`).

Both backends share the call signature of `echo.transcriber.transcribe`, so the
one-shot flow and the daemon use either one without knowing which: a Strategy
chosen by `--backend`. OpenAI is the default; local runs whisper.cpp on this
machine (no API key, no upload, slower per press because the model loads each
time).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from echo.config import LocalWhisperConfig
from echo.transcriber import TranscriberError
from echo.whisper_cpp import WhisperCppError, transcribe_with_timestamps

Backend = Literal["openai", "local"]
BACKENDS: tuple[Backend, ...] = ("openai", "local")

TranscribeFn = Callable[..., str]


def local_transcribe_fn(local: LocalWhisperConfig) -> TranscribeFn:
    """Build a `transcribe`-compatible function backed by local whisper.cpp."""

    def transcribe_local(
        *,
        client: Any,
        wav_path: Path,
        model: str,
        vocabulary_prompt: str,
        language: str,
    ) -> str:
        # `client` and `model` belong to the OpenAI backend; the local model is
        # set by local_whisper.model_path instead.
        del client, model
        try:
            transcript = transcribe_with_timestamps(
                wav_path=wav_path,
                config=local,
                language=language,
                vocabulary_prompt=vocabulary_prompt,
                source=wav_path.name,
            )
        except WhisperCppError as e:
            raise TranscriberError(f"local transcription failed: {e}") from e
        return " ".join(s.text for s in transcript.segments).strip()

    return transcribe_local
