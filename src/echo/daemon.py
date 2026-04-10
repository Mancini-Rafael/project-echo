"""Long-running daemon: listens for a global hotkey chord and runs the
transcribe → clipboard pipeline on toggle.

The chord callback runs on the pynput listener thread. A non-blocking
`threading.Lock` guards the state field so events arriving during
PROCESSING are dropped at the door.
"""
from __future__ import annotations

import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Literal

from echo import sounds as default_sounds
from echo.clipboard import ClipboardError, copy_to_clipboard as default_copy
from echo.config import Config
from echo.hotkey import ChordDetector, parse_chord
from echo.recorder import RecorderError, RecordingSession
from echo.transcriber import TranscriberError, transcribe as default_transcribe
from echo.ui import format_error, format_transcription


State = Literal["idle", "recording", "processing"]


class Daemon:
    def __init__(
        self,
        *,
        config: Config,
        openai_client: Any,
        session_factory: Callable[[], RecordingSession] | None = None,
        transcribe_fn: Callable[..., str] = default_transcribe,
        copy_fn: Callable[[str], None] = default_copy,
        sounds_module=default_sounds,
        paste_fn: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._client = openai_client
        self._session_factory = session_factory or (
            lambda: RecordingSession(
                sample_rate=config.sample_rate, channels=config.channels
            )
        )
        self._transcribe = transcribe_fn
        self._copy = copy_fn
        self._sounds = sounds_module
        self._paste_fn = paste_fn

        self._state: State = "idle"
        self._lock = threading.Lock()
        self._session: RecordingSession | None = None
        self._stop_event = threading.Event()

    @property
    def state(self) -> State:
        return self._state

    def _make_wav_path(self) -> Path:
        return Path(f"/tmp/echo-{int(time.time() * 1000)}.wav")

    # ----- chord callback -----

    def on_chord(self) -> None:
        if not self._lock.acquire(blocking=False):
            return  # another callback is mid-processing
        try:
            current = self._state
            if current == "idle":
                self._state = "recording"
            elif current == "recording":
                self._state = "processing"
            else:  # processing
                return
        finally:
            self._lock.release()

        try:
            if current == "idle":
                self._handle_start()
            elif current == "recording":
                self._handle_stop()
        except Exception as e:
            sys.stderr.write(format_error(f"chord callback failed: {e}") + "\n")
            self._sounds.play(self._config.hotkey.sound_empty)
            with self._lock:
                self._state = "idle"
                self._session = None

    def _handle_start(self) -> None:
        self._sounds.play(self._config.hotkey.sound_start)
        try:
            session = self._session_factory()
            session.start()
        except RecorderError as e:
            sys.stderr.write(format_error(str(e)) + "\n")
            self._sounds.play(self._config.hotkey.sound_empty)
            with self._lock:
                self._state = "idle"
                self._session = None
            return
        self._session = session

    def _handle_stop(self) -> None:
        wav_path = self._make_wav_path()
        session = self._session
        self._session = None
        try:
            if session is None:
                # Defensive: should never happen given the state machine.
                self._sounds.play(self._config.hotkey.sound_empty)
                return

            try:
                recording = session.stop(wav_path)
            except RecorderError as e:
                sys.stderr.write(format_error(str(e)) + "\n")
                self._sounds.play(self._config.hotkey.sound_empty)
                return

            self._sounds.play(self._config.hotkey.sound_stop)

            try:
                text = self._transcribe(
                    client=self._client,
                    wav_path=recording.wav_path,
                    model=self._config.model,
                    vocabulary_prompt=self._config.vocabulary_prompt,
                    language=self._config.language,
                )
            except TranscriberError as e:
                sys.stderr.write(format_error(str(e)) + "\n")
                sys.stderr.write(f"  WAV kept at: {wav_path}\n")
                self._sounds.play(self._config.hotkey.sound_empty)
                return

            if not text:
                sys.stderr.write(
                    format_error("transcription empty; clipboard unchanged") + "\n"
                )
                self._sounds.play(self._config.hotkey.sound_empty)
                wav_path.unlink(missing_ok=True)
                return

            sys.stderr.write(format_transcription(text) + "\n")
            try:
                self._copy(text)
            except ClipboardError as e:
                sys.stderr.write(format_error(str(e)) + "\n")
                sys.stderr.write(f"  WAV kept at: {wav_path}\n")
                self._sounds.play(self._config.hotkey.sound_empty)
                return

            self._sounds.play(self._config.hotkey.sound_success)

            if self._paste_fn is not None:
                try:
                    self._paste_fn()
                except ClipboardError as e:
                    sys.stderr.write(format_error(f"auto-paste failed: {e}") + "\n")

            wav_path.unlink(missing_ok=True)
        finally:
            with self._lock:
                self._state = "idle"

    # ----- lifecycle -----

    def request_stop(self, *_: Any) -> None:
        self._stop_event.set()

    def run(self) -> int:
        # Validate sound files at startup; replace missing with "" + warn.
        validated = self._sounds.validate_paths(
            {
                "start": self._config.hotkey.sound_start,
                "stop": self._config.hotkey.sound_stop,
                "empty": self._config.hotkey.sound_empty,
                "success": self._config.hotkey.sound_success,
            }
        )
        from dataclasses import replace
        from echo.config import HotkeyConfig

        new_hotkey = HotkeyConfig(
            chord=self._config.hotkey.chord,
            sound_start=validated["start"],
            sound_stop=validated["stop"],
            sound_empty=validated["empty"],
            sound_success=validated["success"],
        )
        self._config = replace(self._config, hotkey=new_hotkey)

        # Build the chord detector.
        slots = parse_chord(list(self._config.hotkey.chord))
        detector = ChordDetector(slots=slots, on_pressed=self.on_chord)

        # Lazy-import pynput so unit tests don't need it loaded into the
        # daemon module by default — and so import errors surface here with
        # context, not at module-load time.
        from pynput import keyboard as pyn_keyboard

        listener = pyn_keyboard.Listener(
            on_press=detector.on_press,
            on_release=detector.on_release,
        )
        try:
            listener.start()
        except Exception as e:
            sys.stderr.write(
                format_error(
                    f"Failed to start global hotkey listener: {e}. "
                    "Grant Accessibility access to your terminal in "
                    "System Settings → Privacy & Security → Accessibility."
                )
                + "\n"
            )
            return 1

        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        chord_label = "+".join(self._config.hotkey.chord)
        sys.stderr.write(
            f"✓ Listening for {chord_label} chord. Press Ctrl-C to quit.\n"
        )

        try:
            self._stop_event.wait()
        finally:
            listener.stop()
            if self._session is not None:
                try:
                    self._session.stop(self._make_wav_path())
                except RecorderError:
                    pass
                self._session = None

        sys.stderr.write("daemon stopped\n")
        return 0
