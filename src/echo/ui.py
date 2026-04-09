"""Terminal output helpers for project-echo."""
from __future__ import annotations


def format_recording_line(elapsed_seconds: int) -> str:
    minutes, seconds = divmod(int(elapsed_seconds), 60)
    return f"● Recording... (press space to stop) {minutes}:{seconds:02d}"


def format_transcription(text: str) -> str:
    return f"> {text}"


def format_error(message: str) -> str:
    return f"✗ {message}"
