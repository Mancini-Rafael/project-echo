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
    assert call.kwargs["language"] == "en"
    assert call.kwargs["file"] is not None
    # The vocabulary still reaches the model, now as a labelled reference
    # rather than as the whole prompt.
    assert "TypeScript Postgres" in call.kwargs["prompt"]


def _sent_prompt(fake_client) -> str:
    return fake_client.audio.transcriptions.create.call_args.kwargs["prompt"]


def _transcribe_with(fake_client, tmp_path: Path, **overrides) -> str:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")
    kwargs = {
        "client": fake_client,
        "wav_path": wav,
        "model": "gpt-4o-transcribe",
        "vocabulary_prompt": "",
        "language": "",
    }
    kwargs.update(overrides)
    return transcribe(**kwargs)


def test_prompt_instructs_verbatim_transcription(tmp_path: Path) -> None:
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = MagicMock(text="x")
    _transcribe_with(fake_client, tmp_path, vocabulary_prompt="Postgres", language="en")

    prompt = _sent_prompt(fake_client).lower()
    assert "verbatim" in prompt
    assert "never answer questions" in prompt


def test_prompt_names_the_target_language(tmp_path: Path) -> None:
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = MagicMock(text="x")
    _transcribe_with(fake_client, tmp_path, language="en")

    prompt = _sent_prompt(fake_client)
    assert "English" in prompt
    assert "never translate" in prompt.lower()


def test_prompt_omits_language_clause_for_unknown_code(tmp_path: Path) -> None:
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = MagicMock(text="x")
    _transcribe_with(fake_client, tmp_path, language="zz")

    assert "never translate" not in _sent_prompt(fake_client).lower()


def test_multiline_vocabulary_is_collapsed_to_one_line(tmp_path: Path) -> None:
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = MagicMock(text="x")
    _transcribe_with(fake_client, tmp_path, vocabulary_prompt="\nRails,\n  Docker\n")

    assert "Rails, Docker" in _sent_prompt(fake_client)


def test_transcribe_pins_temperature_to_zero(tmp_path: Path) -> None:
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = MagicMock(text="x")
    _transcribe_with(fake_client, tmp_path)

    assert fake_client.audio.transcriptions.create.call_args.kwargs["temperature"] == 0


def test_transcribe_returns_empty_when_model_echoes_the_full_prompt(tmp_path: Path) -> None:
    fake_client = MagicMock()

    # Capture whatever prompt we build, then replay it as the model's output.
    def echo_prompt(**kwargs):
        return MagicMock(text=kwargs["prompt"].upper())

    fake_client.audio.transcriptions.create.side_effect = echo_prompt
    result = _transcribe_with(
        fake_client, tmp_path, vocabulary_prompt="Rails, Docker", language="en"
    )
    assert result == ""


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
    assert (
        transcribe(client=fake_client, wav_path=wav, model="m", vocabulary_prompt="", language="")
        == "hi"
    )


def test_transcribe_returns_empty_when_model_echoes_vocabulary_prompt(tmp_path: Path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")
    vocab = "TypeScript, Postgres,\n  Rails, Docker"
    fake_client = MagicMock()
    # Simulate Whisper returning the vocabulary verbatim (with extra whitespace
    # and different casing) when there is no real speech.
    fake_client.audio.transcriptions.create.return_value = MagicMock(
        text="typescript, postgres, rails, docker\n"
    )
    result = transcribe(
        client=fake_client,
        wav_path=wav,
        model="m",
        vocabulary_prompt=vocab,
        language="",
    )
    assert result == ""


def test_transcribe_keeps_real_speech_that_overlaps_vocabulary(tmp_path: Path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.return_value = MagicMock(
        text="let me refactor this typescript file"
    )
    result = transcribe(
        client=fake_client,
        wav_path=wav,
        model="m",
        vocabulary_prompt="TypeScript, Postgres",
        language="",
    )
    assert result == "let me refactor this typescript file"


def test_transcribe_raises_on_api_error(tmp_path: Path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")
    fake_client = MagicMock()
    fake_client.audio.transcriptions.create.side_effect = RuntimeError("network down")
    with pytest.raises(TranscriberError, match="network down"):
        transcribe(client=fake_client, wav_path=wav, model="m", vocabulary_prompt="", language="")
