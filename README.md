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

## Usage

```sh
uv run ec
```

1. `● Recording... (press space to stop) 0:00` — the timer ticks
2. Speak
3. Press **space** to stop
4. `✓ Transcribing...`
5. `> your transcribed text`
6. `✓ Copied to clipboard.`

### Flags

| Flag        | Effect                                                            |
|-------------|-------------------------------------------------------------------|
| `--verbose` | Print per-stage timings (record, transcribe) to stderr at the end |
| `--clean`   | Reserved for future LLM cleanup pass; currently exits with a stub |
| `--help`    | argparse help                                                     |

## Project Layout

```
project-echo/
├── config/                 # gitignored except config.example.toml
├── docs/superpowers/specs/ # design documents
├── .claude/plans/          # implementation plans
├── src/echo/
│   ├── __main__.py         # entry point and orchestration
│   ├── config.py           # TOML loading
│   ├── recorder.py         # mic capture + spacebar stop
│   ├── transcriber.py      # OpenAI client wrapper
│   ├── clipboard.py        # pbcopy wrapper
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

### Hotkey daemon

- [ ] Background process holding the mic stream open
- [ ] Global hotkey (push-to-talk or toggle) instead of running `ec` per recording
- [ ] Menu bar indicator for recording state
- [ ] LaunchAgent for auto-start on login

## License

Personal project. No license declared.
