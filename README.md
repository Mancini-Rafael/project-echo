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
