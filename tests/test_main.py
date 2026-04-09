import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echo.config import Config, HotkeyConfig


@pytest.fixture
def fake_config() -> Config:
    return Config(
        model="gpt-4o-transcribe",
        vocabulary_prompt="foo",
        language="en",
        sample_rate=16000,
        channels=1,
        hotkey=HotkeyConfig(
            chord=("control", "option", "command"),
            sound_start="",
            sound_stop="",
            sound_empty="",
        ),
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


# ----- subcommand dispatch -----

def test_main_listen_constructs_and_runs_daemon(mocker, fake_config: Config) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(main_mod.Config, "require_api_key", return_value="sk-test")
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())

    fake_daemon = MagicMock()
    fake_daemon.run.return_value = 0
    mocker.patch.object(main_mod, "Daemon", return_value=fake_daemon)

    # Stub out PID file lifecycle so we don't touch /tmp.
    mocker.patch.object(main_mod, "_acquire_pid_file")
    mocker.patch.object(main_mod, "_release_pid_file")

    exit_code = main_mod.main(argv=["listen"])
    assert exit_code == 0
    fake_daemon.run.assert_called_once()


def test_main_stop_with_no_pid_file(mocker, tmp_path: Path) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "PID_FILE", tmp_path / "echo-daemon.pid")
    exit_code = main_mod.main(argv=["stop"])
    assert exit_code == 0


def test_main_stop_sends_sigterm_when_alive(mocker, tmp_path: Path) -> None:
    from echo import __main__ as main_mod

    pid_file = tmp_path / "echo-daemon.pid"
    pid_file.write_text("12345")
    mocker.patch.object(main_mod, "PID_FILE", pid_file)
    kill = mocker.patch.object(main_mod.os, "kill")
    # First call: SIGTERM. Second call: poll alive. Third call: poll dead.
    kill.side_effect = [None, None, ProcessLookupError]
    exit_code = main_mod.main(argv=["stop"])
    assert exit_code == 0
    # SIGTERM was sent first.
    assert kill.call_args_list[0][0][1] == 15  # signal.SIGTERM


def test_main_listen_refuses_when_pid_file_exists_and_alive(
    mocker, tmp_path: Path, fake_config: Config
) -> None:
    from echo import __main__ as main_mod

    pid_file = tmp_path / "echo-daemon.pid"
    pid_file.write_text("12345")
    mocker.patch.object(main_mod, "PID_FILE", pid_file)
    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(main_mod.Config, "require_api_key", return_value="sk-test")
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())
    mocker.patch.object(main_mod.os, "kill", return_value=None)  # process is "alive"

    exit_code = main_mod.main(argv=["listen"])
    assert exit_code == 1


def test_main_listen_cleans_stale_pid_file(
    mocker, tmp_path: Path, fake_config: Config
) -> None:
    from echo import __main__ as main_mod

    pid_file = tmp_path / "echo-daemon.pid"
    pid_file.write_text("12345")
    mocker.patch.object(main_mod, "PID_FILE", pid_file)
    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(main_mod.Config, "require_api_key", return_value="sk-test")
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())
    mocker.patch.object(main_mod.os, "kill", side_effect=ProcessLookupError)

    fake_daemon = MagicMock()
    fake_daemon.run.return_value = 0
    mocker.patch.object(main_mod, "Daemon", return_value=fake_daemon)

    exit_code = main_mod.main(argv=["listen"])
    assert exit_code == 0
    # The PID file should have been cleaned up at end (released).
    assert not pid_file.exists()
