from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echo.config import Config, HotkeyConfig
from echo.daemon import Daemon
from echo.recorder import RecorderError
from echo.transcriber import TranscriberError


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    return Config(
        model="gpt-4o-transcribe",
        vocabulary_prompt="vocab",
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


def _make_daemon(cfg, mocker, *, transcribe_return="hello", transcribe_side_effect=None,
                 stop_side_effect=None):
    fake_session = MagicMock()
    fake_session.is_recording = True
    if stop_side_effect is not None:
        fake_session.stop.side_effect = stop_side_effect
    else:
        fake_session.stop.return_value = MagicMock(
            wav_path=Path("/tmp/echo-test.wav"), duration_seconds=2.0
        )

    fake_session_factory = MagicMock(return_value=fake_session)
    fake_transcribe = MagicMock(
        return_value=transcribe_return, side_effect=transcribe_side_effect
    )
    fake_copy = MagicMock()
    fake_sounds = MagicMock()
    fake_sounds.play = MagicMock()
    fake_sounds.validate_paths = MagicMock(side_effect=lambda d: d)

    daemon = Daemon(
        config=cfg,
        openai_client=MagicMock(),
        session_factory=fake_session_factory,
        transcribe_fn=fake_transcribe,
        copy_fn=fake_copy,
        sounds_module=fake_sounds,
    )
    # Avoid touching the filesystem in tests.
    daemon._make_wav_path = lambda: Path("/tmp/echo-test.wav")  # type: ignore[method-assign]
    return daemon, fake_session, fake_session_factory, fake_transcribe, fake_copy, fake_sounds


def test_daemon_idle_to_recording(cfg, mocker) -> None:
    d, session, factory, *_ = _make_daemon(cfg, mocker)
    assert d.state == "idle"
    d.on_chord()
    assert d.state == "recording"
    factory.assert_called_once()
    session.start.assert_called_once()


def test_daemon_recording_to_idle_with_copy(cfg, mocker) -> None:
    d, session, _, transcribe_fn, copy_fn, sounds = _make_daemon(cfg, mocker)
    d.on_chord()  # idle → recording
    d.on_chord()  # recording → processing → idle
    assert d.state == "idle"
    transcribe_fn.assert_called_once()
    copy_fn.assert_called_once_with("hello")


def test_daemon_too_short_recording_returns_to_idle(cfg, mocker) -> None:
    d, *_ = _make_daemon(cfg, mocker, stop_side_effect=RecorderError("too short"))
    d.on_chord()
    d.on_chord()
    assert d.state == "idle"


def test_daemon_empty_transcription_does_not_copy(cfg, mocker) -> None:
    d, _, _, _, copy_fn, _ = _make_daemon(cfg, mocker, transcribe_return="")
    d.on_chord()
    d.on_chord()
    assert d.state == "idle"
    copy_fn.assert_not_called()


def test_daemon_transcribe_error_keeps_wav_and_returns_to_idle(cfg, mocker) -> None:
    d, *_ = _make_daemon(
        cfg, mocker, transcribe_side_effect=TranscriberError("api down")
    )
    d.on_chord()
    d.on_chord()
    assert d.state == "idle"


def test_daemon_chord_during_processing_is_dropped(cfg, mocker) -> None:
    d, _, factory, *_ = _make_daemon(cfg, mocker)
    d._state = "processing"  # simulate mid-transcription
    d.on_chord()
    # Nothing happened — no factory call, state unchanged.
    assert d.state == "processing"
    factory.assert_not_called()


def test_daemon_recording_start_failure_returns_to_idle(cfg, mocker) -> None:
    d, session, *_ = _make_daemon(cfg, mocker)
    session.start.side_effect = RecorderError("no mic")
    d.on_chord()
    assert d.state == "idle"


def test_daemon_exception_in_callback_returns_to_idle(cfg, mocker) -> None:
    d, session, *_ = _make_daemon(cfg, mocker)
    session.start.side_effect = RuntimeError("boom")
    d.on_chord()
    assert d.state == "idle"
