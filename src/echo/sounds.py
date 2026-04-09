"""Non-blocking sound playback via macOS `afplay`.

`play(path)` spawns afplay in the background. Empty paths and missing files
are no-ops. Errors invoking afplay are caught and logged but never raised —
audio cues must never crash the daemon.

`validate_paths(paths)` is called once at startup. It returns a copy of the
input dict with any missing-file entries replaced by "" and prints a warning
for each.
"""
from __future__ import annotations

import os
import subprocess
import sys


def play(path: str) -> None:
    if not path or not os.path.isfile(path):
        return
    try:
        subprocess.Popen(
            ["afplay", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError) as e:
        sys.stderr.write(f"warning: afplay invocation failed: {e}\n")


def validate_paths(paths: dict[str, str]) -> dict[str, str]:
    validated: dict[str, str] = {}
    for name, p in paths.items():
        if not p:
            validated[name] = ""
            continue
        if os.path.isfile(p):
            validated[name] = p
        else:
            sys.stderr.write(
                f"warning: hotkey sound '{name}' file not found: {p}; cue disabled\n"
            )
            validated[name] = ""
    return validated
