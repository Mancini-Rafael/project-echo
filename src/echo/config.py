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


@dataclass(frozen=True)
class Config:
    model: str
    vocabulary_prompt: str
    language: str
    sample_rate: int
    channels: int

    @staticmethod
    def require_api_key() -> str:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ConfigError(
                "OPENAI_API_KEY environment variable is not set. "
                "Export it before running ec."
            )
        return key


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
        )
    except KeyError as e:
        raise ConfigError(f"Missing required config key: {e}") from e
