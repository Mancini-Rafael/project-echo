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


# ----- HotkeyConfig -----

from echo.config import HotkeyConfig


def _write_config_with_hotkey(tmp_path, hotkey_section: str) -> Path:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[openai]\nmodel = "gpt-4o-transcribe"\n'
        '[transcription]\nvocabulary_prompt = ""\nlanguage = "en"\n'
        '[recording]\nsample_rate = 16000\nchannels = 1\n'
        + hotkey_section
    )
    return cfg_path


def test_hotkey_config_defaults_when_section_missing(tmp_path: Path) -> None:
    cfg_path = _write_config_with_hotkey(tmp_path, "")
    cfg = load_config(cfg_path)
    assert cfg.hotkey.chord == ("control", "option", "command")
    assert cfg.hotkey.sound_start == "/System/Library/Sounds/Pop.aiff"
    assert cfg.hotkey.sound_stop == "/System/Library/Sounds/Tink.aiff"
    assert cfg.hotkey.sound_empty == "/System/Library/Sounds/Funk.aiff"


def test_hotkey_config_accepts_legacy_aliases(tmp_path: Path) -> None:
    """Old chord names (ctrl/alt/cmd) must still parse — backwards compatible."""
    section = '[hotkey]\nchord = ["ctrl", "alt", "cmd"]\n'
    cfg_path = _write_config_with_hotkey(tmp_path, section)
    cfg = load_config(cfg_path)
    assert cfg.hotkey.chord == ("ctrl", "alt", "cmd")


def test_hotkey_config_parses_custom_section(tmp_path: Path) -> None:
    section = (
        '[hotkey]\nchord = ["ctrl", "shift", "f1"]\n'
        '[hotkey.sounds]\nstart = "/tmp/a"\nstop = "/tmp/b"\nempty = ""\n'
    )
    cfg_path = _write_config_with_hotkey(tmp_path, section)
    cfg = load_config(cfg_path)
    assert cfg.hotkey.chord == ("ctrl", "shift", "f1")
    assert cfg.hotkey.sound_start == "/tmp/a"
    assert cfg.hotkey.sound_stop == "/tmp/b"
    assert cfg.hotkey.sound_empty == ""


def test_hotkey_config_unknown_key_raises(tmp_path: Path) -> None:
    section = '[hotkey]\nchord = ["ctrl", "wat"]\n'
    cfg_path = _write_config_with_hotkey(tmp_path, section)
    with pytest.raises(ConfigError, match="Unknown hotkey key"):
        load_config(cfg_path)


def test_hotkey_config_empty_chord_raises(tmp_path: Path) -> None:
    section = '[hotkey]\nchord = []\n'
    cfg_path = _write_config_with_hotkey(tmp_path, section)
    with pytest.raises(ConfigError, match="empty"):
        load_config(cfg_path)
