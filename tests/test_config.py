import os
import tomllib
from pathlib import Path

import pytest

from echo.config import Config, load_config, ConfigError


def test_load_config_from_file(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[openai]\nmodel = "gpt-4o-transcribe"\n'
        '[transcription]\nvocabulary_prompt = "foo bar"\nlanguage = "en"\n'
        '[recording]\nsample_rate = 16000\nchannels = 1\n'
    )
    cfg = load_config(cfg_path)
    assert cfg.model == "gpt-4o-transcribe"
    assert cfg.vocabulary_prompt == "foo bar"
    assert cfg.language == "en"
    assert cfg.sample_rate == 16000
    assert cfg.channels == 1


def test_load_config_bootstraps_from_example(tmp_path: Path) -> None:
    example = tmp_path / "config.example.toml"
    target = tmp_path / "config.toml"
    example.write_text(
        '[openai]\nmodel = "gpt-4o-transcribe"\n'
        '[transcription]\nvocabulary_prompt = ""\nlanguage = "en"\n'
        '[recording]\nsample_rate = 16000\nchannels = 1\n'
    )
    cfg = load_config(target, example_path=example)
    assert target.exists()
    assert cfg.model == "gpt-4o-transcribe"


def test_load_config_missing_and_no_example(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml", example_path=tmp_path / "nope.example.toml")


def test_load_config_malformed_toml(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("not = valid = toml")
    with pytest.raises(ConfigError, match="parse"):
        load_config(cfg_path)


def test_config_requires_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        Config.require_api_key()


def test_config_returns_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert Config.require_api_key() == "sk-test"
