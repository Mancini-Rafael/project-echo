import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from echo.sounds import play, validate_paths


def test_play_empty_path_does_nothing(mocker) -> None:
    popen = mocker.patch("echo.sounds.subprocess.Popen")
    play("")
    popen.assert_not_called()


def test_play_missing_file_does_nothing(mocker, tmp_path: Path) -> None:
    popen = mocker.patch("echo.sounds.subprocess.Popen")
    play(str(tmp_path / "nope.aiff"))
    popen.assert_not_called()


def test_play_valid_file_invokes_afplay(mocker, tmp_path: Path) -> None:
    sound = tmp_path / "ok.aiff"
    sound.write_bytes(b"FORM")
    popen = mocker.patch("echo.sounds.subprocess.Popen")
    play(str(sound))
    popen.assert_called_once()
    args, _ = popen.call_args
    assert args[0] == ["afplay", str(sound)]


def test_play_swallows_popen_errors(mocker, tmp_path: Path, capsys) -> None:
    sound = tmp_path / "ok.aiff"
    sound.write_bytes(b"FORM")
    mocker.patch("echo.sounds.subprocess.Popen", side_effect=FileNotFoundError("afplay missing"))
    # Must not raise.
    play(str(sound))
    err = capsys.readouterr().err
    assert "afplay" in err


def test_validate_paths_keeps_existing(tmp_path: Path) -> None:
    s1 = tmp_path / "a.aiff"
    s1.write_bytes(b"FORM")
    out = validate_paths({"start": str(s1), "stop": ""})
    assert out["start"] == str(s1)
    assert out["stop"] == ""


def test_validate_paths_replaces_missing_with_empty(tmp_path: Path, capsys) -> None:
    s1 = tmp_path / "missing.aiff"
    out = validate_paths({"start": str(s1)})
    assert out["start"] == ""
    err = capsys.readouterr().err
    assert "missing" in err.lower() or "not found" in err.lower()
