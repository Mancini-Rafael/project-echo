"""Thin wrapper around macOS pbcopy."""

from __future__ import annotations

import subprocess


class ClipboardError(Exception):
    """Raised when the clipboard operation fails."""


def copy_to_clipboard(text: str) -> None:
    try:
        subprocess.run(
            ["pbcopy"],
            input=text.encode("utf-8"),
            check=True,
        )
    except FileNotFoundError as e:
        raise ClipboardError("pbcopy not found; project-echo only supports macOS") from e
    except subprocess.CalledProcessError as e:
        raise ClipboardError(f"pbcopy failed with exit code {e.returncode}") from e


def paste() -> None:
    """Simulate Cmd+V via AppleScript to paste clipboard contents."""
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to keystroke "v" using command down',
            ],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError as e:
        raise ClipboardError("osascript not found; project-echo only supports macOS") from e
    except subprocess.CalledProcessError as e:
        raise ClipboardError(f"osascript paste failed with exit code {e.returncode}") from e
