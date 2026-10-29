import os
import subprocess
import sys


def test_cli_import_does_not_load_portaudio() -> None:
    # `ec video` never records, so starting the CLI must not require the
    # PortAudio system library that sounddevice loads at import time.
    env = {**os.environ, "PYNPUT_BACKEND": os.environ.get("PYNPUT_BACKEND", "dummy")}
    result = subprocess.run(
        [sys.executable, "-c", "import sys, echo.__main__; print('sounddevice' in sys.modules)"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
