# Hotkey Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a long-running daemon (`ec listen`) that listens for a configurable global keyboard chord, toggles audio recording on/off, and runs the existing transcribe → clipboard pipeline. Includes `ec stop` for shutdown and a PID file for lifecycle management.

**Architecture:** Refactor the existing `record_until_space()` into a thread-friendly `RecordingSession` class so both the one-shot CLI and the new daemon use the same capture code. Add three new small modules: `hotkey.py` (chord parsing + detector state machine), `sounds.py` (afplay wrapper), and `daemon.py` (orchestrates pynput listener, RecordingSession, transcriber, clipboard via a three-state machine guarded by a `threading.Lock` acquired non-blocking). Extend `__main__.py` with argparse subcommands and PID-file lifecycle.

**Tech Stack:** Python 3.12+, `uv`, existing deps (`openai`, `sounddevice`, `numpy`, `soundfile`), **new dep: `pynput>=1.7.7`**, macOS `afplay` and `pbcopy` (built-in).

**Spec:** `/Users/rafaelmancini/Projects/personal/project-echo/docs/superpowers/specs/2026-04-09-hotkey-daemon-design.md`

---

## File Map

| Path | Status | Purpose |
|---|---|---|
| `pyproject.toml` | MODIFY | Add `pynput>=1.7.7` to dependencies |
| `src/echo/recorder.py` | REWRITE | Replace `record_until_space` with `RecordingSession` class |
| `src/echo/hotkey.py` | NEW | `parse_chord` + `ChordDetector` (pure logic) |
| `src/echo/sounds.py` | NEW | `play` and `validate_paths`, wraps afplay |
| `src/echo/daemon.py` | NEW | `Daemon` class — state machine and orchestration |
| `src/echo/config.py` | MODIFY | Add `HotkeyConfig` dataclass and `[hotkey]` parsing |
| `src/echo/__main__.py` | REWRITE | Subcommand dispatch + `_wait_for_space` helper + PID file logic |
| `config/config.example.toml` | MODIFY | Add `[hotkey]` and `[hotkey.sounds]` sections |
| `tests/test_recorder.py` | NEW (smoke only) | One trivial import-and-construct test for `RecordingSession` |
| `tests/test_hotkey.py` | NEW | parse_chord + ChordDetector unit tests |
| `tests/test_sounds.py` | NEW | afplay wrapper tests with subprocess mocked |
| `tests/test_daemon.py` | NEW | Daemon state machine tests with all I/O mocked |
| `tests/test_config.py` | MODIFY | Add `[hotkey]` parsing tests + default behavior |
| `tests/test_main.py` | REWRITE | Subcommand dispatch + PID file logic; existing one-shot tests adapted to new recorder API |
| `README.md` | MODIFY | Document `ec listen`, `ec stop`, accessibility permission, hotkey config |

---

## Task 1: Recorder refactor — RecordingSession class

This task introduces the new recorder API and updates the one-shot `ec` path so existing functionality stays green. After this task, `record_until_space` no longer exists.

**Files:**
- Modify: `src/echo/recorder.py` (full rewrite of the module)
- Modify: `src/echo/__main__.py` (rewrite the recording portion to use `RecordingSession`)
- Modify: `tests/test_main.py` (replace `record_until_space` mocks with `RecordingSession` mocks)

- [ ] **Step 1: Rewrite `src/echo/recorder.py`**

```python
"""Microphone capture as a thread-friendly session.

`RecordingSession` opens an input stream on `start()`, captures into an
in-memory buffer, and writes a 16-bit PCM WAV on `stop()`. It can be driven
from any thread; start/stop are independent of stdin or terminal state.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf


class RecorderError(Exception):
    """Raised when audio capture fails."""


@dataclass
class RecordingResult:
    wav_path: Path
    duration_seconds: float


class RecordingSession:
    """Captures audio from the default mic into an in-memory buffer.

    Lifecycle: construct → start() → (later, possibly from another thread) stop().
    A single instance is single-use; create a new one for each recording.
    """

    def __init__(
        self,
        *,
        sample_rate: int,
        channels: int,
        min_duration: float = 0.5,
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._min_duration = min_duration
        self._chunks: list[np.ndarray] = []
        self._chunks_lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._start_time: float | None = None
        self._stopped = False

    @property
    def is_recording(self) -> bool:
        return self._stream is not None and not self._stopped

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        # Drop sounddevice status flags silently; they are non-fatal warnings.
        with self._chunks_lock:
            self._chunks.append(indata.copy())

    def start(self) -> None:
        if self._stream is not None:
            raise RecorderError("RecordingSession already started")
        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="int16",
                callback=self._callback,
            )
            self._stream.start()
        except Exception as e:
            self._stream = None
            raise RecorderError(
                f"Failed to open microphone: {e}. "
                "Grant Terminal mic access in System Settings → Privacy & Security → Microphone."
            ) from e
        self._start_time = time.monotonic()

    def stop(self, output_path: Path) -> RecordingResult:
        if self._stream is None or self._start_time is None:
            raise RecorderError("RecordingSession was never started")
        if self._stopped:
            raise RecorderError("RecordingSession already stopped")
        self._stopped = True

        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None

        duration = time.monotonic() - self._start_time

        with self._chunks_lock:
            if not self._chunks or duration < self._min_duration:
                raise RecorderError(
                    f"Recording too short ({duration:.2f}s); discarded"
                )
            audio = np.concatenate(self._chunks, axis=0)

        sf.write(str(output_path), audio, self._sample_rate, subtype="PCM_16")
        return RecordingResult(wav_path=output_path, duration_seconds=duration)
```

- [ ] **Step 2: Verify the module imports cleanly**

Run:
```sh
uv run python -c "from echo.recorder import RecordingSession, RecordingResult, RecorderError; s = RecordingSession(sample_rate=16000, channels=1); print('ok', s.is_recording)"
```
Expected: `ok False`

- [ ] **Step 3: Rewrite the recording section of `src/echo/__main__.py`**

Replace the entire file with this version. (We will add subcommand dispatch in Task 6 — for now we keep the existing single-command shape but switch to the new recorder API.)

```python
"""Entry point for the `ec` command."""
from __future__ import annotations

import argparse
import select
import sys
import termios
import time
import tty
from pathlib import Path

from openai import OpenAI

from echo.clipboard import ClipboardError, copy_to_clipboard
from echo.config import Config, ConfigError, load_config
from echo.recorder import RecorderError, RecordingSession
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


def _wait_for_space(session: RecordingSession) -> None:
    """Block until the user presses space, ticking a status line.

    Puts the terminal in cbreak mode so a single character is read without
    waiting for newline. Restores the terminal on exit.
    """
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    start = time.monotonic()
    last_tick = -1
    try:
        tty.setcbreak(fd)
        while session.is_recording:
            elapsed = int(time.monotonic() - start)
            if elapsed != last_tick:
                _print_status(format_recording_line(elapsed))
                last_tick = elapsed
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch = sys.stdin.read(1)
                if ch == " ":
                    return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


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
    session = RecordingSession(sample_rate=cfg.sample_rate, channels=cfg.channels)

    try:
        t0 = time.monotonic()
        try:
            session.start()
        except RecorderError as e:
            sys.stderr.write(format_error(str(e)) + "\n")
            return 1
        _wait_for_space(session)
        try:
            recording = session.stop(wav_path)
        except RecorderError as e:
            sys.stderr.write("\n" + format_error(str(e)) + "\n")
            return 1
        sys.stderr.write("\n")
        timings["record"] = time.monotonic() - t0
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        if session.is_recording:
            try:
                session.stop(wav_path)
            except RecorderError:
                pass
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

- [ ] **Step 4: Update `tests/test_main.py` to mock the new API**

Replace the file with:
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
```

- [ ] **Step 5: Run the full suite — everything should be green**

```sh
uv run pytest -q
```
Expected: all existing tests pass. The recorder refactor is complete and the
one-shot path uses `RecordingSession` via mocked `_wait_for_space`.

- [ ] **Step 6: Commit**

```sh
git add src/echo/recorder.py src/echo/__main__.py tests/test_main.py
git commit -m "refactor(recorder): introduce RecordingSession class"
```

---

## Task 2: hotkey module — parse_chord + ChordDetector

**Files:**
- Modify: `pyproject.toml` (add pynput dep)
- Create: `src/echo/hotkey.py`
- Create: `tests/test_hotkey.py`

- [ ] **Step 1: Add pynput to `pyproject.toml`**

Edit the `[project] dependencies` array to add `pynput>=1.7.7`. The full updated section:

```toml
dependencies = [
    "openai>=1.40.0",
    "sounddevice>=0.4.6",
    "numpy>=1.26.0",
    "soundfile>=0.12.1",
    "pynput>=1.7.7",
]
```

- [ ] **Step 2: Sync the lockfile**

```sh
uv sync
```
Expected: pynput and its transitive deps installed, no errors. Confirm with:
```sh
uv run python -c "import pynput; print(pynput.__version__)"
```

- [ ] **Step 3: Write failing tests for `hotkey.py`**

Create `tests/test_hotkey.py`:
```python
import pytest
from pynput.keyboard import Key, KeyCode

from echo.config import ConfigError
from echo.hotkey import ChordDetector, parse_chord


# ----- parse_chord -----

def test_parse_chord_modifiers() -> None:
    slots = parse_chord(["ctrl", "alt", "cmd"])
    # Each slot is a frozenset; modifier slots include both L and R variants.
    assert len(slots) == 3
    assert Key.ctrl_l in slots[0] and Key.ctrl_r in slots[0]
    assert Key.alt_l in slots[1] and Key.alt_r in slots[1]
    assert Key.cmd_l in slots[2] and Key.cmd_r in slots[2]


def test_parse_chord_named_keys() -> None:
    slots = parse_chord(["space", "f1"])
    assert Key.space in slots[0]
    assert Key.f1 in slots[1]


def test_parse_chord_letter() -> None:
    slots = parse_chord(["ctrl", "a"])
    assert KeyCode.from_char("a") in slots[1]


def test_parse_chord_unknown_key_raises() -> None:
    with pytest.raises(ConfigError, match="Unknown hotkey key"):
        parse_chord(["ctrl", "wat"])


def test_parse_chord_empty_raises() -> None:
    with pytest.raises(ConfigError, match="empty"):
        parse_chord([])


# ----- ChordDetector -----

def _make_detector():
    slots = parse_chord(["ctrl", "alt", "cmd"])
    fired = []
    detector = ChordDetector(slots=slots, on_pressed=lambda: fired.append(1))
    return detector, fired


def test_chord_fires_once_on_full_press() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_l)
    detector.on_press(Key.alt_l)
    detector.on_press(Key.cmd_l)
    assert fired == [1]


def test_chord_does_not_fire_on_partial_press() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_l)
    detector.on_press(Key.alt_l)
    assert fired == []


def test_chord_does_not_fire_again_while_held() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_l)
    detector.on_press(Key.alt_l)
    detector.on_press(Key.cmd_l)
    # Press an extra key while still holding the chord — must NOT re-fire.
    detector.on_press(KeyCode.from_char("x"))
    assert fired == [1]


def test_chord_rearms_after_releasing_a_target_key() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_l)
    detector.on_press(Key.alt_l)
    detector.on_press(Key.cmd_l)
    assert fired == [1]
    detector.on_release(Key.ctrl_l)
    detector.on_press(Key.ctrl_l)
    assert fired == [1, 1]


def test_chord_does_not_rearm_when_only_non_target_released() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_l)
    detector.on_press(Key.alt_l)
    detector.on_press(Key.cmd_l)
    detector.on_press(KeyCode.from_char("x"))
    detector.on_release(KeyCode.from_char("x"))
    # All target keys still held — must remain disarmed.
    assert fired == [1]


def test_chord_left_and_right_modifiers_interchangeable() -> None:
    detector, fired = _make_detector()
    detector.on_press(Key.ctrl_r)
    detector.on_press(Key.alt_r)
    detector.on_press(Key.cmd_r)
    assert fired == [1]
```

- [ ] **Step 4: Run tests, verify they fail at collection**

```sh
uv run pytest tests/test_hotkey.py -v
```
Expected: ImportError for `echo.hotkey`.

- [ ] **Step 5: Implement `src/echo/hotkey.py`**

```python
"""Global hotkey chord parsing and detection.

`parse_chord` turns a list of human-readable key names from the config file
into a tuple of "slots", where each slot is a frozenset of pynput keys that
satisfy that slot (modifier names expand to left+right variants).

`ChordDetector` is a pure state machine driven by `on_press`/`on_release`
calls. It fires a single callback on the leading edge of "all slots
satisfied" and re-arms only when at least one target key is released.
"""
from __future__ import annotations

from typing import Callable

from pynput.keyboard import Key, KeyCode

from echo.config import ConfigError


_MODIFIERS: dict[str, list[Key]] = {
    "ctrl": [Key.ctrl_l, Key.ctrl_r],
    "alt": [Key.alt_l, Key.alt_r],
    "cmd": [Key.cmd_l, Key.cmd_r],
    "shift": [Key.shift_l, Key.shift_r],
}

_NAMED: dict[str, Key] = {
    "space": Key.space,
    "enter": Key.enter,
    "tab": Key.tab,
    "esc": Key.esc,
    "escape": Key.esc,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
    "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
    "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
}


Slot = frozenset
ChordSlots = tuple[Slot, ...]


def parse_chord(names: list[str]) -> ChordSlots:
    """Parse a list of key names into a tuple of slots.

    Each slot is a frozenset of pynput Key/KeyCode values that satisfy
    that slot. Modifier slots include both left and right variants.
    """
    if not names:
        raise ConfigError("Hotkey chord cannot be empty")

    slots: list[Slot] = []
    for raw in names:
        name = raw.strip().lower()
        if name in _MODIFIERS:
            slots.append(frozenset(_MODIFIERS[name]))
        elif name in _NAMED:
            slots.append(frozenset({_NAMED[name]}))
        elif len(name) == 1 and name.isprintable():
            slots.append(frozenset({KeyCode.from_char(name)}))
        else:
            raise ConfigError(f"Unknown hotkey key: {raw!r}")
    return tuple(slots)


class ChordDetector:
    """Tracks pressed keys and fires `on_pressed` when the chord is complete.

    Fires exactly once on the transition into "all slots satisfied". Does
    not fire again until at least one target key is released and the chord
    is re-formed.
    """

    def __init__(
        self,
        *,
        slots: ChordSlots,
        on_pressed: Callable[[], None],
    ) -> None:
        self._slots = slots
        self._target_keys: frozenset = frozenset().union(*slots)
        self._on_pressed = on_pressed
        self._pressed: set = set()
        self._armed = True

    def _all_slots_satisfied(self) -> bool:
        return all(bool(slot & self._pressed) for slot in self._slots)

    def on_press(self, key) -> None:
        self._pressed.add(key)
        if self._armed and self._all_slots_satisfied():
            self._armed = False
            self._on_pressed()

    def on_release(self, key) -> None:
        self._pressed.discard(key)
        if key in self._target_keys and not self._all_slots_satisfied():
            self._armed = True
```

NOTE: this module imports `ConfigError` from `echo.config`. That class
already exists from the MVP — no change needed there for this task.

- [ ] **Step 6: Run hotkey tests, verify pass**

```sh
uv run pytest tests/test_hotkey.py -v
```
Expected: 11 passed.

- [ ] **Step 7: Commit**

```sh
git add pyproject.toml uv.lock src/echo/hotkey.py tests/test_hotkey.py
git commit -m "feat(hotkey): chord parsing and detector state machine"
```

---

## Task 3: sounds module — afplay wrapper

**Files:**
- Create: `src/echo/sounds.py`
- Create: `tests/test_sounds.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sounds.py`:
```python
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
```

- [ ] **Step 2: Run tests, verify failure**

```sh
uv run pytest tests/test_sounds.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `src/echo/sounds.py`**

```python
"""Non-blocking sound playback via macOS `afplay`.

`play(path)` spawns afplay in the background. Empty paths and missing files
are no-ops. Errors invoking afplay are caught and logged but never raised —
audio cues must never crash the daemon.

`validate_paths(paths)` is called once at startup. It returns a copy of the
input dict with any missing-file entries replaced by "" and prints a warning
for each.
"""
from __future__ import annotations

import os
import subprocess
import sys


def play(path: str) -> None:
    if not path or not os.path.isfile(path):
        return
    try:
        subprocess.Popen(
            ["afplay", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError) as e:
        sys.stderr.write(f"warning: afplay invocation failed: {e}\n")


def validate_paths(paths: dict[str, str]) -> dict[str, str]:
    validated: dict[str, str] = {}
    for name, p in paths.items():
        if not p:
            validated[name] = ""
            continue
        if os.path.isfile(p):
            validated[name] = p
        else:
            sys.stderr.write(
                f"warning: hotkey sound '{name}' file not found: {p}; cue disabled\n"
            )
            validated[name] = ""
    return validated
```

- [ ] **Step 4: Run tests, verify pass**

```sh
uv run pytest tests/test_sounds.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```sh
git add src/echo/sounds.py tests/test_sounds.py
git commit -m "feat(sounds): non-blocking afplay wrapper with startup validation"
```

---

## Task 4: Config extension — [hotkey] section

**Files:**
- Modify: `src/echo/config.py` (add `HotkeyConfig`, parse `[hotkey]` section)
- Modify: `tests/test_config.py` (add tests)
- Modify: `config/config.example.toml` (add `[hotkey]` and `[hotkey.sounds]`)

- [ ] **Step 1: Add `[hotkey]` to `config/config.example.toml`**

Append to the file:
```toml

[hotkey]
# Modifier-only chord that toggles recording. All listed keys must be pressed
# simultaneously. Supported names: ctrl, alt, cmd, shift, plus any printable
# letter/digit, "space", "f1"-"f12". Modifier names match either side
# (e.g. "ctrl" matches both ctrl_l and ctrl_r).
chord = ["ctrl", "alt", "cmd"]

[hotkey.sounds]
# Paths to sound files (.aiff/.wav). macOS system sounds live in
# /System/Library/Sounds/ (Pop, Tink, Glass, Funk, Bottle, Frog, Hero,
# Morse, Ping, Purr, Sosumi, Submarine). Set to "" to disable a cue.
start = "/System/Library/Sounds/Pop.aiff"
stop = "/System/Library/Sounds/Tink.aiff"
empty = "/System/Library/Sounds/Funk.aiff"
```

- [ ] **Step 2: Write failing config tests**

Append to `tests/test_config.py`:
```python


# ----- HotkeyConfig -----

from echo.config import HotkeyConfig


def _write_config_with_hotkey(tmp_path, hotkey_section: str) -> Path:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[openai]\nmodel = "gpt-4o-transcribe"\n'
        '[transcription]\nvocabulary_prompt = ""\nlanguage = "en"\n'
        '[recording]\nsample_rate = 16000\nchannels = 1\n'
        + hotkey_section
    )
    return cfg_path


def test_hotkey_config_defaults_when_section_missing(tmp_path: Path) -> None:
    cfg_path = _write_config_with_hotkey(tmp_path, "")
    cfg = load_config(cfg_path)
    assert cfg.hotkey.chord == ("ctrl", "alt", "cmd")
    assert cfg.hotkey.sound_start == "/System/Library/Sounds/Pop.aiff"
    assert cfg.hotkey.sound_stop == "/System/Library/Sounds/Tink.aiff"
    assert cfg.hotkey.sound_empty == "/System/Library/Sounds/Funk.aiff"


def test_hotkey_config_parses_custom_section(tmp_path: Path) -> None:
    section = (
        '[hotkey]\nchord = ["ctrl", "shift", "f1"]\n'
        '[hotkey.sounds]\nstart = "/tmp/a"\nstop = "/tmp/b"\nempty = ""\n'
    )
    cfg_path = _write_config_with_hotkey(tmp_path, section)
    cfg = load_config(cfg_path)
    assert cfg.hotkey.chord == ("ctrl", "shift", "f1")
    assert cfg.hotkey.sound_start == "/tmp/a"
    assert cfg.hotkey.sound_stop == "/tmp/b"
    assert cfg.hotkey.sound_empty == ""


def test_hotkey_config_unknown_key_raises(tmp_path: Path) -> None:
    section = '[hotkey]\nchord = ["ctrl", "wat"]\n'
    cfg_path = _write_config_with_hotkey(tmp_path, section)
    with pytest.raises(ConfigError, match="Unknown hotkey key"):
        load_config(cfg_path)


def test_hotkey_config_empty_chord_raises(tmp_path: Path) -> None:
    section = '[hotkey]\nchord = []\n'
    cfg_path = _write_config_with_hotkey(tmp_path, section)
    with pytest.raises(ConfigError, match="empty"):
        load_config(cfg_path)
```

- [ ] **Step 3: Run tests, verify failure**

```sh
uv run pytest tests/test_config.py -v
```
Expected: failures importing `HotkeyConfig`.

- [ ] **Step 4: Update `src/echo/config.py`**

Replace the file with:
```python
"""Config loading for project-echo.

Loads TOML config from disk, bootstraps from an example file on first run,
and reads the OpenAI API key from the environment.
"""
from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Raised when configuration cannot be loaded or is invalid."""


_DEFAULT_HOTKEY_CHORD: tuple[str, ...] = ("ctrl", "alt", "cmd")
_DEFAULT_SOUND_START = "/System/Library/Sounds/Pop.aiff"
_DEFAULT_SOUND_STOP = "/System/Library/Sounds/Tink.aiff"
_DEFAULT_SOUND_EMPTY = "/System/Library/Sounds/Funk.aiff"


@dataclass(frozen=True)
class HotkeyConfig:
    chord: tuple[str, ...]
    sound_start: str
    sound_stop: str
    sound_empty: str


@dataclass(frozen=True)
class Config:
    model: str
    vocabulary_prompt: str
    language: str
    sample_rate: int
    channels: int
    hotkey: HotkeyConfig

    @staticmethod
    def require_api_key() -> str:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ConfigError(
                "OPENAI_API_KEY environment variable is not set. "
                "Export it before running ec."
            )
        return key


def _parse_hotkey(data: dict) -> HotkeyConfig:
    section = data.get("hotkey", {})
    chord_raw = section.get("chord", list(_DEFAULT_HOTKEY_CHORD))
    if not isinstance(chord_raw, list) or not all(isinstance(k, str) for k in chord_raw):
        raise ConfigError("hotkey.chord must be a list of strings")
    if not chord_raw:
        raise ConfigError("hotkey.chord cannot be empty")

    # Validate each key name now so the user gets an error at config-load time,
    # not later when the daemon tries to start.
    from echo.hotkey import parse_chord
    parse_chord(chord_raw)

    sounds = section.get("sounds", {}) if isinstance(section, dict) else {}
    return HotkeyConfig(
        chord=tuple(chord_raw),
        sound_start=str(sounds.get("start", _DEFAULT_SOUND_START)),
        sound_stop=str(sounds.get("stop", _DEFAULT_SOUND_STOP)),
        sound_empty=str(sounds.get("empty", _DEFAULT_SOUND_EMPTY)),
    )


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
            hotkey=_parse_hotkey(data),
        )
    except KeyError as e:
        raise ConfigError(f"Missing required config key: {e}") from e
```

NOTE: `_parse_hotkey` imports `parse_chord` lazily to avoid a circular
import (`hotkey.py` imports `ConfigError` from this module).

- [ ] **Step 5: Update `tests/test_main.py` `fake_config` fixture**

Adding the required `hotkey` field to `Config` breaks the existing fixture in
`test_main.py`. Update the imports and fixture:

```python
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
            chord=("ctrl", "alt", "cmd"),
            sound_start="",
            sound_stop="",
            sound_empty="",
        ),
    )
```

- [ ] **Step 6: Run tests, verify pass**

```sh
uv run pytest tests/test_config.py tests/test_hotkey.py tests/test_main.py -v
```
Expected: all tests in `test_config.py` (10 total: 6 original + 4 new), all in `test_hotkey.py`, all in `test_main.py`.

- [ ] **Step 7: Run the full suite**

```sh
uv run pytest -q
```
Expected: every test passes (config, clipboard, hotkey, sounds, transcriber, ui, main = ~30 tests).

- [ ] **Step 8: Commit**

```sh
git add src/echo/config.py tests/test_config.py tests/test_main.py config/config.example.toml
git commit -m "feat(config): parse [hotkey] section with chord validation"
```

---

## Task 5: Daemon module

**Files:**
- Create: `src/echo/daemon.py`
- Create: `tests/test_daemon.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_daemon.py`:
```python
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
            chord=("ctrl", "alt", "cmd"),
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
```

- [ ] **Step 2: Run tests, verify failure**

```sh
uv run pytest tests/test_daemon.py -v
```
Expected: ImportError for `echo.daemon`.

- [ ] **Step 3: Implement `src/echo/daemon.py`**

```python
"""Long-running daemon: listens for a global hotkey chord and runs the
transcribe → clipboard pipeline on toggle.

The chord callback runs on the pynput listener thread. A non-blocking
`threading.Lock` guards the state field so events arriving during
PROCESSING are dropped at the door.
"""
from __future__ import annotations

import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal

from echo import sounds as default_sounds
from echo.clipboard import ClipboardError, copy_to_clipboard as default_copy
from echo.config import Config
from echo.hotkey import ChordDetector, parse_chord
from echo.recorder import RecorderError, RecordingSession
from echo.transcriber import TranscriberError, transcribe as default_transcribe
from echo.ui import format_error, format_transcription


State = Literal["idle", "recording", "processing"]


class Daemon:
    def __init__(
        self,
        *,
        config: Config,
        openai_client: Any,
        session_factory: Callable[[], RecordingSession] | None = None,
        transcribe_fn: Callable[..., str] = default_transcribe,
        copy_fn: Callable[[str], None] = default_copy,
        sounds_module=default_sounds,
    ) -> None:
        self._config = config
        self._client = openai_client
        self._session_factory = session_factory or (
            lambda: RecordingSession(
                sample_rate=config.sample_rate, channels=config.channels
            )
        )
        self._transcribe = transcribe_fn
        self._copy = copy_fn
        self._sounds = sounds_module

        self._state: State = "idle"
        self._lock = threading.Lock()
        self._session: RecordingSession | None = None
        self._stop_event = threading.Event()

    @property
    def state(self) -> State:
        return self._state

    def _make_wav_path(self) -> Path:
        return Path(f"/tmp/echo-{int(time.time() * 1000)}.wav")

    # ----- chord callback -----

    def on_chord(self) -> None:
        if not self._lock.acquire(blocking=False):
            return  # another callback is mid-processing
        try:
            current = self._state
            if current == "idle":
                self._state = "recording"
            elif current == "recording":
                self._state = "processing"
            else:  # processing
                return
        finally:
            self._lock.release()

        try:
            if current == "idle":
                self._handle_start()
            elif current == "recording":
                self._handle_stop()
        except Exception as e:
            sys.stderr.write(format_error(f"chord callback failed: {e}") + "\n")
            self._sounds.play(self._config.hotkey.sound_empty)
            with self._lock:
                self._state = "idle"
                self._session = None

    def _handle_start(self) -> None:
        self._sounds.play(self._config.hotkey.sound_start)
        try:
            session = self._session_factory()
            session.start()
        except RecorderError as e:
            sys.stderr.write(format_error(str(e)) + "\n")
            self._sounds.play(self._config.hotkey.sound_empty)
            with self._lock:
                self._state = "idle"
                self._session = None
            return
        self._session = session

    def _handle_stop(self) -> None:
        wav_path = self._make_wav_path()
        session = self._session
        self._session = None
        try:
            if session is None:
                # Defensive: should never happen given the state machine.
                self._sounds.play(self._config.hotkey.sound_empty)
                return

            try:
                recording = session.stop(wav_path)
            except RecorderError as e:
                sys.stderr.write(format_error(str(e)) + "\n")
                self._sounds.play(self._config.hotkey.sound_empty)
                return

            self._sounds.play(self._config.hotkey.sound_stop)

            try:
                text = self._transcribe(
                    client=self._client,
                    wav_path=recording.wav_path,
                    model=self._config.model,
                    vocabulary_prompt=self._config.vocabulary_prompt,
                    language=self._config.language,
                )
            except TranscriberError as e:
                sys.stderr.write(format_error(str(e)) + "\n")
                sys.stderr.write(f"  WAV kept at: {wav_path}\n")
                self._sounds.play(self._config.hotkey.sound_empty)
                return

            if not text:
                sys.stderr.write(
                    format_error("transcription empty; clipboard unchanged") + "\n"
                )
                self._sounds.play(self._config.hotkey.sound_empty)
                wav_path.unlink(missing_ok=True)
                return

            sys.stderr.write(format_transcription(text) + "\n")
            try:
                self._copy(text)
            except ClipboardError as e:
                sys.stderr.write(format_error(str(e)) + "\n")
                sys.stderr.write(f"  WAV kept at: {wav_path}\n")
                self._sounds.play(self._config.hotkey.sound_empty)
                return

            wav_path.unlink(missing_ok=True)
        finally:
            with self._lock:
                self._state = "idle"

    # ----- lifecycle -----

    def request_stop(self, *_: Any) -> None:
        self._stop_event.set()

    def run(self) -> int:
        # Validate sound files at startup; replace missing with "" + warn.
        validated = self._sounds.validate_paths(
            {
                "start": self._config.hotkey.sound_start,
                "stop": self._config.hotkey.sound_stop,
                "empty": self._config.hotkey.sound_empty,
            }
        )
        # Frozen dataclass — rebuild via object.__setattr__ on a copy is fine
        # but cleaner: replace the hotkey field via dataclasses.replace.
        from dataclasses import replace
        from echo.config import HotkeyConfig

        new_hotkey = HotkeyConfig(
            chord=self._config.hotkey.chord,
            sound_start=validated["start"],
            sound_stop=validated["stop"],
            sound_empty=validated["empty"],
        )
        self._config = replace(self._config, hotkey=new_hotkey)

        # Build the chord detector.
        slots = parse_chord(list(self._config.hotkey.chord))
        detector = ChordDetector(slots=slots, on_pressed=self.on_chord)

        # Lazy-import pynput so unit tests don't need it loaded into the
        # daemon module by default — and so import errors surface here with
        # context, not at module-load time.
        from pynput import keyboard as pyn_keyboard

        listener = pyn_keyboard.Listener(
            on_press=detector.on_press,
            on_release=detector.on_release,
        )
        try:
            listener.start()
        except Exception as e:
            sys.stderr.write(
                format_error(
                    f"Failed to start global hotkey listener: {e}. "
                    "Grant Accessibility access to your terminal in "
                    "System Settings → Privacy & Security → Accessibility."
                )
                + "\n"
            )
            return 1

        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        chord_label = "+".join(self._config.hotkey.chord)
        sys.stderr.write(
            f"✓ Listening for {chord_label} chord. Press Ctrl-C to quit.\n"
        )

        try:
            self._stop_event.wait()
        finally:
            listener.stop()
            if self._session is not None:
                try:
                    self._session.stop(self._make_wav_path())
                except RecorderError:
                    pass
                self._session = None

        sys.stderr.write("daemon stopped\n")
        return 0
```

- [ ] **Step 4: Run daemon tests, verify pass**

```sh
uv run pytest tests/test_daemon.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Run the full suite**

```sh
uv run pytest -q
```
Expected: all tests still pass.

- [ ] **Step 6: Commit**

```sh
git add src/echo/daemon.py tests/test_daemon.py
git commit -m "feat(daemon): three-state machine for hotkey-driven recording"
```

---

## Task 6: __main__.py — subcommand dispatch + PID file

**Files:**
- Modify: `src/echo/__main__.py` (add subcommand dispatch, PID file logic, `ec listen` and `ec stop`)
- Modify: `tests/test_main.py` (add subcommand dispatch + PID file tests)

- [ ] **Step 1: Write failing tests for subcommands and PID logic**

Append to `tests/test_main.py`:
```python


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
    # First poll: process still alive (kill(pid, 0) succeeds). Second poll: ProcessLookupError.
    kill.side_effect = [None, None, ProcessLookupError]
    exit_code = main_mod.main(argv=["stop"])
    assert exit_code == 0
    # SIGTERM was sent first, then poll(s).
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
    # The PID file should now contain our (test runner's) PID.
    assert pid_file.read_text().strip() == str(os.getpid())
    # Cleanup: release runs at end and removes the file.
    assert not pid_file.exists()
```

Add `import os` at the top of `tests/test_main.py` if not already present.

- [ ] **Step 2: Run tests, verify failure**

```sh
uv run pytest tests/test_main.py -v
```
Expected: failures because `Daemon`, `PID_FILE`, `_acquire_pid_file`, `_release_pid_file`, and the `listen`/`stop` subcommands don't exist yet.

- [ ] **Step 3: Rewrite `src/echo/__main__.py` to support subcommands**

```python
"""Entry point for the `ec` command — supports one-shot, daemon, and stop modes."""
from __future__ import annotations

import argparse
import os
import select
import signal
import sys
import termios
import time
import tty
from pathlib import Path

from openai import OpenAI

from echo.clipboard import ClipboardError, copy_to_clipboard
from echo.config import Config, ConfigError, load_config
from echo.daemon import Daemon
from echo.recorder import RecorderError, RecordingSession
from echo.transcriber import TranscriberError, transcribe
from echo.ui import format_error, format_recording_line, format_transcription


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "config.toml"
EXAMPLE_PATH = REPO_ROOT / "config" / "config.example.toml"

# Module-level so tests can monkeypatch.
PID_FILE = Path("/tmp/echo-daemon.pid")


# ===== argparse =====

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ec",
        description="Record audio, transcribe via OpenAI, copy to clipboard.",
    )
    sub = parser.add_subparsers(dest="command")

    # Default (no subcommand): one-shot recording. Flags live on the root parser.
    parser.add_argument("--clean", action="store_true",
                        help="(reserved) post-process the transcription via an LLM cleanup pass")
    parser.add_argument("--verbose", action="store_true",
                        help="print per-stage timing breakdown to stderr")

    listen_p = sub.add_parser("listen", help="Run the global hotkey daemon")
    listen_p.add_argument("--verbose", action="store_true",
                          help="print per-recording timing breakdown")
    listen_p.add_argument("--force", action="store_true",
                          help="overwrite an existing PID file (kills the previous claim)")

    sub.add_parser("stop", help="Stop a running daemon")

    return parser


# ===== PID file helpers =====

def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _acquire_pid_file(force: bool) -> None:
    if PID_FILE.exists():
        try:
            existing = int(PID_FILE.read_text().strip())
        except ValueError:
            existing = -1
        if existing > 0 and _is_alive(existing):
            if not force:
                raise ConfigError(
                    f"daemon already running (PID {existing}). "
                    "Run 'ec stop' first, or pass --force to override."
                )
            sys.stderr.write(
                f"warning: --force specified; overwriting PID file for live PID {existing}\n"
            )
        else:
            sys.stderr.write(
                f"warning: stale PID file at {PID_FILE} (PID {existing} not alive); cleaning up\n"
            )
    PID_FILE.write_text(str(os.getpid()))


def _release_pid_file() -> None:
    try:
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
            except ValueError:
                pid = -1
            if pid == os.getpid():
                PID_FILE.unlink()
    except OSError:
        pass


# ===== one-shot recording (existing behavior) =====

def _print_status(line: str) -> None:
    sys.stderr.write(f"\r{line}")
    sys.stderr.flush()


def _wait_for_space(session: RecordingSession) -> None:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    start = time.monotonic()
    last_tick = -1
    try:
        tty.setcbreak(fd)
        while session.is_recording:
            elapsed = int(time.monotonic() - start)
            if elapsed != last_tick:
                _print_status(format_recording_line(elapsed))
                last_tick = elapsed
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch = sys.stdin.read(1)
                if ch == " ":
                    return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _run_oneshot(args: argparse.Namespace) -> int:
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
    session = RecordingSession(sample_rate=cfg.sample_rate, channels=cfg.channels)

    try:
        t0 = time.monotonic()
        try:
            session.start()
        except RecorderError as e:
            sys.stderr.write(format_error(str(e)) + "\n")
            return 1
        _wait_for_space(session)
        try:
            recording = session.stop(wav_path)
        except RecorderError as e:
            sys.stderr.write("\n" + format_error(str(e)) + "\n")
            return 1
        sys.stderr.write("\n")
        timings["record"] = time.monotonic() - t0
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        if session.is_recording:
            try:
                session.stop(wav_path)
            except RecorderError:
                pass
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
        return 1

    wav_path.unlink(missing_ok=True)

    if args.verbose:
        sys.stderr.write(
            f"  timings: record={timings.get('record', 0):.2f}s "
            f"transcribe={timings.get('transcribe', 0):.2f}s "
            f"recording_duration={recording.duration_seconds:.2f}s\n"
        )

    return 0


# ===== ec listen =====

def _run_listen(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(CONFIG_PATH, example_path=EXAMPLE_PATH)
        api_key = Config.require_api_key()
    except ConfigError as e:
        sys.stderr.write(format_error(str(e)) + "\n")
        return 1

    try:
        _acquire_pid_file(force=args.force)
    except ConfigError as e:
        sys.stderr.write(format_error(str(e)) + "\n")
        return 1

    try:
        client = OpenAI(api_key=api_key)
        daemon = Daemon(config=cfg, openai_client=client)
        return daemon.run()
    finally:
        _release_pid_file()


# ===== ec stop =====

def _run_stop() -> int:
    if not PID_FILE.exists():
        sys.stderr.write("no daemon running\n")
        return 0
    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        sys.stderr.write("warning: PID file is corrupt; removing\n")
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return 0

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        sys.stderr.write("warning: PID file pointed to a dead process; cleaning up\n")
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return 0

    # Poll for up to 2 seconds.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            try:
                PID_FILE.unlink()
            except OSError:
                pass
            sys.stderr.write("daemon stopped\n")
            return 0
        time.sleep(0.1)

    # Still alive — escalate.
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        PID_FILE.unlink()
    except OSError:
        pass
    sys.stderr.write("daemon stopped (SIGKILL)\n")
    return 0


# ===== entry point =====

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "listen":
        return _run_listen(args)
    if args.command == "stop":
        return _run_stop()
    return _run_oneshot(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

NOTE on the test for `test_main_stop_sends_sigterm_when_alive`: the test
expects `os.kill` to be called with `signal.SIGTERM` (numeric value 15),
then `os.kill(pid, 0)` to poll. The test side_effect list models: SIGTERM
sent → first poll alive → second poll dead. Adjust the test if the polling
loop calls `os.kill` differently than expected — the goal is to verify that
SIGTERM is the first call.

- [ ] **Step 4: Run tests, verify pass**

```sh
uv run pytest tests/test_main.py -v
```
Expected: all tests pass (the original 4 + 5 new = 9).

- [ ] **Step 5: Run the full suite**

```sh
uv run pytest -q
```
Expected: all tests still pass.

- [ ] **Step 6: Commit**

```sh
git add src/echo/__main__.py tests/test_main.py
git commit -m "feat(cli): subcommand dispatch with ec listen and ec stop"
```

---

## Task 7: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update `README.md`**

Open the existing README and make these changes:

1. **Setup section** — replace its body with:

```markdown
## Setup

```sh
# system deps
brew install uv portaudio

# project deps
uv sync

# config (auto-bootstrapped on first run, or copy manually)
cp config/config.example.toml config/config.toml

# api key
export OPENAI_API_KEY=sk-...
```

Edit `config/config.toml` to tune the vocabulary prompt with your own list of
project names, libraries, and jargon. The file is gitignored.

The first time you run `ec`, macOS will ask for microphone permission for
your terminal. Grant it via **System Settings → Privacy & Security →
Microphone**.

For the global hotkey daemon (`ec listen`), you also need to grant
**Accessibility** permission to your terminal. macOS will prompt the first
time. Grant it via **System Settings → Privacy & Security → Accessibility**.
```

2. **Usage section** — replace with:

```markdown
## Usage

### One-shot (terminal)

```sh
uv run ec
```

1. `● Recording... (press space to stop) 0:00` — the timer ticks
2. Speak
3. Press **space** to stop
4. `✓ Transcribing...`
5. `> your transcribed text`
6. `✓ Copied to clipboard.`

### Background daemon (global hotkey)

Start the daemon in any terminal — leave it running:

```sh
uv run ec listen
```

Now press **⌃⌥⌘** (control + option + command) anywhere on the system to
toggle a recording. You'll hear a beep on start and a different beep on stop.
The transcription lands on your clipboard ~1s after you press the chord
again. Configure the chord in `config/config.toml` under `[hotkey]`.

To stop the daemon from any other terminal:

```sh
uv run ec stop
```

To restart: `uv run ec stop && uv run ec listen`.

### Flags

| Command       | Flag        | Effect                                                            |
|---------------|-------------|-------------------------------------------------------------------|
| `ec`          | `--verbose` | Print per-stage timings to stderr                                 |
| `ec`          | `--clean`   | Reserved for future LLM cleanup pass; currently exits with a stub |
| `ec listen`   | `--verbose` | Print per-recording timings                                       |
| `ec listen`   | `--force`   | Overwrite an existing PID file                                    |
```

3. **Roadmap section** — update the "Hotkey daemon" subsection by checking off the items now done. Replace the section with:

```markdown
### Hotkey daemon — complete

- [x] Long-running daemon (`ec listen`) holding the mic stream open between presses
- [x] Configurable global hotkey chord (default `⌃⌥⌘`) defined in `config.toml`
- [x] Configurable start/stop/empty sound cues
- [x] PID file lifecycle and `ec stop` for clean shutdown
- [x] Survives transient failures (mic permission, API errors, missing sound files)
- [ ] LaunchAgent for auto-start on login
- [ ] Menu bar indicator for recording state
```

- [ ] **Step 2: Verify the README renders sensibly**

Skim the file and check for: broken markdown, dangling sections, references
to removed items. No tool runs in this step.

- [ ] **Step 3: Commit**

```sh
git add README.md
git commit -m "docs: document ec listen, ec stop, and hotkey config"
```

---

## Task 8: Manual smoke test

This is the only verification of the recorder, real pynput Listener, real
afplay, and real OpenAI API together. No automated tests cover any of these.

- [ ] **Step 1: Confirm prerequisites**

```sh
brew list portaudio || brew install portaudio
echo "$OPENAI_API_KEY" | head -c 10  # should print sk-... (first 10 chars)
ls config/config.toml || cp config/config.example.toml config/config.toml
```

- [ ] **Step 2: Verify one-shot still works after the recorder refactor**

```sh
cd /Users/rafaelmancini/Projects/personal/project-echo
uv run ec
```

Expected behavior is unchanged from the MVP: timer ticks, press space, transcription appears and lands on clipboard. If this regresses, stop and report — the recorder refactor in Task 1 introduced a bug.

- [ ] **Step 3: Start the daemon**

```sh
uv run ec listen
```

Expected: `✓ Listening for ctrl+alt+cmd chord. Press Ctrl-C to quit.`

If macOS prompts for Accessibility permission, grant it (System Settings → Privacy & Security → Accessibility), then re-run the command. The first run after granting may need a retry.

- [ ] **Step 4: Trigger a recording from outside the terminal**

Switch focus to any other app (Notes, Slack, browser). Press **⌃⌥⌘**. Hear the start beep. Speak a short phrase. Press **⌃⌥⌘** again. Hear the stop beep. Wait ~1s. Paste with **⌘V** — the transcription should appear.

- [ ] **Step 5: Verify the "too short" path**

Press the chord, immediately press it again (under 0.5s). Hear the empty beep. Clipboard should be unchanged. The daemon's stderr should show the "too short" message.

- [ ] **Step 6: Verify the "vocab echo" path (silence)**

Press the chord, stay silent for ~2 seconds, press the chord again. The transcription should be empty (vocab-echo guard kicks in). Hear the empty beep. Clipboard unchanged.

- [ ] **Step 7: Verify the "chord during processing is dropped" behavior**

Press the chord, speak briefly, press the chord again. While the daemon is mid-transcription (~1s window), press the chord rapidly several times. After the original transcription lands, the rapid presses should NOT have started a new recording.

- [ ] **Step 8: Stop and restart cleanly**

In a second terminal:
```sh
uv run ec stop
```

Expected: `daemon stopped`. The first terminal's daemon process should exit.

Then `uv run ec listen` again — fresh start, no PID file conflicts.

- [ ] **Step 9: Verify stale PID file cleanup**

Start the daemon. In another terminal, get its PID:
```sh
cat /tmp/echo-daemon.pid
```

Then `kill -9 <pid>`. The PID file is now stale. Run `uv run ec listen` again — it should print a warning about a stale PID file, clean it up, and start normally.

- [ ] **Step 10: Verify missing sound file warning**

Edit `config/config.toml` and set `[hotkey.sounds] start = "/nonexistent.aiff"`. Restart the daemon. Expect a warning at startup, daemon still works, no start beep on the next chord.

- [ ] **Step 11: Verify invalid chord rejection**

Edit `config/config.toml` and set `chord = ["wat"]`. Run `uv run ec listen`. Expect a `ConfigError: Unknown hotkey key: 'wat'` and exit code 1.

Restore the config when done.

- [ ] **Step 12: Sanity check `ec stop` edge cases**

- `uv run ec stop` with no daemon running → "no daemon running", exit 0
- `uv run ec stop` after killing the daemon with `kill -9` → "PID file pointed to a dead process; cleaning up", exit 0

- [ ] **Step 13: Report findings**

If anything misbehaves (latency, accuracy, accessibility prompts that won't take, race conditions), capture the output and discuss. Do NOT fix in-flight — the milestone scope is locked. File issues for follow-ups.
