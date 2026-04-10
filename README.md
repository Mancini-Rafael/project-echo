![Project Echo](logo-project-echo.png)

A macOS dictation tool. Press a global hotkey, speak, press it again — the
transcription lands on your clipboard or directly on your text input. Works
from any app, any window, any text field.

## What it is

`project-echo` is a small, single-process Python CLI named `ec`. It captures
audio from your microphone, sends it to OpenAI's `gpt-4o-transcribe`, and
copies the result to your clipboard via `pbcopy`. Two ways to drive it: a
one-shot terminal command, or a long-running daemon that listens for a global
keyboard chord.

The design is deliberately small and replaceable:

- **Fast.** Sub-2-second wall-clock from "stop recording" to "text on
  clipboard" for short clips. The daemon keeps an OpenAI client warm so per-recording
  init cost is zero.
- **Accurate on developer vocabulary.** Library names, tool names, framework
  names, and proper nouns transcribe correctly because the OpenAI audio API
  accepts a vocabulary prompt that biases recognition. You tune that list in
  the config file.
- **No surprises.** API key only via environment variable. No telemetry. No
  history. Failure modes are explicit and the clipboard is never overwritten
  on error.
- **Replaceable backend.** Modules are split by responsibility so the
  transcription backend (currently OpenAI) can be swapped for a local Whisper
  model without rewriting the rest of the tool. That's the next milestone.

The binary is named `ec` because `echo` is a reserved shell builtin.

## How do you use it?

### Setup

Requirements: macOS, Python 3.12+, an OpenAI API key.

```sh
# system deps
brew install uv portaudio

# project deps
uv sync

# config — the first run creates this automatically from the example,
# but you can copy it now to edit before running
cp config/config.example.toml config/config.toml

# api key — add this to your shell profile (~/.zshrc) so it persists
export OPENAI_API_KEY=sk-...
```

Edit `config/config.toml` to tune the vocabulary prompt with your own list of
project names, libraries, and jargon. The file is gitignored.

> **Note:** The `export` command only sets the key for the current terminal
> session. To make it permanent, add the `export OPENAI_API_KEY=...` line to
> your `~/.zshrc` (or `~/.bashrc`), then run `source ~/.zshrc`.

The first time you run `ec`, macOS will ask for **microphone permission** for
your terminal. Grant it via *System Settings → Privacy & Security →
Microphone*.

For the daemon (`ec listen`), you also need to grant **Accessibility**
permission to your terminal so it can listen for global keypresses and, if
you use `--auto-paste`, simulate keyboard input. macOS will prompt the first
time. Grant it via *System Settings → Privacy & Security → Accessibility*.

### Usage (one-off)

```sh
uv run ec
```

1. `● Recording... (press space to stop) 0:00` — the timer ticks
2. Speak
3. Press **space** to stop
4. `✓ Transcribing...`
5. `> your transcribed text`
6. `✓ Copied to clipboard.`

Add `--verbose` to print per-stage timings to stderr.

### Usage (always-on + hotkey)

Start the daemon in any terminal — leave it running:

```sh
uv run ec listen
```

You'll see `✓ Listening for control+option+command chord. Press Ctrl-C to
quit.`

Now press **⌃⌥⌘** (Control + Option + Command) simultaneously anywhere on
the system to toggle a recording. This is a modifier-only chord — you don't
press any letter key, just hold all three modifiers at the same time:

- First press → start beep, mic opens
- Speak
- Second press → stop beep, transcription lands on clipboard ~1s later
- Paste with **⌘V** in any app

Configure the chord and sound cues in `config/config.toml` under `[hotkey]`
and `[hotkey.sounds]`. Supported modifier names: `control`, `option`,
`command`, `shift`. You can also use printable letters/digits, `space`, or
`f1`–`f12` as additional slot members.

To stop the daemon from any other terminal:

```sh
uv run ec stop
```

To restart cleanly: `uv run ec stop && uv run ec listen`.

#### Flags

| Command       | Flag        | Effect                                                            |
|---------------|-------------|-------------------------------------------------------------------|
| `ec`          | `--verbose` | Print per-stage timings to stderr                                 |
| `ec listen`   | `--verbose` | Print per-recording timings                                       |
| `ec listen`   | `--force`   | Overwrite an existing PID file                                    |
| `ec listen`   | `--auto-paste` | Simulate Cmd+V after transcription to paste into the focused app |

#### Auto-paste

Pass `--auto-paste` to `ec listen` to have the daemon simulate **Cmd+V**
after every successful transcription:

```sh
uv run ec listen --auto-paste
```

The paste is unconditional — the daemon does not check whether a text input
field is focused. In most apps, pasting into a non-text context is a no-op.
If the paste fails (e.g. Accessibility permission not granted), the
transcription is still on your clipboard for manual pasting.

The Accessibility permission required for the global hotkey already covers the
paste simulation — no additional setup needed.

## How does it work?

End-to-end pipeline for a single recording:

```
press hotkey (or run `ec`)
        │
        ▼
sounddevice opens an InputStream → audio chunks land in an in-memory buffer
        │
        ▼
press hotkey again (or press space)
        │
        ▼
buffer is flushed to a temp WAV at /tmp/echo-<ts>.wav
        │
        ▼
WAV is POSTed to the OpenAI audio API with the configured vocabulary prompt
        │
        ▼
text comes back → pbcopy → clipboard
        │
        ▼
(if --auto-paste) simulate Cmd+V → text lands in focused app
        │
        ▼
temp WAV is deleted
```

A few details worth knowing:

- **Audio format.** Records at 16 kHz mono, which matches what the OpenAI
  transcription model expects natively — no resampling needed, smaller files,
  faster upload.
- **Vocabulary prompt.** The OpenAI audio API accepts a `prompt` parameter
  that biases the model toward specific words. You fill this with your
  developer jargon (library names, project names, acronyms) in the config
  file. This is the single biggest accuracy lever for technical speech.
- **Vocabulary echo guard.** Whisper-family models sometimes echo the
  vocabulary prompt back when there's no actual speech. The tool detects
  this and returns an empty string instead, so a silent recording doesn't
  paste the vocab list into your clipboard.
- **Sound cues.** Four configurable sounds (`start`, `stop`, `empty`,
  `success`) play via `afplay`. If a sound file is missing, that cue
  becomes silent with a warning — the daemon won't crash over a missing
  `.aiff` file.
- **Daemon resilience.** The daemon uses a PID file at `/tmp/echo-daemon.pid`
  to prevent duplicate instances. `ec stop` sends a graceful shutdown signal.
  Accidental double-presses during transcription are ignored — you can't
  start a new recording while the previous one is still processing.

<details>
<summary>Internals (for contributors)</summary>

- **Daemon state machine.** Three states: `idle`, `recording`, `processing`.
  The `processing` state swallows chord events while transcription runs.
  State transitions are guarded by a `threading.Lock` acquired non-blocking
  from the chord callback — events that can't grab the lock are dropped.
- **Chord detection.** The chord is parsed into a tuple of "slots", where
  each slot is a frozenset of pynput keys (e.g. the `control` slot accepts
  both `ctrl_l` and `ctrl_r`). The detector fires once on the leading edge
  of "all slots satisfied" and re-arms when at least one target key is
  released.
- **PID file lifecycle.** `ec listen` writes the PID file on startup, refuses
  to start if the file exists and the named process is alive, cleans up stale
  files automatically. `ec stop` reads the PID, sends SIGTERM, polls for 2
  seconds, escalates to SIGKILL if still alive.

</details>

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `OPENAI_API_KEY not set` | API key not in your environment | Add `export OPENAI_API_KEY=sk-...` to `~/.zshrc` and run `source ~/.zshrc` |
| `ec` starts but no audio is captured | Microphone permission not granted | *System Settings → Privacy & Security → Microphone* → enable your terminal |
| `ec listen` starts but the hotkey does nothing | Accessibility permission not granted | *System Settings → Privacy & Security → Accessibility* → enable your terminal |
| `daemon already running (PID ...)` | A previous daemon is still alive | Run `uv run ec stop` first, or pass `--force` |
| `--auto-paste` doesn't paste | Accessibility permission not granted, or no focused app | Check Accessibility permission; the transcription is still on your clipboard |
| Sound cues don't play | Sound file path in config is wrong or missing | Check `[hotkey.sounds]` paths in `config/config.toml`; set to `""` to disable |

## Project Layout

```
project-echo/
├── .github/workflows/      # CI pipeline (lint, test, commitlint)
├── config/                 # gitignored except config.example.toml
├── src/echo/
│   ├── __init__.py
│   ├── __main__.py         # entry point, subcommand dispatch, PID file
│   ├── clipboard.py        # pbcopy + osascript paste wrappers
│   ├── config.py           # TOML loading + HotkeyConfig
│   ├── daemon.py           # hotkey daemon state machine
│   ├── hotkey.py           # chord parsing + ChordDetector
│   ├── recorder.py         # RecordingSession (thread-friendly mic capture)
│   ├── sounds.py           # afplay wrapper
│   ├── transcriber.py      # OpenAI client wrapper + vocab-echo guard
│   └── ui.py               # terminal status formatters
└── tests/                  # pytest, no real network or hardware
```

Each module has one job and a small public surface. The transcription
backend, the recorder, and the chord detector can each be replaced
independently — that's the path to local Whisper later.

## Contributing

This is a personal tool released into the public domain (see License below),
but if you want to hack on it, fixes and improvements are welcome.

```sh
# clone, install
git clone https://github.com/Mancini-Rafael/project-echo.git
cd project-echo
brew install uv portaudio
uv sync

# run the tests
uv run pytest

# run locally (one-off)
uv run ec
```

A few notes if you're sending a pull request:

- **Tests.** The recorder module is hardware-dependent and has no automated
  tests on purpose. Everything else has reasonably tight coverage with all
  external boundaries (OpenAI, pbcopy, afplay, the filesystem) mocked. New
  code in those areas should follow the same pattern — tests must not hit
  real networks, microphones, or speakers.
- **Style.** The project uses [Ruff](https://docs.astral.sh/ruff/) for
  linting and formatting, enforced in CI. Run `uv run ruff check src/ tests/`
  and `uv run ruff format src/ tests/` before submitting. Beyond that: type
  hints, frozen dataclasses where they fit, small focused modules, errors as
  exceptions with actionable messages.
- **Commits.** Use [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `chore:`, `docs:`, etc.). CI enforces this via commitlint.
- **Scope.** The project deliberately stays small. Local-LLM support and a
  LaunchAgent are on the roadmap; menu bar UI and cross-platform support are
  not. If you're proposing a substantial new feature, open an issue first so
  we can talk about whether it fits.
- **Bugs.** Open an issue with reproduction steps and the output of `ec
  --verbose` or `ec listen --verbose`. The verbose flag prints per-stage
  timings, which is what you want for performance regressions.

## Roadmap

### MVP — complete

- [x] CLI binary `ec` invoked from the terminal
- [x] Microphone capture via `sounddevice` with spacebar stop
- [x] Transcription via OpenAI `gpt-4o-transcribe` with a tunable vocabulary prompt
- [x] Result printed to terminal and copied to the clipboard via `pbcopy`
- [x] Configurable model, language, sample rate, and vocabulary
- [x] Clear failure modes (missing API key, no mic permission, empty audio, API errors)
- [x] Vocabulary-prompt-echo guard so silent recordings don't paste the prompt back

### Hotkey daemon — complete

- [x] Long-running daemon (`ec listen`) holding the mic stream open between presses
- [x] Configurable global hotkey chord (default `⌃⌥⌘`) defined in `config.toml`
- [x] Configurable start/stop/empty/success sound cues
- [x] PID file lifecycle and `ec stop` for clean shutdown
- [x] Survives transient failures (mic permission, API errors, missing sound files)
- [x] Optional auto-paste (`--auto-paste`) simulates Cmd+V after transcription

### Local LLM — next

- [ ] Pluggable transcription backend behind a thin interface
- [ ] Local Whisper (`faster-whisper` or `whisper.cpp`) implementation
- [ ] Config switch to choose between OpenAI and local
- [ ] Benchmark latency and accuracy against the OpenAI default
- [ ] Optional offline mode (no network calls at all)

### Distribution — next

- [ ] One-liner install script (`curl | sh` or `brew install`)
- [ ] Auto-install system deps (portaudio, uv) with platform detection
- [ ] First-run wizard: create config, prompt for API key, grant permissions
- [ ] Homebrew formula or tap for native `ec` binary installation

### Quality of life — later

- [ ] LaunchAgent for auto-start on login
- [ ] Menu bar indicator for recording state
- [ ] `ec status` and `ec restart` commands
- [ ] Hot-reload of config without restart

## License

[The Unlicense](LICENSE) — public domain. Do whatever you want with it.
