# project-echo

A macOS dictation tool. Press a global hotkey, speak, press it again — the
transcription lands on your clipboard. Works from any app, any window, any
text field.

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

# config (auto-bootstrapped on first run, or copy manually)
cp config/config.example.toml config/config.toml

# api key
export OPENAI_API_KEY=sk-...
```

Edit `config/config.toml` to tune the vocabulary prompt with your own list of
project names, libraries, and jargon. The file is gitignored.

The first time you run `ec`, macOS will ask for **microphone permission** for
your terminal. Grant it via *System Settings → Privacy & Security →
Microphone*.

For the daemon (`ec listen`), you also need to grant **Accessibility**
permission to your terminal so it can listen for global keypresses. macOS
will prompt the first time. Grant it via *System Settings → Privacy &
Security → Accessibility*.

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

Now press **⌃⌥⌘** (Control + Option + Command) anywhere on the system to
toggle a recording:

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
| `ec`          | `--clean`   | Reserved for future LLM cleanup pass; currently exits with a stub |
| `ec listen`   | `--verbose` | Print per-recording timings                                       |
| `ec listen`   | `--force`   | Overwrite an existing PID file                                    |

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
temp WAV is deleted
```

A few details worth knowing:

- **Audio format.** 16 kHz mono int16 PCM. Matches Whisper's native input
  rate, so no resampling, smaller files, faster upload.
- **Vocabulary prompt.** OpenAI's audio API takes a `prompt` parameter that
  biases the model toward specific words. We stuff it with your dev jargon at
  startup. Bigger accuracy lever than the model choice itself for technical
  speech.
- **Vocabulary echo guard.** Whisper-family models sometimes echo the
  vocabulary prompt back when there's no actual speech to transcribe. The
  transcriber detects this case (after normalizing whitespace and case) and
  returns an empty string instead, so the daemon doesn't paste the vocab
  list into your clipboard on a silent recording.
- **Daemon state machine.** The daemon is a three-state machine: `idle`,
  `recording`, `processing`. The `processing` state exists to swallow chord
  events that arrive while transcription is running, so accidental double-presses
  during the ~1s API window can't start a new recording. State transitions are
  guarded by a `threading.Lock` acquired non-blocking from the chord callback —
  events that can't grab the lock are dropped at the door.
- **Chord detection.** The chord is parsed into a tuple of "slots", where each
  slot is a frozenset of pynput keys that satisfy that slot (e.g. the
  `control` slot accepts both `ctrl_l` and `ctrl_r`). The detector fires once
  on the leading edge of "all slots satisfied" and re-arms only when at least
  one target key is released.
- **PID file lifecycle.** `ec listen` writes `/tmp/echo-daemon.pid` on
  startup, refuses to start if the file already exists and the named process
  is alive, cleans up stale files automatically. `ec stop` reads the PID,
  sends SIGTERM, polls for 2 seconds, escalates to SIGKILL if still alive.
- **Sound cues.** Three configurable cues (`start`, `stop`, `empty`) play via
  `afplay` in a non-blocking subprocess. Missing files become silent at
  startup with a warning instead of crashing the daemon.

## Project Layout

```
project-echo/
├── config/                 # gitignored except config.example.toml
├── src/echo/
│   ├── __main__.py         # entry point, subcommand dispatch, PID file
│   ├── config.py           # TOML loading + HotkeyConfig
│   ├── recorder.py         # RecordingSession (thread-friendly mic capture)
│   ├── transcriber.py      # OpenAI client wrapper + vocab-echo guard
│   ├── clipboard.py        # pbcopy wrapper
│   ├── daemon.py           # hotkey daemon state machine
│   ├── hotkey.py           # chord parsing + ChordDetector
│   ├── sounds.py           # afplay wrapper
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
- **Style.** No formal linter is wired up. Match the existing style: type
  hints, frozen dataclasses where they fit, small focused modules, errors as
  exceptions with actionable messages.
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
- [x] Configurable start/stop/empty sound cues
- [x] PID file lifecycle and `ec stop` for clean shutdown
- [x] Survives transient failures (mic permission, API errors, missing sound files)

### Local LLM — next

- [ ] Pluggable transcription backend behind a thin interface
- [ ] Local Whisper (`faster-whisper` or `whisper.cpp`) implementation
- [ ] Config switch to choose between OpenAI and local
- [ ] Benchmark latency and accuracy against the OpenAI default
- [ ] Optional offline mode (no network calls at all)

### Quality of life — later

- [ ] LaunchAgent for auto-start on login
- [ ] Menu bar indicator for recording state
- [ ] `ec status` and `ec restart` commands
- [ ] Hot-reload of config without restart

## License

[The Unlicense](LICENSE) — public domain. Do whatever you want with it.
