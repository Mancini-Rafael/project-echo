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


_DEFAULT_HOTKEY_CHORD: tuple[str, ...] = ("control", "option", "command")
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
