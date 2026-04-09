# project-echo MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a macOS Python CLI named `ec` that records audio, transcribes it via OpenAI's `gpt-4o-transcribe`, prints the result, and copies it to the clipboard.

**Architecture:** Single-process Python CLI managed by `uv`. Modules split by responsibility — `recorder` (sounddevice capture + spacebar stop), `transcriber` (OpenAI client wrapper), `clipboard` (`pbcopy` shell-out), `config` (TOML loader), `ui` (terminal output), `__main__` (orchestration). Config lives in `./config/config.toml`, gitignored. API key from `OPENAI_API_KEY` env var only.

**Tech Stack:** Python 3.12+, `uv`, `sounddevice`, `openai` SDK, `numpy`, `pytest`, `pytest-mock`, macOS `pbcopy`.

**Spec:** `/Users/rafaelmancini/Projects/personal/project-echo/docs/superpowers/specs/2026-04-09-project-echo-design.md`

---

## File Map

| Path | Purpose |
|---|---|
| `pyproject.toml` | uv project config, deps, `ec` entry point |
| `.python-version` | Pin Python 3.12 |
| `.gitignore` | Standard Python + ignore `config/*` except example |
| `.env.example` | Documents `OPENAI_API_KEY` |
| `README.md` | Brief usage docs |
| `config/config.example.toml` | Committed config template |
| `config/config.toml` | Gitignored; auto-created on first run |
| `src/echo/__init__.py` | Package marker, version |
| `src/echo/__main__.py` | Argparse, top-level orchestration, exit codes |
| `src/echo/config.py` | Load TOML, bootstrap, defaults |
| `src/echo/recorder.py` | sounddevice capture + spacebar stop loop |
| `src/echo/transcriber.py` | OpenAI client wrapper |
| `src/echo/clipboard.py` | pbcopy subprocess wrapper |
| `src/echo/ui.py` | Terminal status lines, timer |
| `tests/__init__.py` | Test package marker |
| `tests/test_config.py` | Config loading tests |
| `tests/test_transcriber.py` | OpenAI client mocked |
| `tests/test_clipboard.py` | pbcopy mocked + macOS-gated round-trip |
| `tests/test_ui.py` | Snapshot tests for status lines |
| `tests/test_main.py` | End-to-end with everything mocked |

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `.env.example`, `README.md`
- Create: `src/echo/__init__.py`, `tests/__init__.py`
- Create: `config/config.example.toml`

- [ ] **Step 1: Create `.python-version`**

```
3.12
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "project-echo"
version = "0.1.0"
description = "CLI dictation tool: record audio, transcribe via OpenAI, copy to clipboard."
requires-python = ">=3.12"
dependencies = [
    "openai>=1.40.0",
    "sounddevice>=0.4.6",
    "numpy>=1.26.0",
    "soundfile>=0.12.1",
]

[project.scripts]
ec = "echo.__main__:main"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-mock>=3.12.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/echo"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 3: Create `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.venv/
dist/
build/

# Env
.env

# Config (gitignored except the example)
config/*
!config/config.example.toml

# OS
.DS_Store
```

- [ ] **Step 4: Create `.env.example`**

```
OPENAI_API_KEY=sk-...
```

- [ ] **Step 5: Create `README.md`**

```markdown
# project-echo

A macOS CLI that records audio, transcribes it via OpenAI, and copies the result to your clipboard.

## Setup

```sh
brew install portaudio
uv sync
cp config/config.example.toml config/config.toml
export OPENAI_API_KEY=sk-...
```

## Usage

```sh
uv run ec
```

Press space to stop recording. The transcription is printed and copied to your clipboard.
```

- [ ] **Step 6: Create `config/config.example.toml`**

```toml
[openai]
model = "gpt-4o-transcribe"

[transcription]
vocabulary_prompt = """
TypeScript, Python, Postgres, Kubernetes, Docker, Rails, Django, Flask,
React, Next.js, Tailwind, npm, pnpm, uv, async, await, webhook, OAuth,
Vulcan, Tarifei, Comex Radar, Rafael Mancini
"""
language = "en"

[recording]
sample_rate = 16000
channels = 1
```

- [ ] **Step 7: Create empty package markers**

`src/echo/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`: empty file

- [ ] **Step 8: Initialize uv environment**

Run:
```sh
cd /Users/rafaelmancini/Projects/personal/project-echo
uv sync
```
Expected: lockfile created, venv populated, no errors.

- [ ] **Step 9: Commit**

```sh
git add pyproject.toml .python-version .gitignore .env.example README.md config/config.example.toml src/echo/__init__.py tests/__init__.py uv.lock
git commit -m "chore: scaffold project-echo with uv"
```

---

## Task 2: Config module (TDD)

**Files:**
- Create: `src/echo/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for config loading**

`tests/test_config.py`:
```python
import os
import tomllib
from pathlib import Path

import pytest

from echo.config import Config, load_config, ConfigError


def test_load_config_from_file(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[openai]\nmodel = "gpt-4o-transcribe"\n'
        '[transcription]\nvocabulary_prompt = "foo bar"\nlanguage = "en"\n'
        '[recording]\nsample_rate = 16000\nchannels = 1\n'
    )
    cfg = load_config(cfg_path)
    assert cfg.model == "gpt-4o-transcribe"
    assert cfg.vocabulary_prompt == "foo bar"
    assert cfg.language == "en"
    assert cfg.sample_rate == 16000
    assert cfg.channels == 1


def test_load_config_bootstraps_from_example(tmp_path: Path) -> None:
    example = tmp_path / "config.example.toml"
    target = tmp_path / "config.toml"
    example.write_text(
        '[openai]\nmodel = "gpt-4o-transcribe"\n'
        '[transcription]\nvocabulary_prompt = ""\nlanguage = "en"\n'
        '[recording]\nsample_rate = 16000\nchannels = 1\n'
    )
    cfg = load_config(target, example_path=example)
    assert target.exists()
    assert cfg.model == "gpt-4o-transcribe"


def test_load_config_missing_and_no_example(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml", example_path=tmp_path / "nope.example.toml")


def test_load_config_malformed_toml(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("not = valid = toml")
    with pytest.raises(ConfigError, match="parse"):
        load_config(cfg_path)


def test_config_requires_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        Config.require_api_key()


def test_config_returns_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert Config.require_api_key() == "sk-test"
```

- [ ] **Step 2: Run tests, verify failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: ImportError / ModuleNotFoundError for `echo.config`.

- [ ] **Step 3: Implement `src/echo/config.py`**

```python
"""Config loading for project-echo.

Loads TOML config from disk, bootstraps from an example file on first run,
and reads the OpenAI API key from the environment.
"""
from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Raised when configuration cannot be loaded or is invalid."""


@dataclass(frozen=True)
class Config:
    model: str
    vocabulary_prompt: str
    language: str
    sample_rate: int
    channels: int

    @staticmethod
    def require_api_key() -> str:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ConfigError(
                "OPENAI_API_KEY environment variable is not set. "
                "Export it before running ec."
            )
        return key


def load_config(path: Path, example_path: Path | None = None) -> Config:
    if not path.exists():
        if example_path is not None and example_path.exists():
            shutil.copy(example_path, path)
        else:
            raise ConfigError(f"Config file not found: {path}")

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Failed to parse config at {path}: {e}") from e

    try:
        return Config(
            model=data["openai"]["model"],
            vocabulary_prompt=data["transcription"].get("vocabulary_prompt", ""),
            language=data["transcription"].get("language", ""),
            sample_rate=int(data["recording"]["sample_rate"]),
            channels=int(data["recording"]["channels"]),
        )
    except KeyError as e:
        raise ConfigError(f"Missing required config key: {e}") from e
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```sh
git add src/echo/config.py tests/test_config.py
git commit -m "feat(config): TOML loader with example bootstrap and API key check"
```

---

## Task 3: Clipboard module (TDD)

**Files:**
- Create: `src/echo/clipboard.py`
- Test: `tests/test_clipboard.py`

- [ ] **Step 1: Write failing tests**

`tests/test_clipboard.py`:
```python
import platform
import subprocess
from unittest.mock import MagicMock

import pytest

from echo.clipboard import ClipboardError, copy_to_clipboard


def test_copy_to_clipboard_invokes_pbcopy(mocker) -> None:
    run = mocker.patch("echo.clipboard.subprocess.run")
    run.return_value = MagicMock(returncode=0)
    copy_to_clipboard("hello world")
    run.assert_called_once()
    args, kwargs = run.call_args
    assert args[0] == ["pbcopy"]
    assert kwargs["input"] == b"hello world"
    assert kwargs["check"] is True


def test_copy_to_clipboard_raises_on_pbcopy_failure(mocker) -> None:
    mocker.patch(
        "echo.clipboard.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "pbcopy"),
    )
    with pytest.raises(ClipboardError):
        copy_to_clipboard("hi")


def test_copy_to_clipboard_raises_on_missing_pbcopy(mocker) -> None:
    mocker.patch("echo.clipboard.subprocess.run", side_effect=FileNotFoundError)
    with pytest.raises(ClipboardError, match="pbcopy"):
        copy_to_clipboard("hi")


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-only round trip")
def test_clipboard_round_trip_real_pbcopy() -> None:
    copy_to_clipboard("project-echo round trip")
    out = subprocess.run(["pbpaste"], capture_output=True, check=True)
    assert out.stdout.decode() == "project-echo round trip"
```

- [ ] **Step 2: Run tests, verify failure**

Run: `uv run pytest tests/test_clipboard.py -v`
Expected: ImportError for `echo.clipboard`.

- [ ] **Step 3: Implement `src/echo/clipboard.py`**

```python
"""Thin wrapper around macOS pbcopy."""
from __future__ import annotations

import subprocess


class ClipboardError(Exception):
    """Raised when the clipboard operation fails."""


def copy_to_clipboard(text: str) -> None:
    try:
        subprocess.run(
            ["pbcopy"],
            input=text.encode("utf-8"),
            check=True,
        )
    except FileNotFoundError as e:
        raise ClipboardError("pbcopy not found; project-echo only supports macOS") from e
    except subprocess.CalledProcessError as e:
        raise ClipboardError(f"pbcopy failed with exit code {e.returncode}") from e
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_clipboard.py -v`
Expected: 4 passed (or 3 passed + 1 skipped on non-macOS).

- [ ] **Step 5: Commit**

```sh
git add src/echo/clipboard.py tests/test_clipboard.py
git commit -m "feat(clipboard): pbcopy wrapper with error handling"
```

---

## Task 4: UI module (snapshot tests)

**Files:**
- Create: `src/echo/ui.py`
- Test: `tests/test_ui.py`

- [ ] **Step 1: Write failing tests**

`tests/test_ui.py`:
```python
from echo.ui import format_recording_line, format_transcription, format_error


def test_format_recording_line_zero_seconds() -> None:
    assert format_recording_line(0) == "● Recording... (press space to stop) 0:00"


def test_format_recording_line_padding() -> None:
    assert format_recording_line(5) == "● Recording... (press space to stop) 0:05"
    assert format_recording_line(65) == "● Recording... (press space to stop) 1:05"
    assert format_recording_line(600) == "● Recording... (press space to stop) 10:00"


def test_format_transcription() -> None:
    assert format_transcription("hello") == "> hello"


def test_format_error() -> None:
    assert format_error("boom") == "✗ boom"
```

- [ ] **Step 2: Run tests, verify failure**

Run: `uv run pytest tests/test_ui.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/echo/ui.py`**

```python
"""Terminal output helpers for project-echo."""
from __future__ import annotations


def format_recording_line(elapsed_seconds: int) -> str:
    minutes, seconds = divmod(int(elapsed_seconds), 60)
    return f"● Recording... (press space to stop) {minutes}:{seconds:02d}"


def format_transcription(text: str) -> str:
    return f"> {text}"


def format_error(message: str) -> str:
    return f"✗ {message}"
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_ui.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```sh
git add src/echo/ui.py tests/test_ui.py
git commit -m "feat(ui): terminal status line formatters"
```

---

## Task 5: Transcriber module (TDD with mocked OpenAI)

**Files:**
- Create: `src/echo/transcriber.py`
- Test: `tests/test_transcriber.py`

- [ ] **Step 1: Write failing tests**

`tests/test_transcriber.py`:
```python
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
```

- [ ] **Step 2: Run tests, verify failure**

Run: `uv run pytest tests/test_transcriber.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `src/echo/transcriber.py`**

```python
"""OpenAI audio transcription wrapper."""
from __future__ import annotations

from pathlib import Path
from typing import Any


class TranscriberError(Exception):
    """Raised when transcription fails."""


def transcribe(
    *,
    client: Any,
    wav_path: Path,
    model: str,
    vocabulary_prompt: str,
    language: str,
) -> str:
    kwargs: dict[str, Any] = {
        "model": model,
        "prompt": vocabulary_prompt,
    }
    if language:
        kwargs["language"] = language

    try:
        with wav_path.open("rb") as f:
            kwargs["file"] = f
            response = client.audio.transcriptions.create(**kwargs)
    except Exception as e:
        raise TranscriberError(f"OpenAI transcription failed: {e}") from e

    return (response.text or "").strip()
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_transcriber.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```sh
git add src/echo/transcriber.py tests/test_transcriber.py
git commit -m "feat(transcriber): OpenAI audio API wrapper with vocabulary prompt"
```

---

## Task 6: Recorder module (no automated tests)

**Files:**
- Create: `src/echo/recorder.py`

Per the spec, this module is hardware-dependent and intentionally has no
automated tests. It is verified manually in Task 8.

- [ ] **Step 1: Implement `src/echo/recorder.py`**

```python
"""Microphone capture with spacebar stop.

Records from the default input device into an in-memory buffer until the user
presses space (or Ctrl-C). Writes the buffer to a WAV file at the requested path.
"""
from __future__ import annotations

import select
import sys
import termios
import time
import tty
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd
import soundfile as sf


class RecorderError(Exception):
    """Raised when audio capture fails."""


@dataclass
class RecordingResult:
    wav_path: Path
    duration_seconds: float


def record_until_space(
    *,
    output_path: Path,
    sample_rate: int,
    channels: int,
    on_tick: Callable[[int], None] | None = None,
    min_duration: float = 0.5,
) -> RecordingResult:
    """Record from the default mic until space is pressed.

    Calls `on_tick(elapsed_seconds)` once per second so the caller can
    update a status line. Raises RecorderError if the recording is shorter
    than `min_duration`.
    """
    chunks: list[np.ndarray] = []

    def callback(indata, frames, time_info, status):  # noqa: ARG001
        if status:
            # Drop input overflow warnings silently; non-fatal.
            pass
        chunks.append(indata.copy())

    try:
        stream = sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            callback=callback,
        )
    except Exception as e:
        raise RecorderError(
            f"Failed to open microphone: {e}. "
            "Grant Terminal mic access in System Settings → Privacy & Security → Microphone."
        ) from e

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    start = time.monotonic()
    last_tick = -1

    try:
        tty.setcbreak(fd)
        stream.start()
        while True:
            elapsed = int(time.monotonic() - start)
            if elapsed != last_tick and on_tick is not None:
                on_tick(elapsed)
                last_tick = elapsed

            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch = sys.stdin.read(1)
                if ch == " ":
                    break
    finally:
        try:
            stream.stop()
            stream.close()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    duration = time.monotonic() - start
    if duration < min_duration or not chunks:
        raise RecorderError(f"Recording too short ({duration:.2f}s); discarded")

    audio = np.concatenate(chunks, axis=0)
    sf.write(str(output_path), audio, sample_rate, subtype="PCM_16")
    return RecordingResult(wav_path=output_path, duration_seconds=duration)
```

- [ ] **Step 2: Commit**

```sh
git add src/echo/recorder.py
git commit -m "feat(recorder): sounddevice capture with spacebar stop"
```

---

## Task 7: Main entry point with end-to-end test

**Files:**
- Create: `src/echo/__main__.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing end-to-end test**

`tests/test_main.py`:
```python
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


def test_main_happy_path(mocker, tmp_path: Path, fake_config: Config) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(main_mod.Config, "require_api_key", return_value="sk-test")

    fake_recording = MagicMock(wav_path=tmp_path / "clip.wav", duration_seconds=2.0)
    (tmp_path / "clip.wav").write_bytes(b"RIFF")
    mocker.patch.object(main_mod, "record_until_space", return_value=fake_recording)

    fake_client = MagicMock()
    mocker.patch.object(main_mod, "OpenAI", return_value=fake_client)
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


def test_main_empty_transcription_does_not_copy(mocker, tmp_path: Path, fake_config: Config) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(main_mod.Config, "require_api_key", return_value="sk-test")

    fake_recording = MagicMock(wav_path=tmp_path / "clip.wav", duration_seconds=2.0)
    (tmp_path / "clip.wav").write_bytes(b"RIFF")
    mocker.patch.object(main_mod, "record_until_space", return_value=fake_recording)
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
```

- [ ] **Step 2: Run tests, verify failure**

Run: `uv run pytest tests/test_main.py -v`
Expected: ImportError or attribute errors.

- [ ] **Step 3: Implement `src/echo/__main__.py`**

```python
"""Entry point for the `ec` command."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from openai import OpenAI

from echo.clipboard import ClipboardError, copy_to_clipboard
from echo.config import Config, ConfigError, load_config
from echo.recorder import RecorderError, record_until_space
from echo.transcriber import TranscriberError, transcribe
from echo.ui import format_error, format_recording_line, format_transcription


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "config.toml"
EXAMPLE_PATH = REPO_ROOT / "config" / "config.example.toml"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ec",
        description="Record audio, transcribe via OpenAI, copy to clipboard.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="(reserved) post-process the transcription via an LLM cleanup pass",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print per-stage timing breakdown to stderr",
    )
    return parser.parse_args(argv)


def _print_status(line: str) -> None:
    sys.stderr.write(f"\r{line}")
    sys.stderr.flush()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.clean:
        sys.stderr.write(format_error("--clean is not implemented in the MVP") + "\n")
        return 2

    try:
        cfg = load_config(CONFIG_PATH, example_path=EXAMPLE_PATH)
        api_key = Config.require_api_key()
    except ConfigError as e:
        sys.stderr.write(format_error(str(e)) + "\n")
        return 1

    timings: dict[str, float] = {}
    wav_path = Path(f"/tmp/echo-{int(time.time())}.wav")

    try:
        t0 = time.monotonic()
        recording = record_until_space(
            output_path=wav_path,
            sample_rate=cfg.sample_rate,
            channels=cfg.channels,
            on_tick=lambda elapsed: _print_status(format_recording_line(elapsed)),
        )
        sys.stderr.write("\n")
        timings["record"] = time.monotonic() - t0
    except RecorderError as e:
        sys.stderr.write("\n" + format_error(str(e)) + "\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        if wav_path.exists():
            wav_path.unlink(missing_ok=True)
        return 130

    sys.stderr.write("✓ Transcribing...\n")

    try:
        t1 = time.monotonic()
        client = OpenAI(api_key=api_key)
        text = transcribe(
            client=client,
            wav_path=recording.wav_path,
            model=cfg.model,
            vocabulary_prompt=cfg.vocabulary_prompt,
            language=cfg.language,
        )
        timings["transcribe"] = time.monotonic() - t1
    except TranscriberError as e:
        sys.stderr.write(format_error(str(e)) + "\n")
        sys.stderr.write(f"  WAV kept at: {wav_path}\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write(f"\n  WAV kept at: {wav_path}\n")
        return 130

    if not text:
        sys.stderr.write(format_error("transcription empty; clipboard unchanged") + "\n")
        wav_path.unlink(missing_ok=True)
        return 1

    print(format_transcription(text))

    try:
        copy_to_clipboard(text)
        sys.stderr.write("✓ Copied to clipboard.\n")
    except ClipboardError as e:
        sys.stderr.write(format_error(f"{e} (transcription printed above)") + "\n")
        # Don't delete WAV in this case; user may want to retry.
        return 1

    wav_path.unlink(missing_ok=True)

    if args.verbose:
        sys.stderr.write(
            f"  timings: record={timings.get('record', 0):.2f}s "
            f"transcribe={timings.get('transcribe', 0):.2f}s "
            f"recording_duration={recording.duration_seconds:.2f}s\n"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests, verify pass**

Run: `uv run pytest tests/test_main.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests pass (config, clipboard, ui, transcriber, main).

- [ ] **Step 6: Commit**

```sh
git add src/echo/__main__.py tests/test_main.py
git commit -m "feat: wire up ec entry point with end-to-end orchestration"
```

---

## Task 8: Manual smoke test

This is the only verification of the recorder module. Requires real hardware,
real API call, real clipboard.

- [ ] **Step 1: Confirm prerequisites**

```sh
brew list portaudio || brew install portaudio
echo "$OPENAI_API_KEY" | head -c 10  # should print sk-... (first 10 chars)
ls config/config.toml || cp config/config.example.toml config/config.toml
```

- [ ] **Step 2: Run the CLI**

```sh
cd /Users/rafaelmancini/Projects/personal/project-echo
uv run ec
```

Expected:
- See `● Recording... (press space to stop) 0:00`, timer ticks
- Speak a short test phrase ("hello, this is a test of project echo")
- Press space
- See `✓ Transcribing...`
- See `> hello, this is a test of project echo`
- See `✓ Copied to clipboard.`
- Run `pbpaste` in another terminal — should match the printed text

- [ ] **Step 3: Run with `--verbose` and verify timings printed**

```sh
uv run ec --verbose
```

Expected: same flow, plus a timings line on stderr at the end.

- [ ] **Step 4: Verify failure modes manually**

- Unset `OPENAI_API_KEY` and run `uv run ec` → exits with clear error before mic opens.
- Run `uv run ec --clean` → exits with "not implemented" message.
- Run `uv run ec`, immediately press space (under 0.5s) → "Recording too short" error.

- [ ] **Step 5: If anything misbehaves, file findings**

If a real-world bug surfaces (latency, accuracy, UX), capture it as an issue
or follow-up note in `docs/superpowers/specs/` rather than fixing it inline —
the MVP scope is locked.
