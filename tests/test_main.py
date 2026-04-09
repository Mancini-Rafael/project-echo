from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echo.config import Config


@pytest.fixture
def fake_config() -> Config:
    return Config(
        model="gpt-4o-transcribe",
        vocabulary_prompt="foo",
        language="en",
        sample_rate=16000,
        channels=1,
    )


def _patch_session_with_recording(mocker, main_mod, tmp_path: Path):
    """Patch RecordingSession so start() is a no-op and stop() returns a result."""
    fake_recording = MagicMock(wav_path=tmp_path / "clip.wav", duration_seconds=2.0)
    (tmp_path / "clip.wav").write_bytes(b"RIFF")
    fake_session = MagicMock()
    fake_session.is_recording = True
    fake_session.stop.return_value = fake_recording
    mocker.patch.object(main_mod, "RecordingSession", return_value=fake_session)
    # Skip the spacebar wait so the test runs without touching the terminal.
    mocker.patch.object(main_mod, "_wait_for_space", return_value=None)
    return fake_session, fake_recording


def test_main_happy_path(mocker, tmp_path: Path, fake_config: Config) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(main_mod.Config, "require_api_key", return_value="sk-test")
    _patch_session_with_recording(mocker, main_mod, tmp_path)
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())
    mocker.patch.object(main_mod, "transcribe", return_value="hello world")
    copy = mocker.patch.object(main_mod, "copy_to_clipboard")

    exit_code = main_mod.main(argv=[])

    assert exit_code == 0
    copy.assert_called_once_with("hello world")


def test_main_missing_api_key_exits_nonzero(mocker, fake_config: Config) -> None:
    from echo import __main__ as main_mod
    from echo.config import ConfigError

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(
        main_mod.Config,
        "require_api_key",
        side_effect=ConfigError("OPENAI_API_KEY not set"),
    )

    assert main_mod.main(argv=[]) != 0


def test_main_empty_transcription_does_not_copy(
    mocker, tmp_path: Path, fake_config: Config
) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(main_mod.Config, "require_api_key", return_value="sk-test")
    _patch_session_with_recording(mocker, main_mod, tmp_path)
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())
    mocker.patch.object(main_mod, "transcribe", return_value="")
    copy = mocker.patch.object(main_mod, "copy_to_clipboard")

    exit_code = main_mod.main(argv=[])

    assert exit_code != 0
    copy.assert_not_called()


def test_main_clean_flag_not_implemented(mocker, fake_config: Config) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(main_mod.Config, "require_api_key", return_value="sk-test")

    assert main_mod.main(argv=["--clean"]) != 0
