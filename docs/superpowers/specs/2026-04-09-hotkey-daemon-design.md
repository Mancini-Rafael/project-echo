# Hotkey Daemon — Design

**Date:** 2026-04-09
**Status:** Approved (pending user spec review)
**Author:** Rafael Mancini
**Builds on:** `2026-04-09-project-echo-design.md` (MVP)

## Summary

Add a long-running daemon mode (`ec listen`) that listens for a configurable
global keyboard chord, toggles audio recording on/off, and runs the existing
transcribe → clipboard pipeline. Goal: trigger dictation from anywhere on the
system without touching a terminal.

No menu bar, no notifications, no GUI. Audio cues are the only feedback. The
daemon is started manually (no LaunchAgent yet) and managed via a `ec stop`
subcommand.

## Goals

- Trigger a recording from any application without switching focus to a terminal.
- Toggle on/off with a single chord press; no key-holding fatigue.
- Pure-modifier default chord so the trigger never inserts characters into a
  focused text field.
- Reuse the existing config, transcriber, and clipboard modules unchanged
  where possible. Refactor the recorder so the same capture code serves both
  the one-shot CLI and the daemon.
- The daemon must survive transient failures (API errors, missing mic
  permission, missing sound files). One bad recording must never kill it.
- Configurable everything (chord keys, sound files), so the user can tune
  the experience without recompiling.

## Non-Goals (Out of Scope for This Milestone)

- Menu bar / app bar indicator
- macOS notification banners
- LaunchAgent / auto-start on login
- `ec status` and `ec restart` commands
- Multiple concurrent recordings or queueing
- A second hotkey to kill the daemon (use `ec stop`)
- Per-app or per-context vocabulary prompts
- Pluggable transcription backend (separate roadmap milestone)
- Hot-reload of config without restart
- Session history / past transcriptions
- GUI for hotkey configuration
- Cross-platform support (still macOS only)
- Telemetry

## User Flow

```
$ ec listen
✓ Listening for ⌃⌥⌘ chord. Press Ctrl-C to quit.

[user, focused in Slack, presses ⌃⌥⌘]
[start beep plays — Pop.aiff]
[user dictates: "let me refactor the dashboard hook"]
[user presses ⌃⌥⌘ again]
[stop beep plays — Tink.aiff]
[~1s later, transcription is on the clipboard]
[user pastes into Slack with ⌘V]

[transcription is also printed to the daemon's stderr for diagnostics]
> let me refactor the dashboard hook
```

To stop the daemon:

```
$ ec stop
daemon stopped
```

## Architecture

A new subcommand `ec listen` starts a long-running daemon process. The daemon
owns:

- A `pynput.keyboard.Listener` running in its own thread, monitoring all
  keypresses globally
- A `ChordDetector` that tracks modifier state and fires a single
  `on_chord_pressed` callback when the configured chord transitions into the
  fully-pressed state
- A `RecordingSession` (refactored from the existing recorder) that captures
  audio into an in-memory buffer between explicit `start()` and `stop()` calls
- A persistent OpenAI client (created once at daemon startup, reused across
  recordings — no per-recording init cost)
- A three-state machine: `IDLE`, `RECORDING`, `PROCESSING`. `PROCESSING`
  exists to swallow chord events that arrive while the daemon is mid-transcribe,
  so the user can't accidentally start a new recording in that window.

### Daemon Event Loop

```
ec listen
 │
 ├─ load config
 ├─ Config.require_api_key()  → fail fast if missing
 ├─ create OpenAI client (once)
 ├─ check sound files exist; warn and disable any that don't
 ├─ write PID file at /tmp/echo-daemon.pid (refuse if exists; clean stale)
 ├─ start pynput Listener thread
 ├─ print "✓ Listening for <chord>. Press Ctrl-C to quit."
 │
 └─ chord callback (runs on the pynput listener thread):
     │
     ├─ acquire state lock (non-blocking try_lock — see Concurrency Model)
     │     └─ if NOT acquired: drop event and return  (PROCESSING in flight)
     │
     ├─ chord pressed AND state == IDLE:
     │     ├─ state = RECORDING
     │     ├─ release state lock
     │     ├─ play start sound (non-blocking)
     │     └─ session.start()       # mic open in background
     │
     ├─ chord pressed AND state == RECORDING:
     │     ├─ state = PROCESSING        # blocks any further chord events
     │     ├─ release state lock
     │     ├─ result = session.stop(/tmp/echo-<ts>.wav)
     │     ├─ play stop sound (non-blocking)
     │     ├─ if RecorderError "too short": play empty sound, state = IDLE
     │     ├─ text = transcribe(...)             # ~1s
     │     ├─ if text non-empty:
     │     │     ├─ copy_to_clipboard(text)
     │     │     ├─ print "> {text}" to stderr
     │     │     └─ delete WAV
     │     ├─ else:
     │     │     ├─ play empty sound
     │     │     └─ delete WAV
     │     └─ state = IDLE
     │
     ├─ chord pressed AND state == PROCESSING:
     │     └─ unreachable: the try_lock above already dropped the event
     │
     ├─ exception in chord callback:
     │     ├─ caught at top of callback
     │     ├─ logged to stderr
     │     ├─ play empty sound
     │     ├─ state = IDLE
     │     └─ daemon stays alive
     │
     └─ SIGTERM / SIGINT (Ctrl-C):
           ├─ stop pynput listener
           ├─ if recording active: session.stop() and discard
           ├─ remove PID file
           └─ exit 0
```

### Concurrency Model

- **Main thread:** waits for SIGTERM/SIGINT after starting the listener.
  Performs no per-recording work itself.
- **pynput listener thread:** receives raw key events and forwards them to
  the `ChordDetector`. When a full chord is detected, the detector invokes
  the daemon's chord callback **on this same listener thread**. The chord
  callback does all the work — start/stop recording, transcribe, clipboard.
- **sounddevice callback thread:** managed internally by the library; appends
  audio chunks to a buffer protected by a lock inside `RecordingSession`.

**Why a non-blocking try_lock guards the state field:**

pynput delivers chord events sequentially on its listener thread, so two
chord callbacks won't run literally in parallel. But because the chord
callback can take ~1 second (transcription), pynput may *queue* additional
chord events that arrive while the callback is busy. When the busy callback
returns, pynput would immediately fire the queued event — potentially starting
a new recording right after we finished one, which the user did not intend.

To prevent this, the chord callback acquires `state_lock` with `try_lock()`
(non-blocking) at entry. If it can't acquire — meaning another callback is
already mid-processing — it drops the event and returns immediately. The
lock is held only long enough to read and update the state field; the heavy
work (transcribe, clipboard) runs after the lock is released, with the
`PROCESSING` state field acting as the "busy" guard for any *future*
callbacks. Combined with the try_lock, queued events that arrive during
`PROCESSING` are dropped at the door.

### File Layout

```
src/echo/
├── __main__.py         # MODIFIED: subcommand dispatch (ec | ec listen | ec stop)
├── config.py           # MODIFIED: parse [hotkey] section + chord validation
├── recorder.py         # MODIFIED: RecordingSession class; record_until_space removed
├── daemon.py           # NEW: hotkey listener + state machine
├── hotkey.py           # NEW: pynput chord detection (parse + ChordDetector)
├── sounds.py           # NEW: afplay wrapper
├── transcriber.py      # unchanged
├── clipboard.py        # unchanged
└── ui.py               # unchanged

tests/
├── test_config.py      # MODIFIED: tests for [hotkey] parsing + validation
├── test_hotkey.py      # NEW
├── test_sounds.py      # NEW
├── test_daemon.py      # NEW
├── test_main.py        # MODIFIED: subcommand dispatch + PID file logic
└── (recorder still has no tests)
```

## Module Responsibilities

### `hotkey.py`

Pure logic, no I/O. Two public surfaces:

- **`parse_chord(names: list[str]) -> frozenset[Key]`** — turns
  `["ctrl", "alt", "cmd"]` into a frozenset of `pynput.keyboard.Key`
  constants. Raises `ConfigError("Unknown hotkey key: 'foo'")` for unknown
  names. Supported names: `ctrl`, `alt`, `cmd`, `shift`, plus printable
  letters/digits, `space`, `f1`–`f12`. Modifier names map to the *generic*
  modifier (e.g. `ctrl` matches both `ctrl_l` and `ctrl_r`).
- **`ChordDetector(target: frozenset[Key], on_pressed: Callable[[], None])`** —
  state container. Public methods `on_press(key)` and `on_release(key)`. Maintains
  the set of currently-held keys. Fires `on_pressed()` exactly once when the
  held set transitions from "not a superset of target" to "a superset of target".
  Does NOT fire while held; only on the leading edge. Tracks an `armed` flag
  that resets when any target key is released, so a second press fires again.

### `sounds.py`

Tiny wrapper. One public function:

- **`play(path: str) -> None`** — if `path` is empty or the file does not
  exist, return silently (no warning here — startup already warned). Otherwise
  spawns `subprocess.Popen(["afplay", path])` without waiting. Errors from
  Popen are caught and logged to stderr; sound failures must never kill the
  daemon.

Plus a startup helper:

- **`validate_paths(paths: dict[str, str]) -> dict[str, str]`** — given a
  dict of named paths, returns a copy with any missing-file paths replaced
  by `""` and prints a warning for each.

### `daemon.py`

Orchestrates the event loop. The public surface is one class:

- **`Daemon`** — constructed with a `Config`, an OpenAI client, and optional
  injected dependencies (`ChordDetector`, `RecordingSession` factory,
  `transcribe`, `copy_to_clipboard`, `sounds.play`) for testability. Defaults
  to the real implementations.
- **`Daemon.run() -> int`** — installs signal handlers, starts the pynput
  listener, blocks until SIGTERM/SIGINT, returns an exit code.
- Internal state: `state: Literal["idle", "recording", "processing"]`,
  current `RecordingSession`, `threading.Lock` guarding the state field.
  The chord callback acquires the lock with a non-blocking `acquire(blocking=False)`
  and drops the event if it can't.

The daemon imports `pynput` lazily inside `run()` so unit tests of the state
machine don't need pynput installed (and so import errors surface with a
clear message at runtime, not at import).

### `recorder.py`

Refactored. The current `record_until_space()` function and its termios/select
spacebar loop are removed. New API:

```python
@dataclass
class RecordingResult:
    wav_path: Path
    duration_seconds: float

class RecorderError(Exception): ...

class RecordingSession:
    def __init__(
        self, *, sample_rate: int, channels: int, min_duration: float = 0.5
    ): ...
    def start(self) -> None: ...
    def stop(self, output_path: Path) -> RecordingResult: ...
    @property
    def is_recording(self) -> bool: ...
```

`start()` opens the `sounddevice.InputStream` and begins capturing into a
buffer guarded by an internal lock. `stop()` halts the stream, writes the
buffer to `output_path` as a 16-bit PCM WAV, and returns a `RecordingResult`.
If the elapsed duration is below `min_duration`, `stop()` raises
`RecorderError("Recording too short ...")` and writes nothing.

Both methods raise `RecorderError` on hardware/permission failures with the
same actionable message about granting Microphone access in System Settings.

The one-shot `ec` path in `__main__.py` is rewritten to use this class. A new
small private helper `_wait_for_space()` in `__main__.py` handles the
termios/select spacebar loop and is the *only* code that touches terminal raw
mode.

### `__main__.py`

Subcommand dispatch via `argparse` subparsers:

```
ec               # one-shot recording (existing behavior)
ec listen        # start the daemon
ec stop          # stop a running daemon
ec --help
```

Existing top-level flags `--clean` and `--verbose` continue to work for the
one-shot path. `ec listen` accepts `--verbose` and `--force`. `ec stop`
accepts no flags.

The PID file lives at `/tmp/echo-daemon.pid`.

## Configuration

`config/config.example.toml` gains a `[hotkey]` section:

```toml
[openai]
model = "gpt-4o-transcribe"

[transcription]
vocabulary_prompt = """..."""
language = "en"

[recording]
sample_rate = 16000
channels = 1

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

### Config dataclass changes

```python
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
```

### Validation

- `hotkey.chord` must be a non-empty list of strings.
- Each string must parse via `hotkey.parse_chord()`; unknown name → `ConfigError`.
- Sound paths are NOT validated at config-load time. They are checked when
  the daemon starts; missing files become `""` with a printed warning.
- The `[hotkey]` section is **optional**. If absent, defaults are:
  `chord = ["ctrl", "alt", "cmd"]`, sound paths set to the macOS system
  sounds shown above. Existing post-MVP `config.toml` files continue to work
  unchanged.

## Daemon Lifecycle: PID File

The daemon writes its PID to `/tmp/echo-daemon.pid` on startup and removes it
on graceful shutdown.

### `ec listen` startup

1. If PID file does not exist → write our PID, proceed.
2. If PID file exists and the named process is alive →
   refuse with `"daemon already running (PID 12345). Run 'ec stop' first, or pass --force to override."`
   and exit 1.
3. If PID file exists but the named process is gone (stale) →
   print a warning, remove the file, write our PID, proceed.
4. With `--force` → ignore any existing PID file and overwrite it.

### `ec stop`

1. If PID file does not exist → print `"no daemon running"` and exit 0.
2. Read the PID. Send SIGTERM.
3. Poll for up to 2 seconds, in 0.1s increments, for the process to exit.
4. If still alive after 2s → send SIGKILL, remove the PID file manually.
5. If the process was already gone → remove the stale file.
6. Print `"daemon stopped"` and exit 0.

### Graceful shutdown inside the daemon

The daemon installs handlers for SIGINT and SIGTERM. Both call the same
shutdown routine: stop pynput listener, stop active recording (discard),
remove PID file, exit 0.

## Error Handling

| Failure                                       | Handling                                                                                                                                              |
|-----------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| `OPENAI_API_KEY` missing                      | Refuse to start, exit 1 with clear error before opening the listener.                                                                                 |
| Accessibility permission not granted          | pynput listener fails on `start()`. Catch, print actionable msg pointing at System Settings → Privacy & Security → Accessibility, exit 1.             |
| Mic permission denied                         | First `RecordingSession.start()` fails. Print actionable msg, do NOT crash. State returns to IDLE; daemon waits for next chord.                       |
| Configured sound file missing (startup)       | Print warning, treat that cue as disabled (`""`). Daemon proceeds.                                                                                    |
| Recording shorter than 0.5s                   | Discard, play empty sound, return to IDLE.                                                                                                            |
| OpenAI API error during transcription         | Print error to stderr, play empty sound, KEEP the temp WAV, print its path. Return to IDLE.                                                           |
| API returns empty text (incl. vocab echo)     | Play empty sound, do NOT touch clipboard, print "transcription empty" to stderr, delete WAV, return to IDLE.                                          |
| `pbcopy` failure                              | Print transcription to stderr (so user can copy manually), play empty sound, KEEP the WAV, return to IDLE.                                            |
| Chord pressed during transcription            | Ignored. State machine drops the event.                                                                                                               |
| Unhandled exception in chord callback         | Caught at the top of the callback, logged to stderr, play empty sound, state forced to IDLE, daemon stays alive.                                      |
| `ec listen` started while daemon already runs | Refuse, print PID + suggested fix, exit 1. `--force` overrides.                                                                                       |
| Stale PID file                                | Detect on `ec listen` startup or on `ec stop`. Warn, clean up, proceed.                                                                               |
| SIGINT / SIGTERM                              | Clean shutdown: stop listener, stop active recording (discard), remove PID file, exit 0.                                                              |

## Testing Strategy

| Module                       | Approach                                                                                                                                                                                                                                                                                                              |
|------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `config.py` (extended)       | Real unit tests for `[hotkey]` parsing, defaults when section is absent, unknown chord key → `ConfigError`, sound paths preserved verbatim.                                                                                                                                                                            |
| `hotkey.py` (`parse_chord`)  | Happy path, unknown name, empty list, modifier-only, modifier+letter combos.                                                                                                                                                                                                                                          |
| `hotkey.py` (`ChordDetector`)| Feed fake key events directly (no real pynput Listener). Assert: fires once on transition into all-pressed; does not fire while held; second press after release fires again; partial chord does not fire; releasing one target key disarms.                                                                          |
| `sounds.py`                  | Mock `subprocess.Popen`. Empty path → no call. Missing file → no call (silent at play time; warning happens at startup, not here). Valid path → `Popen(["afplay", path])` without waiting. `validate_paths` warns and replaces missing entries with `""`.                                                              |
| `daemon.py`                  | Inject mocks for `RecordingSession` factory, `transcribe`, `copy_to_clipboard`, `sounds.play`, and a fake `ChordDetector`. Drive state transitions by calling the daemon's chord callback directly. Test: idle→record→transcribe→copy→idle, idle→record→too-short→idle, idle→record→empty-text→no-copy→idle, idle→record→api-error→keep-wav→idle, chord-during-PROCESSING is dropped (simulate by pre-setting state and asserting the callback returns without touching mocks), exception in callback returns to idle. |
| PID file logic               | Tests in `test_main.py` for: write on start, remove on graceful exit, refuse-if-exists, stale-detection-and-cleanup, `ec stop` happy path, `ec stop` with no PID file, `ec stop` with already-dead PID.                                                                                                               |
| Subcommand dispatch          | Tests for `ec` (existing one-shot), `ec listen` (constructs and runs Daemon — Daemon mocked), `ec stop` (calls stop logic — process operations mocked). Existing one-shot end-to-end tests remain green after the recorder refactor.                                                                                  |
| `recorder.py`                | **No automated tests.** Manual smoke test verifies both the refactored one-shot path and the daemon path.                                                                                                                                                                                                              |

**Explicitly NOT tested:**
- Real pynput Listener (hardware/permissions)
- Real `afplay` invocation (would actually beep during test runs)
- Real OpenAI API calls
- Real cross-thread timing race conditions (covered by manual smoke test)

## Manual Smoke Test (final task)

1. Grant Accessibility permission to whatever terminal you run `ec listen` from.
2. `ec listen` → see "Listening for ⌃⌥⌘ chord."
3. Switch focus to Slack/Notes/anything. Press ⌃⌥⌘.
4. Hear start beep. Speak a phrase. Press ⌃⌥⌘.
5. Hear stop beep. ~1s later, paste with ⌘V. Confirm transcription is correct.
6. Press chord, immediately press chord again (under 0.5s) → empty beep, no clipboard change.
7. Press chord, hold ⌃⌥⌘ for 5 seconds (don't release) → should still trigger only once.
8. Press chord, speak silence, press chord → empty beep, clipboard unchanged (vocab-echo guard).
9. In a second terminal: `ec stop` → daemon exits, "daemon stopped" printed.
10. Restart with `ec listen`. In another terminal `kill -9 <pid>` → restart `ec listen` and confirm stale PID file is cleaned with a warning.
11. Edit `config.toml` to set `[hotkey.sounds] start = "/nonexistent"` → restart daemon, see warning, daemon still works (no start beep).
12. Edit `config.toml` to set an invalid chord key → restart daemon, see clear ConfigError, exit 1.
13. Run the existing one-shot `ec` (terminal-based) and confirm the recorder refactor didn't break it.

## Documentation

The README must be updated to cover:

- New `ec listen` and `ec stop` commands and their flags
- Accessibility permission requirement and where to grant it
- pynput dependency
- Hotkey config example with the new `[hotkey]` section
- A note that the daemon is started manually (LaunchAgent is roadmap, not MVP)

## Open Questions

- _(none at design-approval time)_

## Future Work (Post-Milestone)

- LaunchAgent for auto-start on login
- Menu bar indicator and macOS notifications
- `ec status` and `ec restart` commands
- Hot-reload of config without restart
- Pluggable transcription backend (separate roadmap milestone — local Whisper)
