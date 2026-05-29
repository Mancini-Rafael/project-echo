from pathlib import Path

import pytest

from echo.config import Config, ConfigError, load_config, resolve_config_path


def _minimal_config(api_key: str | None = None) -> Config:
    """Construct a Config with safe defaults; only api_key varies per test."""
    from echo.config import HotkeyConfig

    return Config(
        model="gpt-4o-transcribe",
        vocabulary_prompt="",
        language="en",
        sample_rate=16000,
        channels=1,
        api_key=api_key,
        hotkey=HotkeyConfig(
            chord=("control", "option", "command"),
            sound_start="",
            sound_stop="",
            sound_empty="",
            sound_success="",
        ),
    )


def test_load_config_from_file(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[openai]\nmodel = "gpt-4o-transcribe"\n'
        '[transcription]\nvocabulary_prompt = "foo bar"\nlanguage = "en"\n'
        "[recording]\nsample_rate = 16000\nchannels = 1\n"
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
        "[recording]\nsample_rate = 16000\nchannels = 1\n"
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


def test_require_api_key_raises_when_neither_env_nor_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        _minimal_config(api_key=None).require_api_key()


def test_require_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert _minimal_config(api_key=None).require_api_key() == "sk-from-env"


def test_require_api_key_from_config_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _minimal_config(api_key="sk-from-config").require_api_key() == "sk-from-config"


def test_require_api_key_env_wins_over_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert _minimal_config(api_key="sk-from-config").require_api_key() == "sk-from-env"


def test_load_config_reads_optional_api_key(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[openai]\nmodel = "gpt-4o-transcribe"\napi_key = "sk-stored"\n'
        '[transcription]\nvocabulary_prompt = ""\nlanguage = "en"\n'
        "[recording]\nsample_rate = 16000\nchannels = 1\n"
    )
    assert load_config(cfg_path).api_key == "sk-stored"


def test_load_config_api_key_optional(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[openai]\nmodel = "gpt-4o-transcribe"\n'
        '[transcription]\nvocabulary_prompt = ""\nlanguage = "en"\n'
        "[recording]\nsample_rate = 16000\nchannels = 1\n"
    )
    assert load_config(cfg_path).api_key is None


# ----- resolve_config_path -----


def test_resolve_config_path_env_override_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "custom" / "config.toml"
    monkeypatch.setenv("ECHO_CONFIG", str(override))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    # Legacy presence must NOT win over an explicit override.
    legacy = tmp_path / "legacy.toml"
    legacy.write_text("")
    assert resolve_config_path(legacy_path=legacy) == override


def test_resolve_config_path_uses_xdg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ECHO_CONFIG", raising=False)
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert resolve_config_path(legacy_path=tmp_path / "no-legacy.toml") == (
        xdg / "echo" / "config.toml"
    )


def test_resolve_config_path_defaults_to_home_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ECHO_CONFIG", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    assert resolve_config_path(legacy_path=tmp_path / "no-legacy.toml") == (
        home / ".config" / "echo" / "config.toml"
    )


def test_resolve_config_path_prefers_legacy_repo_path_when_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Back-compat: if a config exists at the legacy repo location, keep using it."""
    monkeypatch.delenv("ECHO_CONFIG", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    legacy = tmp_path / "repo" / "config" / "config.toml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("")
    assert resolve_config_path(legacy_path=legacy) == legacy


# ----- HotkeyConfig -----


def _write_config_with_hotkey(tmp_path, hotkey_section: str) -> Path:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[openai]\nmodel = "gpt-4o-transcribe"\n'
        '[transcription]\nvocabulary_prompt = ""\nlanguage = "en"\n'
        "[recording]\nsample_rate = 16000\nchannels = 1\n" + hotkey_section
    )
    return cfg_path


def test_hotkey_config_defaults_when_section_missing(tmp_path: Path) -> None:
    cfg_path = _write_config_with_hotkey(tmp_path, "")
    cfg = load_config(cfg_path)
    assert cfg.hotkey.chord == ("control", "option", "command")
    assert cfg.hotkey.sound_start == "/System/Library/Sounds/Pop.aiff"
    assert cfg.hotkey.sound_stop == "/System/Library/Sounds/Tink.aiff"
    assert cfg.hotkey.sound_empty == "/System/Library/Sounds/Funk.aiff"
    assert cfg.hotkey.sound_success == "/System/Library/Sounds/Glass.aiff"


def test_hotkey_config_rejects_legacy_aliases(tmp_path: Path) -> None:
    """Old short names (ctrl/alt/cmd) are no longer supported."""
    section = '[hotkey]\nchord = ["ctrl", "alt", "cmd"]\n'
    cfg_path = _write_config_with_hotkey(tmp_path, section)
    with pytest.raises(ConfigError, match="Unknown hotkey key"):
        load_config(cfg_path)


def test_hotkey_config_parses_custom_section(tmp_path: Path) -> None:
    section = (
        '[hotkey]\nchord = ["control", "shift", "f1"]\n'
        '[hotkey.sounds]\nstart = "/tmp/a"\nstop = "/tmp/b"\nempty = ""\n'
    )
    cfg_path = _write_config_with_hotkey(tmp_path, section)
    cfg = load_config(cfg_path)
    assert cfg.hotkey.chord == ("control", "shift", "f1")
    assert cfg.hotkey.sound_start == "/tmp/a"
    assert cfg.hotkey.sound_stop == "/tmp/b"
    assert cfg.hotkey.sound_empty == ""


def test_hotkey_config_unknown_key_raises(tmp_path: Path) -> None:
    section = '[hotkey]\nchord = ["control", "wat"]\n'
    cfg_path = _write_config_with_hotkey(tmp_path, section)
    with pytest.raises(ConfigError, match="Unknown hotkey key"):
        load_config(cfg_path)


def test_hotkey_config_empty_chord_raises(tmp_path: Path) -> None:
    section = "[hotkey]\nchord = []\n"
    cfg_path = _write_config_with_hotkey(tmp_path, section)
    with pytest.raises(ConfigError, match="empty"):
        load_config(cfg_path)
