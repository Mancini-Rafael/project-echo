![Project Echo](logo-project-echo.png)

A macOS dictation tool. Press a global hotkey, speak, press it again — the
transcription lands on your clipboard or directly on your text input. Works
from any app, any window, any text field.

## What it is

`project-echo` is a small, single-process Python CLI named `ec`. It captures
audio from your microphone, transcribes it, and copies the result to your
clipboard via `pbcopy`. Two ways to drive it: a one-shot terminal command, or a
long-running daemon that listens for a global keyboard chord.

Transcription runs on one of two backends, picked per run with `--backend`:

- **OpenAI** (default): `gpt-4o-transcribe`. Best accuracy, needs an API key,
  audio leaves your machine.
- **Local** (`--backend local`): a [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
  model on your Mac. Free, offline, no API key, nothing uploaded. See
  [Local models](#local-models-whispercpp).

A third command, `ec video`, turns a video's audio into a transcript with
word-level timestamps (always local), for AI video-editing workflows.

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
- **Replaceable backend.** Modules are split by responsibility, and both
  backends share one call signature, so the one-shot command and the daemon
  run on either without knowing which.

The binary is named `ec` because `echo` is a reserved shell builtin.

## How do you use it?

### Setup

Requirements: macOS, Python 3.12+, and either an OpenAI API key or a local
whisper.cpp model ([Local models](#local-models-whispercpp)). You only need the
key if you use the OpenAI backend.

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

A few macOS gotchas worth knowing:

- **The permission attaches to your terminal app, not to `ec` or Python.**
  Whatever app launches `ec` (Terminal, iTerm2, Ghostty, VS Code's integrated
  terminal, …) is what appears in the Accessibility list. You won't find
  "echo" or "python" there.
- **Accessibility and Input Monitoring are separate gates.** The chord can be
  detected (Input Monitoring) while auto-paste still fails (Accessibility), so
  it's possible for transcription to work but `--auto-paste` not to.
- **pynput prints `"This process is not trusted! Input event monitoring will
  not be possible..."` on startup when Accessibility isn't granted.** It's
  printed unconditionally and can be misleading — the hotkey may still fire.
  If you see it together with auto-paste failures, grant Accessibility.
- **Restart the terminal/daemon after granting.** Trust is read at process
  start, so a daemon that was already running won't pick up a freshly granted
  permission. Quit and relaunch it. If a previously-granted app stops working
  after an update, toggle it off and on in the Accessibility list.

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
| `ec`, `ec listen` | `--backend openai\|local` | Transcribe with OpenAI (default) or local whisper.cpp |
| `ec`, `ec listen` | `--no-vocabulary` | Don't send `vocabulary_prompt` (default: send it) |

#### Local dictation (no API key)

Once a local model is set up ([Local models](#local-models-whispercpp)), add
`--backend local` to either command. Nothing leaves your machine.

```sh
uv run ec --backend local                                  # one-off
uv run ec listen --backend local                           # hotkey daemon
uv run ec listen --backend local --no-vocabulary --auto-paste
```

Restart a running daemon (`uv run ec stop`) to switch backends; the backend is
chosen when `ec listen` starts.

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

### Usage (video → timestamped transcript, local)

`ec video` transcribes a video's audio **locally** with
[whisper.cpp](https://github.com/ggml-org/whisper.cpp) and writes a transcript
with segment- and word-level timestamps, meant as input for an AI video-editing
flow. No API key, no upload, no file-size limit.

One-time setup: a local model ([Local models](#local-models-whispercpp)) plus
FFmpeg for audio extraction:

```sh
brew install ffmpeg
```

Run it:

```sh
uv run ec video ~/Movies/take-03.mp4            # → take-03.transcript.json
uv run ec video ~/Movies/take-03.mp4 --srt      # also → take-03.srt
uv run ec video reuniao.mp4 --language pt --verbose
```

Output (`<name>.transcript.json`, times in seconds):

```json
{
  "source": "take-03.mp4",
  "language": "en",
  "model": "ggml-large-v3-turbo.bin",
  "segments": [
    {
      "start": 0.0, "end": 10.6,
      "text": "And so my fellow Americans, ask not ...",
      "words": [
        {"start": 0.32, "end": 0.4, "text": "And", "probability": 0.675, "approx": false},
        {"start": 1.75, "end": 2.11, "text": "Americans,", "probability": 0.904, "approx": false}
      ]
    }
  ]
}
```

| Flag | Effect |
|------|--------|
| `--language LANG` | `pt`, `en`, … or `auto`; overrides `local_whisper.language` |
| `--srt` | Also write `<name>.srt` (subtitle cues of up to 42 chars / 3 s, built from word timings) |
| `--vocabulary` / `--no-vocabulary` | Send (or skip) your vocabulary prompt for this run; overrides `local_whisper.use_vocabulary` |
| `--verbose` | Print per-stage timings to stderr |

`ec video` uses the `[local_whisper]` settings described in
[Local models](#local-models-whispercpp), including `use_vocabulary`.

Behavior worth knowing:

- Audio is the **first audio stream** of the input, converted to 16 kHz mono.
  Audio files work too.
- Outputs are written atomically and re-running overwrites them, so an
  interrupted run never leaves a half-written transcript.
- A video with no audio stream fails with `no audio stream in <file>`.
  Silence produces a valid transcript with `"segments": []` and a warning.
- If transcription fails after extraction, the WAV is kept and its path printed.

Known limits:

- **Word timestamps are approximate** (whisper token timing). Punctuation never
  moves a word's timing, so pauses stay visible. But around silence whisper can
  misplace words: with 3 s of leading silence, the first words were stamped
  *inside* the silence, and after long gaps several words can collapse onto the
  same instant. Those zero-length words are marked `"approx": true`; don't cut
  on them, and leave a margin around word boundaries in general.
- **Word splitting assumes spaces between words.** For Japanese, Chinese or
  Thai, a whole segment comes out as one "word".
- **Only the first audio track is used.** Multi-track recordings (e.g. mic on
  track 2) need re-muxing first.
- **Whisper can hallucinate on silence or music** (e.g. a stray "Thank you.").
  There is no VAD filtering yet.
- **`auto` language detection** can misfire on very short clips; pin
  `--language` when you know it.

### Local models (whisper.cpp)

The local backend (`ec --backend local`, `ec listen --backend local`, and
`ec video`) runs [whisper.cpp](https://github.com/ggml-org/whisper.cpp) on your
Mac. On Apple Silicon it uses the GPU (Metal) automatically. You bring the
model file; echo never downloads anything on its own.

**1. Install whisper.cpp**

```sh
brew install whisper-cpp
which whisper-cli        # → /opt/homebrew/bin/whisper-cli
```

**2. Download a model.** Models are single `ggml-*.bin` files from
[huggingface.co/ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp/tree/main).
Pick one by trading speed for accuracy:

| Model file | Size | Notes |
|------------|------|-------|
| `ggml-tiny.en.bin` | 78 MB | Fastest; English only; noticeably less accurate |
| `ggml-base.en.bin` | 148 MB | Fast; English only; fine for quick dictation |
| `ggml-small.bin` | 488 MB | Multilingual; good middle ground |
| `ggml-large-v3-turbo-q5_0.bin` | 574 MB | Quantized turbo; near large-model quality at a third of the size |
| `ggml-large-v3-turbo.bin` | 1.6 GB | **Default.** Multilingual, best speed/accuracy balance |
| `ggml-large-v3.bin` | 3.1 GB | Most accurate; slowest |

Models ending in `.en` only understand English. Use a multilingual one if you
speak Portuguese, Spanish, etc.

```sh
mkdir -p ~/.local/share/echo/models
curl -L -o ~/.local/share/echo/models/ggml-large-v3-turbo.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
```

**3. Point echo at it (only if you didn't use the default).** With no
`[local_whisper]` section, echo looks for
`~/.local/share/echo/models/ggml-large-v3-turbo.bin`. To use any other model,
including a fine-tuned one you converted to ggml yourself, add this to
`config/config.toml`:

```toml
[local_whisper]
binary = "whisper-cli"                                    # or a full path
model_path = "~/.local/share/echo/models/ggml-small.bin"  # any ggml .bin
language = "auto"         # or "en", "pt", ... ; `auto` can misdetect short clips
use_vocabulary = true     # `ec video` only; see the note below
```

**4. Check it works**, outside echo first if anything looks off:

```sh
whisper-cli -m ~/.local/share/echo/models/ggml-large-v3-turbo.bin -f some.wav
uv run ec --backend local
```

Trade-offs versus the OpenAI backend:

- **Latency.** Each dictation loads the model from disk, so expect an extra
  second or more per press (larger models take longer). The daemon doesn't keep
  the model loaded yet.
- **Accuracy.** OpenAI's `gpt-4o-transcribe` is generally stronger, especially
  on names and jargon. Smaller local models trade accuracy for speed.
- **Vocabulary prompt.** Whisper reads `vocabulary_prompt` as speech that came
  *before* the audio, not as instructions, so a long list can backfire: on one
  test recording it caused misheard words and a repeated phrase. If names come
  out wrong, try `--no-vocabulary` (dictation and `ec video`) or
  `use_vocabulary = false` under `[local_whisper]` (for `ec video`).

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
(or, with --backend local, run through whisper-cli on this machine)
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
| `whisper-cli not found` | whisper.cpp isn't installed, or the binary has another name | `brew install whisper-cpp`; older formulas name it `whisper-cpp`, so set `binary = "whisper-cpp"` under `[local_whisper]` |
| `whisper model not found at ...` | No model at the configured path | Download one ([Local models](#local-models-whispercpp)) or fix `model_path` |
| Local transcripts mishear names or repeat phrases | Vocabulary prompt biasing whisper | Run with `--no-vocabulary` |
| Local dictation is slow | Large model reloaded on every press | Use a smaller or quantized model (e.g. `ggml-large-v3-turbo-q5_0.bin`) |

## Project Layout

```
project-echo/
├── .github/workflows/      # CI pipeline (lint, test, commitlint)
├── config/                 # gitignored except config.example.toml
├── src/echo/
│   ├── __init__.py
│   ├── backends.py         # OpenAI / local dictation backends (--backend)
│   ├── __main__.py         # entry point, subcommand dispatch, PID file
│   ├── clipboard.py        # pbcopy + osascript paste wrappers
│   ├── config.py           # TOML loading + HotkeyConfig
│   ├── daemon.py           # hotkey daemon state machine
│   ├── hotkey.py           # chord parsing + ChordDetector
│   ├── recorder.py         # RecordingSession (thread-friendly mic capture)
│   ├── sounds.py           # afplay wrapper
│   ├── media.py            # ffmpeg audio extraction for `ec video`
│   ├── timed_transcript.py # timestamped transcript types + JSON/SRT output
│   ├── transcriber.py      # OpenAI client wrapper + vocab-echo guard
│   ├── whisper_cpp.py      # whisper-cli runner + token→word timestamp parser
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

### Distribution — next

- [ ] First-run wizard: create config, prompt for API key, walk through granting
      Microphone + Accessibility permissions
- [ ] One-liner install script (`curl | sh`) that bootstraps system deps
      (portaudio, uv) with platform detection
- [ ] Homebrew tap / formula for native `ec` binary installation
- [ ] `ec doctor` command to diagnose setup (deps, permissions, API key, config)

### Local Whisper — in progress

- [x] Pluggable transcription backend behind a thin interface
- [x] Local Whisper (`whisper.cpp`) for timestamped video transcription (`ec video`)
- [x] Local Whisper for dictation (`ec --backend local`, `ec listen --backend local`)
- [ ] Config switch to choose between OpenAI and local (flag only for now)
- [ ] Keep the local model warm in `ec listen` to cut per-press latency
- [ ] Benchmark latency and accuracy against the OpenAI default
- [ ] Optional offline mode (no network calls at all)

### Quality of life — later

- [ ] LaunchAgent for auto-start on login
- [ ] Menu bar indicator for recording state
- [ ] `ec status` and `ec restart` commands
- [ ] Hot-reload of config without restart

## License

[The Unlicense](LICENSE) — public domain. Do whatever you want with it.
