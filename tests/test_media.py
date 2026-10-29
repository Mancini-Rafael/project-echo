import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from echo.media import MediaError, extract_audio

NO_AUDIO_STDERR = (
    "Stream map '0:a:0' matches no streams.\nTo ignore this, add a trailing '?' to the map.\n"
)


def _run(returncode: int = 0, stderr: str = "") -> MagicMock:
    def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, returncode, stdout="", stderr=stderr)

    return MagicMock(side_effect=run)


def _video(tmp_path: Path, name: str = "clip.mp4") -> Path:
    video = tmp_path / name
    video.write_bytes(b"\x00")
    return video


def test_extract_audio_argv(tmp_path: Path) -> None:
    video, wav = _video(tmp_path), tmp_path / "out.wav"
    run = _run()

    extract_audio(video, wav, ffmpeg_binary="/opt/ffmpeg", run=run)

    assert run.call_args.args[0] == [
        "/opt/ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(wav),
    ]
    assert run.call_args.kwargs == {"check": False, "capture_output": True, "text": True}


def test_extract_audio_unicode_path_single_arg(tmp_path: Path) -> None:
    video = _video(tmp_path, "reunião final.mp4")
    run = _run()

    extract_audio(video, tmp_path / "out.wav", run=run)

    assert str(video) in run.call_args.args[0]


def test_no_audio_stream_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(MediaError, match=r"no audio stream in clip\.mp4"):
        extract_audio(_video(tmp_path), tmp_path / "out.wav", run=_run(234, stderr=NO_AUDIO_STDERR))


def test_other_ffmpeg_failure_includes_stderr(tmp_path: Path) -> None:
    with pytest.raises(MediaError, match="Invalid data found"):
        extract_audio(
            _video(tmp_path),
            tmp_path / "out.wav",
            run=_run(1, stderr="clip.mp4: Invalid data found when processing input"),
        )


def test_missing_input_file_raises_before_running(tmp_path: Path) -> None:
    run = _run()

    with pytest.raises(MediaError, match="not found"):
        extract_audio(tmp_path / "nope.mp4", tmp_path / "out.wav", run=run)

    run.assert_not_called()


def test_ffmpeg_binary_not_installed_raises(tmp_path: Path) -> None:
    def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(argv[0])

    with pytest.raises(MediaError, match="ffmpeg not found"):
        extract_audio(_video(tmp_path), tmp_path / "out.wav", run=run)
