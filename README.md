# project-echo

A macOS CLI dictation tool. Records audio from your microphone, transcribes it
via OpenAI's `gpt-4o-transcribe`, and copies the result straight to your
clipboard so you can paste it anywhere.

The binary is named `ec` (since `echo` is a reserved shell builtin).

## Goals

- **Fast.** Sub-2-second wall-clock from "stop recording" to "text on
  clipboard" for short clips. No daemons, no warm-up, no GUI overhead.
- **Accurate on developer vocabulary.** Library names, tool names, framework
  names, and proper nouns should transcribe correctly out of the box. The
  config exposes a vocabulary prompt you tune for your own jargon.
- **Simple and replaceable.** Single Python process, modules split by
  responsibility so the transcription backend can be swapped (e.g. for a local
  Whisper model) without rewriting the rest of the tool.
- **No surprises.** API key only via environment variable. No telemetry. No
  history. Failure modes are explicit and the clipboard is never overwritten
  on error.

## Requirements

- macOS (depends on `pbcopy` and the macOS microphone APIs)
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) for dependency management
- [`portaudio`](https://www.portaudio.com/) (linked by `sounddevice`)
- An OpenAI API key

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

Now press **⌃⌥⌘** (Control + Option + Command) anywhere on the system to
toggle a recording. You'll hear a beep on start and a different beep on stop.
The transcription lands on your clipboard ~1s after you press the chord
again. Configure the chord and sound files in `config/config.toml` under
`[hotkey]` and `[hotkey.sounds]`. Supported modifier names: `control`,
`option`, `command`, `shift`.

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

## Project Layout

```
project-echo/
├── config/                 # gitignored except config.example.toml
├── docs/superpowers/specs/ # design documents
├── .claude/plans/          # implementation plans
├── src/echo/
│   ├── __main__.py         # entry point, subcommand dispatch, PID file
│   ├── config.py           # TOML loading + HotkeyConfig
│   ├── recorder.py         # RecordingSession (thread-friendly mic capture)
│   ├── transcriber.py      # OpenAI client wrapper
│   ├── clipboard.py        # pbcopy wrapper
│   ├── daemon.py           # hotkey daemon state machine
│   ├── hotkey.py           # chord parsing + ChordDetector
│   ├── sounds.py           # afplay wrapper
│   └── ui.py               # terminal status formatters
└── tests/                  # pytest, no real network or hardware
```

## Tests

```sh
uv run pytest
```

The recorder module is hardware-dependent and intentionally has no automated
tests. Everything else is covered.

## Roadmap

### MVP — complete

- [x] CLI binary `ec` invoked from the terminal
- [x] Microphone capture via `sounddevice` with spacebar stop
- [x] Transcription via OpenAI `gpt-4o-transcribe` with a tunable vocabulary prompt
- [x] Result printed to terminal and copied to the clipboard via `pbcopy`
- [x] Configurable model, language, sample rate, and vocabulary
- [x] Clear failure modes (missing API key, no mic permission, empty audio, API errors)
- [x] Vocabulary-prompt-echo guard so silent recordings don't paste the prompt back

### Enable local LLM

- [ ] Pluggable transcription backend behind a thin interface
- [ ] Local Whisper (`faster-whisper` or `whisper.cpp`) implementation
- [ ] Config switch to choose between OpenAI and local
- [ ] Benchmark latency and accuracy against the OpenAI default
- [ ] Optional offline mode (no network calls at all)

### Hotkey daemon — complete

- [x] Long-running daemon (`ec listen`) holding the mic stream open between presses
- [x] Configurable global hotkey chord (default `⌃⌥⌘`) defined in `config.toml`
- [x] Configurable start/stop/empty sound cues
- [x] PID file lifecycle and `ec stop` for clean shutdown
- [x] Survives transient failures (mic permission, API errors, missing sound files)
- [ ] LaunchAgent for auto-start on login
- [ ] Menu bar indicator for recording state

## License

[The Unlicense](LICENSE) — public domain. Do whatever you want with it.
