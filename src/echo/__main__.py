"""Entry point for the `ec` command."""
from __future__ import annotations

import argparse
import select
import sys
import termios
import time
import tty
from pathlib import Path

from openai import OpenAI

from echo.clipboard import ClipboardError, copy_to_clipboard
from echo.config import Config, ConfigError, load_config
from echo.recorder import RecorderError, RecordingSession
from echo.transcriber import TranscriberError, transcribe
from echo.ui import format_error, format_recording_line, format_transcription


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "config.toml"
EXAMPLE_PATH = REPO_ROOT / "config" / "config.example.toml"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ec",
        description="Record audio, transcribe via OpenAI, copy to clipboard.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="(reserved) post-process the transcription via an LLM cleanup pass",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print per-stage timing breakdown to stderr",
    )
    return parser.parse_args(argv)


def _print_status(line: str) -> None:
    sys.stderr.write(f"\r{line}")
    sys.stderr.flush()


def _wait_for_space(session: RecordingSession) -> None:
    """Block until the user presses space, ticking a status line.

    Puts the terminal in cbreak mode so a single character is read without
    waiting for newline. Restores the terminal on exit.
    """
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


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.clean:
        sys.stderr.write(format_error("--clean is not implemented in the MVP") + "\n")
        return 2

    try:
        cfg = load_config(CONFIG_PATH, example_path=EXAMPLE_PATH)
        api_key = Config.require_api_key()
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


if __name__ == "__main__":
    raise SystemExit(main())
