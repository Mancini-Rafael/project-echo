from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echo.transcriber import TranscriberError, transcribe


def test_transcribe_calls_openai_with_correct_args(mocker, tmp_path: Path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFFfakecontent")

    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = MagicMock(text="hello world")

    text = transcribe(
        client=fake_client,
        wav_path=wav,
        model="gpt-4o-transcribe",
        vocabulary_prompt="TypeScript Postgres",
        language="en",
    )

    assert text == "hello world"
    call = fake_client.audio.transcriptions.create.call_args
    assert call.kwargs["model"] == "gpt-4o-transcribe"
    assert call.kwargs["prompt"] == "TypeScript Postgres"
    assert call.kwargs["language"] == "en"
    assert call.kwargs["file"] is not None


def test_transcribe_omits_language_when_blank(mocker, tmp_path: Path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFFfakecontent")

    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = MagicMock(text="x")

    transcribe(
        client=fake_client,
        wav_path=wav,
        model="gpt-4o-transcribe",
        vocabulary_prompt="",
        language="",
    )

    kwargs = fake_client.audio.transcriptions.create.call_args.kwargs
    assert "language" not in kwargs


def test_transcribe_strips_whitespace(tmp_path: Path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = MagicMock(text="  hi  \n")
    assert transcribe(
        client=fake_client, wav_path=wav, model="m", vocabulary_prompt="", language=""
    ) == "hi"


def test_transcribe_raises_on_api_error(tmp_path: Path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.side_effect = RuntimeError("network down")
    with pytest.raises(TranscriberError, match="network down"):
        transcribe(
            client=fake_client, wav_path=wav, model="m", vocabulary_prompt="", language=""
        )
