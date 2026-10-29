from pathlib import Path
from unittest.mock import MagicMock

import pytest

from echo.config import Config, HotkeyConfig


@pytest.fixture
def fake_config() -> Config:
    return Config(
        model="gpt-4o-transcribe",
        vocabulary_prompt="foo",
        language="en",
        sample_rate=16000,
        channels=1,
        hotkey=HotkeyConfig(
            chord=("control", "option", "command"),
            sound_start="",
            sound_stop="",
            sound_empty="",
            sound_success="",
        ),
    )


def _patch_session_with_recording(mocker, main_mod, tmp_path: Path):
    """Patch RecordingSession so start() is a no-op and stop() returns a result."""
    fake_recording = MagicMock(wav_path=tmp_path / "clip.wav", duration_seconds=2.0)
    (tmp_path / "clip.wav").write_bytes(b"RIFF")
    fake_session = MagicMock()
    fake_session.is_recording = True
    fake_session.stop.return_value = fake_recording
    mocker.patch.object(main_mod, "RecordingSession", return_value=fake_session)
    # Skip the spacebar wait so the test runs without touching the terminal.
    mocker.patch.object(main_mod, "_wait_for_space", return_value=None)
    return fake_session, fake_recording


def test_main_happy_path(mocker, tmp_path: Path, fake_config: Config) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(Config, "require_api_key", return_value="sk-test")
    _patch_session_with_recording(mocker, main_mod, tmp_path)
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())
    mocker.patch.object(main_mod, "transcribe", return_value="hello world")
    copy = mocker.patch.object(main_mod, "copy_to_clipboard")

    exit_code = main_mod.main(argv=[])

    assert exit_code == 0
    copy.assert_called_once_with("hello world")


def test_main_missing_api_key_exits_nonzero(mocker, fake_config: Config) -> None:
    from echo import __main__ as main_mod
    from echo.config import ConfigError

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(
        Config,
        "require_api_key",
        side_effect=ConfigError("OPENAI_API_KEY not set"),
    )

    assert main_mod.main(argv=[]) != 0


def test_main_empty_transcription_does_not_copy(
    mocker, tmp_path: Path, fake_config: Config
) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(Config, "require_api_key", return_value="sk-test")
    _patch_session_with_recording(mocker, main_mod, tmp_path)
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())
    mocker.patch.object(main_mod, "transcribe", return_value="")
    copy = mocker.patch.object(main_mod, "copy_to_clipboard")

    exit_code = main_mod.main(argv=[])

    assert exit_code != 0
    copy.assert_not_called()


def test_main_clean_flag_not_implemented(mocker, fake_config: Config) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(Config, "require_api_key", return_value="sk-test")

    assert main_mod.main(argv=["--clean"]) != 0


# ----- subcommand dispatch -----


def test_main_listen_constructs_and_runs_daemon(mocker, fake_config: Config) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(Config, "require_api_key", return_value="sk-test")
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())

    fake_daemon = MagicMock()
    fake_daemon.run.return_value = 0
    mocker.patch.object(main_mod, "Daemon", return_value=fake_daemon)

    # Stub out PID file lifecycle so we don't touch /tmp.
    mocker.patch.object(main_mod, "_acquire_pid_file")
    mocker.patch.object(main_mod, "_release_pid_file")

    exit_code = main_mod.main(argv=["listen"])
    assert exit_code == 0
    fake_daemon.run.assert_called_once()


def test_main_stop_with_no_pid_file(mocker, tmp_path: Path) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "PID_FILE", tmp_path / "echo-daemon.pid")
    exit_code = main_mod.main(argv=["stop"])
    assert exit_code == 0


def test_main_stop_sends_sigterm_when_alive(mocker, tmp_path: Path) -> None:
    from echo import __main__ as main_mod

    pid_file = tmp_path / "echo-daemon.pid"
    pid_file.write_text("12345")
    mocker.patch.object(main_mod, "PID_FILE", pid_file)
    kill = mocker.patch.object(main_mod.os, "kill")
    # First call: SIGTERM. Second call: poll alive. Third call: poll dead.
    kill.side_effect = [None, None, ProcessLookupError]
    exit_code = main_mod.main(argv=["stop"])
    assert exit_code == 0
    # SIGTERM was sent first.
    assert kill.call_args_list[0][0][1] == 15  # signal.SIGTERM


def test_main_listen_refuses_when_pid_file_exists_and_alive(
    mocker, tmp_path: Path, fake_config: Config
) -> None:
    from echo import __main__ as main_mod

    pid_file = tmp_path / "echo-daemon.pid"
    pid_file.write_text("12345")
    mocker.patch.object(main_mod, "PID_FILE", pid_file)
    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(Config, "require_api_key", return_value="sk-test")
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())
    mocker.patch.object(main_mod.os, "kill", return_value=None)  # process is "alive"

    exit_code = main_mod.main(argv=["listen"])
    assert exit_code == 1


def test_main_listen_cleans_stale_pid_file(mocker, tmp_path: Path, fake_config: Config) -> None:
    from echo import __main__ as main_mod

    pid_file = tmp_path / "echo-daemon.pid"
    pid_file.write_text("12345")
    mocker.patch.object(main_mod, "PID_FILE", pid_file)
    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(Config, "require_api_key", return_value="sk-test")
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())
    mocker.patch.object(main_mod.os, "kill", side_effect=ProcessLookupError)

    fake_daemon = MagicMock()
    fake_daemon.run.return_value = 0
    mocker.patch.object(main_mod, "Daemon", return_value=fake_daemon)

    exit_code = main_mod.main(argv=["listen"])
    assert exit_code == 0
    # The PID file should have been cleaned up at end (released).
    assert not pid_file.exists()


# ----- ec video -----


def _transcript():
    from echo.timed_transcript import Segment, TimedTranscript, Word

    return TimedTranscript(
        source="clip.mp4",
        language="en",
        model="ggml-base.bin",
        segments=(
            Segment(
                start=0.0,
                end=1.0,
                text="hello",
                words=(Word(start=0.1, end=0.5, text="hello", probability=0.9),),
            ),
        ),
    )


@pytest.fixture
def video_env(mocker, tmp_path: Path, fake_config: Config):
    """A video file, a model file, and every external boundary mocked."""
    import dataclasses

    from echo import __main__ as main_mod

    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"model")
    config = dataclasses.replace(
        fake_config,
        local_whisper=dataclasses.replace(fake_config.local_whisper, model_path=model),
    )
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00")
    # Keep the temp WAV inside tmp_path instead of the real system temp dir.
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    mocker.patch.object(main_mod.tempfile, "tempdir", str(temp_dir))

    mocker.patch.object(main_mod, "load_config", return_value=config)
    mocker.patch.object(main_mod.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}")
    extract = mocker.patch.object(
        main_mod, "extract_audio", side_effect=lambda _v, wav, **_k: wav.write_bytes(b"RIFF")
    )
    transcribe = mocker.patch.object(
        main_mod, "transcribe_with_timestamps", return_value=_transcript()
    )
    return main_mod, video, extract, transcribe


def test_video_writes_json_next_to_input(video_env, capsys) -> None:
    import json

    main_mod, video, _extract, _transcribe = video_env

    assert main_mod.main(argv=["video", str(video)]) == 0

    out = video.parent / "clip.transcript.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["segments"][0]["words"][0]["text"] == "hello"
    assert str(out) in capsys.readouterr().out
    assert not (video.parent / "clip.srt").exists()


def test_video_srt_flag_writes_srt(video_env) -> None:
    main_mod, video, _extract, _transcribe = video_env

    assert main_mod.main(argv=["video", str(video), "--srt"]) == 0

    assert (
        (video.parent / "clip.srt")
        .read_text()
        .startswith("1\n00:00:00,100 --> 00:00:00,600\nhello")
    )


def test_video_uses_config_language_by_default(video_env) -> None:
    main_mod, video, _extract, transcribe = video_env

    main_mod.main(argv=["video", str(video)])

    assert transcribe.call_args.kwargs["language"] == "auto"


def test_video_language_flag_overrides_config(video_env) -> None:
    main_mod, video, _extract, transcribe = video_env

    main_mod.main(argv=["video", str(video), "--language", "pt"])

    assert transcribe.call_args.kwargs["language"] == "pt"


def test_video_missing_whisper_cli_fails_before_extraction(mocker, video_env, capsys) -> None:
    main_mod, video, extract, _transcribe = video_env
    mocker.patch.object(
        main_mod.shutil, "which", side_effect=lambda n: None if n == "whisper-cli" else n
    )

    assert main_mod.main(argv=["video", str(video)]) == 1

    assert "brew install whisper-cpp" in capsys.readouterr().err
    extract.assert_not_called()


def test_video_missing_ffmpeg_fails_before_extraction(mocker, video_env, capsys) -> None:
    main_mod, video, extract, _transcribe = video_env
    mocker.patch.object(
        main_mod.shutil, "which", side_effect=lambda n: None if n == "ffmpeg" else n
    )

    assert main_mod.main(argv=["video", str(video)]) == 1

    assert "brew install ffmpeg" in capsys.readouterr().err
    extract.assert_not_called()


def test_video_missing_model_fails_before_extraction(video_env, capsys) -> None:
    main_mod, video, extract, _transcribe = video_env
    model = video.parent / "ggml-base.bin"
    model.unlink()

    assert main_mod.main(argv=["video", str(video)]) == 1

    assert str(model) in capsys.readouterr().err
    extract.assert_not_called()


def test_video_nonexistent_path_exit_2(video_env) -> None:
    main_mod, video, extract, _transcribe = video_env

    assert main_mod.main(argv=["video", str(video.parent / "missing.mp4")]) == 2
    extract.assert_not_called()


def test_video_does_not_require_openai_key(video_env, monkeypatch) -> None:
    main_mod, video, _extract, _transcribe = video_env
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert main_mod.main(argv=["video", str(video)]) == 0


def test_video_failure_keeps_previous_transcript_and_wav(video_env, capsys) -> None:
    from echo.whisper_cpp import WhisperCppError

    main_mod, video, _extract, transcribe = video_env
    previous = video.parent / "clip.transcript.json"
    previous.write_text('{"old": true}')
    transcribe.side_effect = WhisperCppError("decoder exploded")

    assert main_mod.main(argv=["video", str(video)]) == 1

    assert previous.read_text() == '{"old": true}'
    err = capsys.readouterr().err
    assert "decoder exploded" in err
    kept = Path(err.split("WAV kept at: ")[1].strip())
    assert kept.exists()


def test_video_media_error_exit_1(video_env, capsys) -> None:
    from echo.media import MediaError

    main_mod, video, extract, transcribe = video_env
    extract.side_effect = MediaError("no audio stream in clip.mp4")

    assert main_mod.main(argv=["video", str(video)]) == 1

    err = capsys.readouterr().err
    assert "no audio stream" in err
    assert "WAV kept at" not in err
    assert list((video.parent / "tmp").iterdir()) == []
    transcribe.assert_not_called()


def test_video_success_removes_temp_wav(video_env) -> None:
    main_mod, video, extract, _transcribe = video_env

    main_mod.main(argv=["video", str(video)])

    wav = extract.call_args.args[1]
    assert not wav.exists()


def test_video_rerun_overwrites_transcript(video_env) -> None:
    main_mod, video, _extract, _transcribe = video_env
    out = video.parent / "clip.transcript.json"
    out.write_text("stale")

    assert main_mod.main(argv=["video", str(video)]) == 0

    assert out.read_text() != "stale"
    assert [p.name for p in video.parent.iterdir() if p.name.startswith(".clip")] == []


def test_video_keyboard_interrupt_exit_130(video_env) -> None:
    main_mod, video, _extract, transcribe = video_env
    transcribe.side_effect = KeyboardInterrupt

    assert main_mod.main(argv=["video", str(video)]) == 130


def test_video_no_speech_still_writes_json_and_warns(video_env, capsys) -> None:
    import dataclasses

    main_mod, video, _extract, transcribe = video_env
    transcribe.return_value = dataclasses.replace(_transcript(), segments=())

    assert main_mod.main(argv=["video", str(video)]) == 0

    err = capsys.readouterr().err
    assert "warning: no speech detected" in err
    assert "✗" not in err
    assert (video.parent / "clip.transcript.json").exists()


def test_video_rerun_keeps_existing_file_permissions(video_env) -> None:
    import stat

    main_mod, video, _extract, _transcribe = video_env
    out = video.parent / "clip.transcript.json"
    out.write_text("stale")
    out.chmod(0o644)

    main_mod.main(argv=["video", str(video)])

    assert stat.S_IMODE(out.stat().st_mode) == 0o644


def test_video_new_file_uses_umask_permissions(video_env) -> None:
    import os
    import stat

    main_mod, video, _extract, _transcribe = video_env
    old = os.umask(0o022)
    try:
        main_mod.main(argv=["video", str(video)])
    finally:
        os.umask(old)

    assert stat.S_IMODE((video.parent / "clip.transcript.json").stat().st_mode) == 0o644


def _with_local_whisper(main_mod, use_vocabulary: bool) -> None:
    import dataclasses

    cfg = main_mod.load_config.return_value
    main_mod.load_config.return_value = dataclasses.replace(
        cfg,
        local_whisper=dataclasses.replace(cfg.local_whisper, use_vocabulary=use_vocabulary),
    )


def test_video_sends_vocabulary_by_default(video_env) -> None:
    main_mod, video, _extract, transcribe = video_env

    main_mod.main(argv=["video", str(video)])

    assert transcribe.call_args.kwargs["vocabulary_prompt"] == "foo"


def test_video_no_vocabulary_flag_sends_empty_prompt(video_env) -> None:
    main_mod, video, _extract, transcribe = video_env

    main_mod.main(argv=["video", str(video), "--no-vocabulary"])

    assert transcribe.call_args.kwargs["vocabulary_prompt"] == ""


def test_video_respects_config_use_vocabulary_false(video_env) -> None:
    main_mod, video, _extract, transcribe = video_env
    _with_local_whisper(main_mod, use_vocabulary=False)

    main_mod.main(argv=["video", str(video)])

    assert transcribe.call_args.kwargs["vocabulary_prompt"] == ""


def test_video_vocabulary_flag_overrides_config_false(video_env) -> None:
    main_mod, video, _extract, transcribe = video_env
    _with_local_whisper(main_mod, use_vocabulary=False)

    main_mod.main(argv=["video", str(video), "--vocabulary"])

    assert transcribe.call_args.kwargs["vocabulary_prompt"] == "foo"


# ----- dictation backend + vocabulary flags -----


def _local_ready(mocker, main_mod, config: Config, tmp_path: Path) -> Config:
    """Config whose local whisper binary and model 'exist'."""
    import dataclasses

    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"model")
    config = dataclasses.replace(
        config,
        local_whisper=dataclasses.replace(config.local_whisper, model_path=model),
    )
    mocker.patch.object(main_mod, "load_config", return_value=config)
    mocker.patch.object(main_mod.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}")
    return config


def test_oneshot_defaults_to_openai_with_vocabulary(mocker, tmp_path: Path, fake_config) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(Config, "require_api_key", return_value="sk-test")
    _patch_session_with_recording(mocker, main_mod, tmp_path)
    openai_cls = mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())
    transcribe = mocker.patch.object(main_mod, "transcribe", return_value="hi")
    mocker.patch.object(main_mod, "copy_to_clipboard")

    assert main_mod.main(argv=[]) == 0

    openai_cls.assert_called_once_with(api_key="sk-test")
    assert transcribe.call_args.kwargs["vocabulary_prompt"] == "foo"


def test_oneshot_no_vocabulary_sends_empty_prompt(mocker, tmp_path: Path, fake_config) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(Config, "require_api_key", return_value="sk-test")
    _patch_session_with_recording(mocker, main_mod, tmp_path)
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())
    transcribe = mocker.patch.object(main_mod, "transcribe", return_value="hi")
    mocker.patch.object(main_mod, "copy_to_clipboard")

    assert main_mod.main(argv=["--no-vocabulary"]) == 0

    assert transcribe.call_args.kwargs["vocabulary_prompt"] == ""


def test_oneshot_local_backend_skips_openai_and_api_key(
    mocker, tmp_path: Path, fake_config, monkeypatch
) -> None:
    from echo import __main__ as main_mod

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = _local_ready(mocker, main_mod, fake_config, tmp_path)
    _patch_session_with_recording(mocker, main_mod, tmp_path)
    openai_cls = mocker.patch.object(main_mod, "OpenAI")
    openai_transcribe = mocker.patch.object(main_mod, "transcribe")
    local_fn = MagicMock(return_value="local text")
    factory = mocker.patch.object(main_mod, "local_transcribe_fn", return_value=local_fn)
    copy = mocker.patch.object(main_mod, "copy_to_clipboard")

    assert main_mod.main(argv=["--backend", "local"]) == 0

    factory.assert_called_once_with(config.local_whisper)
    assert local_fn.call_args.kwargs["language"] == "en"
    openai_cls.assert_not_called()
    openai_transcribe.assert_not_called()
    copy.assert_called_once_with("local text")


def test_oneshot_local_backend_missing_whisper_fails_before_recording(
    mocker, tmp_path: Path, fake_config, capsys
) -> None:
    from echo import __main__ as main_mod

    _local_ready(mocker, main_mod, fake_config, tmp_path)
    mocker.patch.object(
        main_mod.shutil, "which", side_effect=lambda n: None if n == "whisper-cli" else n
    )
    session_cls = mocker.patch.object(main_mod, "RecordingSession")

    assert main_mod.main(argv=["--backend", "local"]) == 1

    assert "brew install whisper-cpp" in capsys.readouterr().err
    session_cls.assert_not_called()


def test_listen_local_backend_builds_daemon_without_openai(
    mocker, tmp_path: Path, fake_config, monkeypatch
) -> None:
    from echo import __main__ as main_mod

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config = _local_ready(mocker, main_mod, fake_config, tmp_path)
    openai_cls = mocker.patch.object(main_mod, "OpenAI")
    local_fn = MagicMock()
    mocker.patch.object(main_mod, "local_transcribe_fn", return_value=local_fn)
    daemon_cls = mocker.patch.object(main_mod, "Daemon")
    daemon_cls.return_value.run.return_value = 0
    mocker.patch.object(main_mod, "_acquire_pid_file")
    mocker.patch.object(main_mod, "_release_pid_file")

    assert main_mod.main(argv=["listen", "--backend", "local"]) == 0

    kwargs = daemon_cls.call_args.kwargs
    assert kwargs["openai_client"] is None
    assert kwargs["transcribe_fn"] is local_fn
    assert kwargs["config"].vocabulary_prompt == config.vocabulary_prompt
    openai_cls.assert_not_called()


def test_listen_no_vocabulary_blanks_prompt_for_daemon(mocker, fake_config) -> None:
    from echo import __main__ as main_mod

    mocker.patch.object(main_mod, "load_config", return_value=fake_config)
    mocker.patch.object(Config, "require_api_key", return_value="sk-test")
    mocker.patch.object(main_mod, "OpenAI", return_value=MagicMock())
    daemon_cls = mocker.patch.object(main_mod, "Daemon")
    daemon_cls.return_value.run.return_value = 0
    mocker.patch.object(main_mod, "_acquire_pid_file")
    mocker.patch.object(main_mod, "_release_pid_file")

    assert main_mod.main(argv=["listen", "--no-vocabulary"]) == 0

    kwargs = daemon_cls.call_args.kwargs
    assert kwargs["config"].vocabulary_prompt == ""
    assert kwargs["transcribe_fn"] is main_mod.transcribe


def test_backend_flag_rejects_unknown_value(capsys) -> None:
    from echo import __main__ as main_mod

    with pytest.raises(SystemExit) as exc:
        main_mod.main(argv=["--backend", "azure"])

    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
