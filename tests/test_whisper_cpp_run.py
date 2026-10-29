import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from echo.config import LocalWhisperConfig
from echo.whisper_cpp import WhisperCppError, build_command, transcribe_with_timestamps

FIXTURE = Path(__file__).parent / "fixtures" / "whisper_cli_full.json"


def _config(tmp_path: Path) -> LocalWhisperConfig:
    return LocalWhisperConfig(
        binary="whisper-cli", model_path=tmp_path / "ggml-base.bin", language="auto"
    )


def test_build_command_argv(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    wav, out = tmp_path / "a.wav", tmp_path / "out"

    assert build_command(cfg, wav, out, language="pt", prompt="") == [
        "whisper-cli",
        "-m",
        str(tmp_path / "ggml-base.bin"),
        "-f",
        str(wav),
        "-l",
        "pt",
        "-ojf",
        "-of",
        str(out),
        "--no-prints",
    ]


def test_build_command_adds_prompt_when_present(tmp_path: Path) -> None:
    argv = build_command(_config(tmp_path), tmp_path / "a.wav", tmp_path / "o", "en", "Rails")

    assert argv[-2:] == ["--prompt", "Rails"]


def test_build_command_keeps_unicode_path_as_single_arg(tmp_path: Path) -> None:
    wav = Path("/tmp/reunião final.wav")

    assert str(wav) in build_command(_config(tmp_path), wav, tmp_path / "o", "auto", "")


def test_build_command_flattens_vocabulary_prompt(tmp_path: Path) -> None:
    argv = build_command(
        _config(tmp_path), tmp_path / "a.wav", tmp_path / "o", "en", "\n  Rails,\n\tDjango  \n"
    )

    assert argv[-1] == "Rails, Django"


def test_build_command_whitespace_only_prompt_is_omitted(tmp_path: Path) -> None:
    argv = build_command(_config(tmp_path), tmp_path / "a.wav", tmp_path / "o", "en", " \n ")

    assert "--prompt" not in argv


def _fake_run(writes: dict[str, Any] | None, returncode: int = 0, stderr: str = "") -> MagicMock:
    def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        out_base = Path(argv[argv.index("-of") + 1])
        if writes is not None:
            out_base.with_name(out_base.name + ".json").write_text(json.dumps(writes))
        return subprocess.CompletedProcess(argv, returncode, stdout="", stderr=stderr)

    return MagicMock(side_effect=run)


def test_transcribe_reads_json_written_by_cli(tmp_path: Path) -> None:
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    run = _fake_run(json.loads(FIXTURE.read_text()))

    transcript = transcribe_with_timestamps(
        wav_path=wav,
        config=_config(tmp_path),
        language="auto",
        vocabulary_prompt="",
        source="clip.mp4",
        run=run,
    )

    assert transcript.model == "ggml-base.bin"
    assert transcript.source == "clip.mp4"
    assert len(transcript.segments) == 2
    assert run.call_args.kwargs == {"check": False, "capture_output": True, "text": True}


def test_transcribe_cleans_up_its_temp_output(tmp_path: Path) -> None:
    seen: list[Path] = []
    inner = _fake_run(json.loads(FIXTURE.read_text()))

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append(Path(argv[argv.index("-of") + 1]).parent)
        return inner(argv, **kwargs)

    transcribe_with_timestamps(
        wav_path=tmp_path / "a.wav",
        config=_config(tmp_path),
        language="auto",
        vocabulary_prompt="",
        source="clip.mp4",
        run=run,
    )

    assert not seen[0].exists()


def test_transcribe_nonzero_exit_raises_with_stderr(tmp_path: Path) -> None:
    with pytest.raises(WhisperCppError, match="boom"):
        transcribe_with_timestamps(
            wav_path=tmp_path / "a.wav",
            config=_config(tmp_path),
            language="auto",
            vocabulary_prompt="",
            source="clip.mp4",
            run=_fake_run(None, returncode=3, stderr="boom"),
        )


def test_transcribe_missing_output_file_raises(tmp_path: Path) -> None:
    with pytest.raises(WhisperCppError, match="no JSON output"):
        transcribe_with_timestamps(
            wav_path=tmp_path / "a.wav",
            config=_config(tmp_path),
            language="auto",
            vocabulary_prompt="",
            source="clip.mp4",
            run=_fake_run(None),
        )


def test_transcribe_binary_not_found_raises(tmp_path: Path) -> None:
    def run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(argv[0])

    with pytest.raises(WhisperCppError, match="whisper-cli"):
        transcribe_with_timestamps(
            wav_path=tmp_path / "a.wav",
            config=_config(tmp_path),
            language="auto",
            vocabulary_prompt="",
            source="clip.mp4",
            run=run,
        )
