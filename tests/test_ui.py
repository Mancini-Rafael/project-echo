from echo.ui import format_recording_line, format_transcription, format_error


def test_format_recording_line_zero_seconds() -> None:
    assert format_recording_line(0) == "● Recording... (press space to stop) 0:00"


def test_format_recording_line_padding() -> None:
    assert format_recording_line(5) == "● Recording... (press space to stop) 0:05"
    assert format_recording_line(65) == "● Recording... (press space to stop) 1:05"
    assert format_recording_line(600) == "● Recording... (press space to stop) 10:00"


def test_format_transcription() -> None:
    assert format_transcription("hello") == "> hello"


def test_format_error() -> None:
    assert format_error("boom") == "✗ boom"
