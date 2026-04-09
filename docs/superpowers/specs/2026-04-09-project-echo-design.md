# project-echo — Design

**Date:** 2026-04-09
**Status:** Approved (pending user spec review)
**Author:** Rafael Mancini
**Replaces:** AudioWhisper (deleted; suffered from latency and transcription errors)

## Summary

A macOS CLI tool that records audio from the microphone, sends it to OpenAI's
audio transcription API, prints the result, and copies it to the clipboard.
Optimized for fast dictation of code-heavy / dev terminology.

The MVP is intentionally minimal: one binary, one command, no daemon, no GUI.

## Goals

- Sub-2-second total latency from "stop recording" to "text on clipboard" for
  short clips (under 30 seconds).
- High accuracy on developer vocabulary (library names, tools, proper nouns)
  via OpenAI's most accurate model plus a tunable vocabulary prompt.
- Simple, single-process invocation. No background services, no permission
  prompts beyond microphone access.
- Architecture that allows swapping the transcription backend (e.g. local
  Whisper) in the future without rewriting the rest of the tool.

## Non-Goals (Out of Scope for MVP)

- Local Whisper / local LLM models (deferred future work)
- GUI or menu bar app
- Global hotkey / system-wide trigger
- Streaming transcription / partial results
- Speaker diarization, timestamps, SRT/VTT output
- Persistent history of past transcriptions
- Output sinks other than the clipboard (no piping, no file writes)
- Cross-platform support; macOS only
- Auto-update / Homebrew formula
- CI/CD pipelines
- Telemetry of any kind

## Naming

- **Project name:** `project-echo`
- **Binary name:** `ec`
  - `echo` is a reserved shell builtin and cannot be used.
  - `ec` is two characters, fast to type, and not present on stock macOS.

## User Flow

```
$ ec
● Recording... (press space to stop) 0:03
[user presses space]
✓ Transcribing...
> Let me refactor the useState hook in the dashboard component.
✓ Copied to clipboard.
```

Total wall-clock time after spacebar press: target ~1–2 seconds for short
clips, dominated by the OpenAI API round-trip.

## Architecture

Single Python process. No daemon. No background workers. End-to-end:

```
ec
 │
 ├─ load config (./config/config.toml relative to repo root)
 ├─ verify OPENAI_API_KEY env var is set; abort with clear error if not
 ├─ open microphone stream via sounddevice (16 kHz mono)
 ├─ print "● Recording... (press space to stop) 0:00"
 ├─ spawn keypress watcher in raw tty mode → on SPACE: stop
 ├─ update elapsed timer in-place once per second
 │
 ├─ on stop:
 │    ├─ if duration < 0.5s → discard, print warning, exit
 │    ├─ write buffer to /tmp/echo-<timestamp>.wav
 │    ├─ POST to OpenAI audio API with model + vocabulary prompt
 │    ├─ on success: print transcription, pipe to `pbcopy`, delete WAV
 │    └─ on failure: print error, KEEP WAV, print its path
 └─ exit
```

### Module Layout

```
project-echo/
├── README.md
├── pyproject.toml          # uv-managed; declares deps and `ec` entry point
├── .python-version
├── .gitignore              # ignores /config/* except config.example.toml
├── .env.example
├── config/
│   ├── config.toml         # gitignored; user's actual config
│   └── config.example.toml # committed template
├── src/
│   └── echo/
│       ├── __init__.py
│       ├── __main__.py     # argparse, top-level orchestration, exit codes
│       ├── config.py       # TOML loading, defaults, first-run bootstrap
│       ├── recorder.py     # sounddevice capture + spacebar-stop loop
│       ├── transcriber.py  # OpenAI client wrapper
│       ├── clipboard.py    # pbcopy subprocess wrapper
│       └── ui.py           # terminal output: timer, status lines, errors
└── tests/
    ├── test_config.py
    ├── test_transcriber.py
    ├── test_clipboard.py
    └── test_main.py
```

**Boundaries.** Each module has one job and a small public surface, so any one
of them (especially `transcriber.py` and `recorder.py`) can be replaced
without touching the others.

### Tooling

- **Python package manager:** `uv`. Run via `uv run ec` during development.
- **Python version:** pinned in `.python-version`.
- **Audio capture:** `sounddevice` (PortAudio binding) — captures straight to
  a numpy buffer in-process, no shell-out to ffmpeg/sox.
- **HTTP / OpenAI client:** the official `openai` Python SDK.
- **Clipboard:** subprocess call to `pbcopy` (macOS built-in, zero deps).
- **Tests:** `pytest` + `pytest-mock`.

## Configuration

Config lives at `./config/config.toml`, relative to the repo root. Gitignored.
A committed `config.example.toml` serves as the template and is auto-copied to
`config.toml` on first run if missing.

```toml
[openai]
model = "gpt-4o-transcribe"
# API key is read from OPENAI_API_KEY env var, never from this file.

[transcription]
# Bias the model toward your vocabulary. Comma- or space-separated string.
# Capped at ~244 tokens per OpenAI documentation.
vocabulary_prompt = """
TypeScript, Python, Postgres, Kubernetes, Docker, Rails, Django, Flask,
React, Next.js, Tailwind, npm, pnpm, uv, async, await, webhook, OAuth,
Vulcan, Tarifei, Comex Radar, Rafael Mancini
"""
language = "en"  # ISO-639-1 code; omit or empty string for auto-detect

[recording]
sample_rate = 16000   # Whisper's native rate; no resampling needed
channels = 1          # mono
```

### Why these defaults

- **`gpt-4o-transcribe`** — measurably more accurate than `whisper-1` and
  `gpt-4o-mini-transcribe` on technical vocabulary, accents, and proper nouns.
  Cost overhead is negligible at single-user volume (estimated $2–8/month for
  typical dev usage).
- **Vocabulary prompt** — the OpenAI audio API accepts a `prompt` parameter
  that biases recognition toward listed terms. Bigger accuracy lever than
  the model choice itself for jargon-heavy speech.
- **API key in env var only** — never written to a config file, even a
  gitignored one. Personal trust rule for third parties.
- **16 kHz mono** — matches Whisper's native input sample rate; smaller
  files, faster upload, no quality loss for speech.

## CLI Surface

```
ec                  # default: record, transcribe, copy
ec --clean          # post-process the transcription with an LLM cleanup pass
ec --verbose        # log per-stage timing breakdown to stderr
ec --help
```

`--clean` is parsed by argparse in the MVP but prints "not yet implemented"
and exits. Full implementation is deferred. The default path must NOT include
any LLM cleanup, because that was a likely cause of latency in AudioWhisper.

## Error Handling

No silent failures. The clipboard is never overwritten on error.

| Failure                              | Handling                                                                            |
|--------------------------------------|-------------------------------------------------------------------------------------|
| `OPENAI_API_KEY` missing             | Exit immediately with clear message, before opening the mic                         |
| `config/config.toml` missing         | Auto-copy from `config.example.toml`, print "created config at ..."                 |
| No mic / permissions denied          | Catch sounddevice error, print actionable msg pointing at System Settings → Privacy |
| Recording shorter than 0.5s          | Discard, print "recording too short", exit cleanly                                  |
| OpenAI API error (network, 4xx, 5xx) | Print error, KEEP the temp WAV, print its path so the user can retry manually       |
| API returns empty string             | Print "transcription empty", do NOT touch the clipboard                             |
| `pbcopy` failure                     | Print transcription to stdout anyway so the user can copy manually                  |
| Ctrl-C during recording              | Stop stream, delete temp file, exit 130                                             |
| Ctrl-C during API call               | Keep WAV, print its path, exit 130                                                  |

### Logging

Structured-ish status output to stderr. `--verbose` dumps a per-stage timing
breakdown (record duration, file write, upload, API time, clipboard) so future
latency regressions are diagnosable.

## Testing Strategy

TDD where it's useful; skipped where the tests would be theatre.

| Module           | Approach                                                                                                                   | Rationale                                          |
|------------------|----------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------|
| `config.py`      | Real unit tests: missing file → auto-creates, malformed TOML → clear error, env-var presence checks                        | Pure logic, fast, high value                       |
| `transcriber.py` | Mock the OpenAI client. Assert correct model, correct vocabulary prompt, file handle passed; verify error paths surface up | API is the boundary; don't burn real quota in CI   |
| `clipboard.py`   | Subprocess mock + one macOS-gated integration test that round-trips through `pbcopy`/`pbpaste`                             | Cheap to verify for real on the target platform    |
| `ui.py`          | Snapshot output strings for the few status lines                                                                           | Trivial, regression-catching                       |
| `recorder.py`    | **No automated tests.** Manual verification only.                                                                          | Hardware-dependent; mocking sounddevice tests nothing real |
| `__main__.py`    | One end-to-end test with everything mocked: argparse → config → recorder stub → transcriber mock → clipboard mock          | Catches wiring bugs                                |

**Explicitly not done:** no real API calls in tests, no CI pipeline.

## Open Questions

None at design-approval time. Listed here so they're tracked if discovered
during implementation:

- _(none yet)_

## Future Work (Post-MVP)

- Local Whisper model for offline use and zero-cost transcription
- Optional LLM cleanup pass via `--clean` (already reserved in CLI surface)
- Global hotkey trigger (would require a small daemon)
- Per-project vocabulary overrides
- Streaming transcription for long-form dictation
