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
_DEFAULT_SOUND_SUCCESS = "/System/Library/Sounds/Glass.aiff"


@dataclass(frozen=True)
class HotkeyConfig:
    chord: tuple[str, ...]
    sound_start: str
    sound_stop: str
    sound_empty: str
    sound_success: str


@dataclass(frozen=True)
class Config:
    model: str
    vocabulary_prompt: str
    language: str
    sample_rate: int
    channels: int
    hotkey: HotkeyConfig
    # Optional persisted API key (written by `ec setup`). The OPENAI_API_KEY
    # env var, when set, always wins so existing shell-exported setups don't
    # silently switch to a stale stored key.
    api_key: str | None = None

    def require_api_key(self) -> str:
        key = os.environ.get("OPENAI_API_KEY") or self.api_key
        if not key:
            raise ConfigError(
                "OPENAI_API_KEY is not set and no api_key in config. "
                "Export OPENAI_API_KEY or run `ec setup`."
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
        sound_success=str(sounds.get("success", _DEFAULT_SOUND_SUCCESS)),
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
        api_key_raw = data["openai"].get("api_key")
        return Config(
            model=data["openai"]["model"],
            vocabulary_prompt=data["transcription"].get("vocabulary_prompt", ""),
            language=data["transcription"].get("language", ""),
            sample_rate=int(data["recording"]["sample_rate"]),
            channels=int(data["recording"]["channels"]),
            hotkey=_parse_hotkey(data),
            api_key=str(api_key_raw) if api_key_raw else None,
        )
    except KeyError as e:
        raise ConfigError(f"Missing required config key: {e}") from e


# ----- config path resolution -----

# Legacy in-repo location, kept working for users who ran an older version.
# Computed at import time; tests pass their own legacy_path so this constant
# doesn't make tests environment-dependent.
_LEGACY_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.toml"


def resolve_config_path(legacy_path: Path | None = None) -> Path:
    """Resolve the path to the user's config file.

    Lookup order:
      1. $ECHO_CONFIG if set (explicit override, also used by tests).
      2. The legacy in-repo path if a file already exists there (back-compat
         for users who set up Echo before the move to ~/.config).
      3. $XDG_CONFIG_HOME/echo/config.toml if XDG_CONFIG_HOME is set.
      4. $HOME/.config/echo/config.toml otherwise.

    The returned path may or may not exist; callers handle creation.
    """
    explicit = os.environ.get("ECHO_CONFIG")
    if explicit:
        return Path(explicit)

    legacy = legacy_path if legacy_path is not None else _LEGACY_CONFIG_PATH
    if legacy.exists():
        return legacy

    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path(os.path.expanduser("~")) / ".config"
    return base / "echo" / "config.toml"
