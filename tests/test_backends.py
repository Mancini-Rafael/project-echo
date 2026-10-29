from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echo.backends import local_transcribe_fn
from echo.config import LocalWhisperConfig
from echo.timed_transcript import Segment, TimedTranscript
from echo.transcriber import TranscriberError
from echo.whisper_cpp import WhisperCppError


def _local() -> LocalWhisperConfig:
    return LocalWhisperConfig(
        binary="whisper-cli", model_path=Path("/models/ggml-base.bin"), language="auto"
    )


def _transcript(*texts: str) -> TimedTranscript:
    segments = tuple(
        Segment(start=float(i), end=float(i + 1), text=t, words=()) for i, t in enumerate(texts)
    )
    return TimedTranscript(source="clip.wav", language="en", model="m", segments=segments)


def _call(fn, wav: Path, **overrides):
    kwargs = {
        "client": None,
        "wav_path": wav,
        "model": "gpt-4o-transcribe",
        "vocabulary_prompt": "Rails",
        "language": "en",
    }
    kwargs.update(overrides)
    return fn(**kwargs)


def test_local_fn_joins_segment_text(mocker, tmp_path: Path) -> None:
    run = mocker.patch(
        "echo.backends.transcribe_with_timestamps",
        return_value=_transcript("Hello there.", "Second part."),
    )

    text = _call(local_transcribe_fn(_local()), tmp_path / "a.wav")

    assert text == "Hello there. Second part."
    kwargs = run.call_args.kwargs
    assert kwargs["wav_path"] == tmp_path / "a.wav"
    assert kwargs["config"] == _local()
    assert kwargs["language"] == "en"
    assert kwargs["vocabulary_prompt"] == "Rails"


def test_local_fn_passes_empty_vocabulary_through(mocker, tmp_path: Path) -> None:
    run = mocker.patch("echo.backends.transcribe_with_timestamps", return_value=_transcript("ok"))

    _call(local_transcribe_fn(_local()), tmp_path / "a.wav", vocabulary_prompt="")

    assert run.call_args.kwargs["vocabulary_prompt"] == ""


def test_local_fn_returns_empty_string_for_silence(mocker, tmp_path: Path) -> None:
    mocker.patch("echo.backends.transcribe_with_timestamps", return_value=_transcript())

    assert _call(local_transcribe_fn(_local()), tmp_path / "a.wav") == ""


def test_local_fn_ignores_openai_client(mocker, tmp_path: Path) -> None:
    mocker.patch("echo.backends.transcribe_with_timestamps", return_value=_transcript("x"))
    client = MagicMock()

    _call(local_transcribe_fn(_local()), tmp_path / "a.wav", client=client)

    assert client.mock_calls == []


def test_local_fn_maps_whisper_errors_to_transcriber_error(mocker, tmp_path: Path) -> None:
    mocker.patch(
        "echo.backends.transcribe_with_timestamps", side_effect=WhisperCppError("decoder died")
    )

    with pytest.raises(TranscriberError, match="local transcription failed: decoder died"):
        _call(local_transcribe_fn(_local()), tmp_path / "a.wav")
