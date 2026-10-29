"""Entry point for the `ec` command — supports one-shot, daemon, and stop modes."""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import signal
import stat
import sys
import tempfile
import termios
import time
import tty
from pathlib import Path

from openai import OpenAI

from echo.clipboard import ClipboardError, copy_to_clipboard, paste
from echo.config import Config, ConfigError, load_config, resolve_config_path
from echo.daemon import Daemon
from echo.media import MediaError, extract_audio
from echo.recorder import RecorderError, RecordingSession
from echo.timed_transcript import TimedTranscript, to_json_dict, to_srt
from echo.transcriber import TranscriberError, transcribe
from echo.ui import format_error, format_recording_line, format_transcription
from echo.whisper_cpp import WhisperCppError, transcribe_with_timestamps

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = REPO_ROOT / "config" / "config.example.toml"


def _config_path() -> Path:
    """Resolve at call time so $ECHO_CONFIG / env changes are honored per-run."""
    return resolve_config_path()


# Module-level so tests can monkeypatch.
PID_FILE = Path("/tmp/echo-daemon.pid")


# ===== argparse =====


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ec",
        description="Record audio, transcribe via OpenAI, copy to clipboard.",
    )
    sub = parser.add_subparsers(dest="command")

    # Default (no subcommand): one-shot recording. Flags live on the root parser.
    parser.add_argument(
        "--clean",
        action="store_true",
        help="(reserved) post-process the transcription via an LLM cleanup pass",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="print per-stage timing breakdown to stderr"
    )

    listen_p = sub.add_parser("listen", help="Run the global hotkey daemon")
    listen_p.add_argument(
        "--verbose", action="store_true", help="print per-recording timing breakdown"
    )
    listen_p.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing PID file (kills the previous claim)",
    )
    listen_p.add_argument(
        "--auto-paste",
        action="store_true",
        default=False,
        help="simulate Cmd+V after transcription to paste into the focused app",
    )

    sub.add_parser("stop", help="Stop a running daemon")

    video_p = sub.add_parser(
        "video",
        help="Transcribe a video's audio locally with whisper.cpp (timestamped JSON)",
    )
    video_p.add_argument("path", type=Path, help="video (or audio) file to transcribe")
    video_p.add_argument(
        "--language",
        help="spoken language code (e.g. pt, en) or 'auto'; overrides local_whisper.language",
    )
    video_p.add_argument(
        "--srt", action="store_true", help="also write <name>.srt next to the input"
    )
    video_p.add_argument(
        "--verbose", action="store_true", help="print per-stage timing breakdown to stderr"
    )

    return parser


# ===== PID file helpers =====


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _acquire_pid_file(force: bool) -> None:
    if PID_FILE.exists():
        try:
            existing = int(PID_FILE.read_text().strip())
        except ValueError:
            existing = -1
        if existing > 0 and _is_alive(existing):
            if not force:
                raise ConfigError(
                    f"daemon already running (PID {existing}). "
                    "Run 'ec stop' first, or pass --force to override."
                )
            sys.stderr.write(
                f"warning: --force specified; overwriting PID file for live PID {existing}\n"
            )
        else:
            sys.stderr.write(
                f"warning: stale PID file at {PID_FILE} (PID {existing} not alive); cleaning up\n"
            )
    PID_FILE.write_text(str(os.getpid()))


def _release_pid_file() -> None:
    try:
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
            except ValueError:
                pid = -1
            if pid == os.getpid():
                PID_FILE.unlink()
    except OSError:
        pass


# ===== one-shot recording (existing behavior) =====


def _print_status(line: str) -> None:
    sys.stderr.write(f"\r{line}")
    sys.stderr.flush()


def _wait_for_space(session: RecordingSession) -> None:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    start = time.monotonic()
    last_tick = -1
    try:
        tty.setcbreak(fd)
        while session.is_recording:
            elapsed = int(time.monotonic() - start)
            if elapsed != last_tick:
                _print_status(format_recording_line(elapsed))
                last_tick = elapsed
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch = sys.stdin.read(1)
                if ch == " ":
                    return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _run_oneshot(args: argparse.Namespace) -> int:
    if args.clean:
        sys.stderr.write(format_error("--clean is not implemented in the MVP") + "\n")
        return 2

    try:
        cfg = load_config(_config_path(), example_path=EXAMPLE_PATH)
        api_key = cfg.require_api_key()
    except ConfigError as e:
        sys.stderr.write(format_error(str(e)) + "\n")
        return 1

    timings: dict[str, float] = {}
    wav_path = Path(f"/tmp/echo-{int(time.time())}.wav")
    session = RecordingSession(sample_rate=cfg.sample_rate, channels=cfg.channels)

    try:
        t0 = time.monotonic()
        try:
            session.start()
        except RecorderError as e:
            sys.stderr.write(format_error(str(e)) + "\n")
            return 1
        _wait_for_space(session)
        try:
            recording = session.stop(wav_path)
        except RecorderError as e:
            sys.stderr.write("\n" + format_error(str(e)) + "\n")
            return 1
        sys.stderr.write("\n")
        timings["record"] = time.monotonic() - t0
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        if session.is_recording:
            try:
                session.stop(wav_path)
            except RecorderError:
                pass
        if wav_path.exists():
            wav_path.unlink(missing_ok=True)
        return 130

    sys.stderr.write("✓ Transcribing...\n")

    try:
        t1 = time.monotonic()
        client = OpenAI(api_key=api_key)
        text = transcribe(
            client=client,
            wav_path=recording.wav_path,
            model=cfg.model,
            vocabulary_prompt=cfg.vocabulary_prompt,
            language=cfg.language,
        )
        timings["transcribe"] = time.monotonic() - t1
    except TranscriberError as e:
        sys.stderr.write(format_error(str(e)) + "\n")
        sys.stderr.write(f"  WAV kept at: {wav_path}\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write(f"\n  WAV kept at: {wav_path}\n")
        return 130

    if not text:
        sys.stderr.write(format_error("transcription empty; clipboard unchanged") + "\n")
        wav_path.unlink(missing_ok=True)
        return 1

    print(format_transcription(text))

    try:
        copy_to_clipboard(text)
        sys.stderr.write("✓ Copied to clipboard.\n")
    except ClipboardError as e:
        sys.stderr.write(format_error(f"{e} (transcription printed above)") + "\n")
        return 1

    wav_path.unlink(missing_ok=True)

    if args.verbose:
        sys.stderr.write(
            f"  timings: record={timings.get('record', 0):.2f}s "
            f"transcribe={timings.get('transcribe', 0):.2f}s "
            f"recording_duration={recording.duration_seconds:.2f}s\n"
        )

    return 0


# ===== ec listen =====


def _run_listen(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(_config_path(), example_path=EXAMPLE_PATH)
        api_key = cfg.require_api_key()
    except ConfigError as e:
        sys.stderr.write(format_error(str(e)) + "\n")
        return 1

    try:
        _acquire_pid_file(force=args.force)
    except ConfigError as e:
        sys.stderr.write(format_error(str(e)) + "\n")
        return 1

    try:
        client = OpenAI(api_key=api_key)
        paste_fn = paste if args.auto_paste else None
        daemon = Daemon(config=cfg, openai_client=client, paste_fn=paste_fn)
        return daemon.run()
    finally:
        _release_pid_file()


# ===== ec stop =====


def _run_stop() -> int:
    if not PID_FILE.exists():
        sys.stderr.write("no daemon running\n")
        return 0
    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        sys.stderr.write("warning: PID file is corrupt; removing\n")
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return 0

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        sys.stderr.write("warning: PID file pointed to a dead process; cleaning up\n")
        try:
            PID_FILE.unlink()
        except OSError:
            pass
        return 0

    # Poll for up to 2 seconds.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            try:
                PID_FILE.unlink()
            except OSError:
                pass
            sys.stderr.write("daemon stopped\n")
            return 0
        time.sleep(0.1)

    # Still alive — escalate.
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        PID_FILE.unlink()
    except OSError:
        pass
    sys.stderr.write("daemon stopped (SIGKILL)\n")
    return 0


# ===== ec video =====


def _target_mode(path: Path) -> int:
    if path.exists():
        return stat.S_IMODE(path.stat().st_mode)
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def _write_atomic(path: Path, text: str) -> None:
    """Write via a temp file in the same directory + os.replace.

    A crash or Ctrl-C mid-write leaves the previous file intact instead of a
    half-written transcript an editing tool would then choke on.
    """
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        # mkstemp creates 0600 files; keep the mode a plain write would have had.
        os.chmod(tmp_name, _target_mode(path))
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _video_preflight(cfg: Config) -> str | None:
    """Return an actionable error before spending minutes on extraction, or None."""
    local = cfg.local_whisper
    if shutil.which(local.binary) is None:
        return (
            f"{local.binary} not found. Install it with `brew install whisper-cpp` "
            "or set local_whisper.binary in your config."
        )
    if not local.model_path.is_file():
        return (
            f"whisper model not found at {local.model_path}. Download a ggml model there "
            "or set local_whisper.model_path in your config."
        )
    if shutil.which("ffmpeg") is None:
        return "ffmpeg not found. Install it with `brew install ffmpeg`."
    return None


def _write_video_outputs(video: Path, transcript: TimedTranscript, *, srt: bool) -> list[Path]:
    json_path = video.with_name(f"{video.stem}.transcript.json")
    _write_atomic(json_path, json.dumps(to_json_dict(transcript), ensure_ascii=False, indent=2))
    written = [json_path]
    if srt:
        srt_path = video.with_name(f"{video.stem}.srt")
        _write_atomic(srt_path, to_srt(transcript))
        written.append(srt_path)
    return written


def _keep_or_discard_wav(wav_path: Path, extracted: bool) -> None:
    """Keep the extracted audio for retries/debugging; drop a partial one."""
    if extracted:
        sys.stderr.write(f"  WAV kept at: {wav_path}\n")
    else:
        wav_path.unlink(missing_ok=True)


def _run_video(args: argparse.Namespace) -> int:
    video: Path = args.path.expanduser()
    if not video.is_file():
        sys.stderr.write(format_error(f"file not found: {video}") + "\n")
        return 2

    try:
        cfg = load_config(_config_path(), example_path=EXAMPLE_PATH)
    except ConfigError as e:
        sys.stderr.write(format_error(str(e)) + "\n")
        return 1

    problem = _video_preflight(cfg)
    if problem:
        sys.stderr.write(format_error(problem) + "\n")
        return 1

    fd, wav_name = tempfile.mkstemp(prefix="echo-video-", suffix=".wav")
    os.close(fd)
    wav_path = Path(wav_name)
    language = args.language or cfg.local_whisper.language

    extracted = False
    try:
        sys.stderr.write(f"✓ Extracting audio from {video.name}...\n")
        t0 = time.monotonic()
        extract_audio(video, wav_path)
        extracted = True
        t1 = time.monotonic()
        sys.stderr.write(f"✓ Transcribing locally ({cfg.local_whisper.model_path.name})...\n")
        transcript = transcribe_with_timestamps(
            wav_path=wav_path,
            config=cfg.local_whisper,
            language=language,
            vocabulary_prompt=cfg.vocabulary_prompt,
            source=video.name,
        )
        t2 = time.monotonic()
        written = _write_video_outputs(video, transcript, srt=args.srt)
    except (MediaError, WhisperCppError, OSError) as e:
        sys.stderr.write(format_error(str(e)) + "\n")
        _keep_or_discard_wav(wav_path, extracted)
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\n")
        _keep_or_discard_wav(wav_path, extracted)
        return 130

    wav_path.unlink(missing_ok=True)
    if not transcript.segments:
        sys.stderr.write("warning: no speech detected; wrote an empty transcript\n")
    for path in written:
        print(path)

    if args.verbose:
        sys.stderr.write(
            f"  timings: extract={t1 - t0:.2f}s transcribe={t2 - t1:.2f}s "
            f"segments={len(transcript.segments)} language={transcript.language}\n"
        )
    return 0


# ===== entry point =====


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "listen":
        return _run_listen(args)
    if args.command == "stop":
        return _run_stop()
    if args.command == "video":
        return _run_video(args)
    return _run_oneshot(args)


if __name__ == "__main__":
    raise SystemExit(main())
