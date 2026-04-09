import platform
import subprocess
from unittest.mock import MagicMock

import pytest

from echo.clipboard import ClipboardError, copy_to_clipboard


def test_copy_to_clipboard_invokes_pbcopy(mocker) -> None:
    run = mocker.patch("echo.clipboard.subprocess.run")
    run.return_value = MagicMock(returncode=0)
    copy_to_clipboard("hello world")
    run.assert_called_once()
    args, kwargs = run.call_args
    assert args[0] == ["pbcopy"]
    assert kwargs["input"] == b"hello world"
    assert kwargs["check"] is True


def test_copy_to_clipboard_raises_on_pbcopy_failure(mocker) -> None:
    mocker.patch(
        "echo.clipboard.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "pbcopy"),
    )
    with pytest.raises(ClipboardError):
        copy_to_clipboard("hi")


def test_copy_to_clipboard_raises_on_missing_pbcopy(mocker) -> None:
    mocker.patch("echo.clipboard.subprocess.run", side_effect=FileNotFoundError)
    with pytest.raises(ClipboardError, match="pbcopy"):
        copy_to_clipboard("hi")


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-only round trip")
def test_clipboard_round_trip_real_pbcopy() -> None:
    copy_to_clipboard("project-echo round trip")
    out = subprocess.run(["pbpaste"], capture_output=True, check=True)
    assert out.stdout.decode() == "project-echo round trip"
