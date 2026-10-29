from echo.timed_transcript import Segment, TimedTranscript, Word, to_json_dict, to_srt


def _transcript(*segments: Segment) -> TimedTranscript:
    return TimedTranscript(
        source="clip.mp4", language="en", model="ggml-base.bin", segments=segments
    )


def test_to_json_dict_shape() -> None:
    words = (
        Word(start=0.32, end=0.4, text="And", probability=0.675489),
        Word(start=0.4, end=1.23456, text="so", probability=0.99),
    )
    transcript = _transcript(Segment(start=0.0, end=1.23456, text="And so", words=words))

    assert to_json_dict(transcript) == {
        "source": "clip.mp4",
        "language": "en",
        "model": "ggml-base.bin",
        "segments": [
            {
                "start": 0.0,
                "end": 1.235,
                "text": "And so",
                "words": [
                    {"start": 0.32, "end": 0.4, "text": "And", "probability": 0.675},
                    {"start": 0.4, "end": 1.235, "text": "so", "probability": 0.99},
                ],
            }
        ],
    }


def test_to_json_dict_empty_segments() -> None:
    assert to_json_dict(_transcript())["segments"] == []


def test_to_srt_formats_timestamps() -> None:
    transcript = _transcript(
        Segment(start=61.5, end=63.25, text="first line", words=()),
        Segment(start=64.0, end=65.0, text="second line", words=()),
    )

    assert to_srt(transcript) == (
        "1\n00:01:01,500 --> 00:01:03,250\nfirst line\n"
        "\n"
        "2\n00:01:04,000 --> 00:01:05,000\nsecond line\n"
    )


def test_to_srt_hours() -> None:
    transcript = _transcript(Segment(start=3725.0, end=3726.0, text="late", words=()))

    assert "01:02:05,000 --> 01:02:06,000" in to_srt(transcript)


def test_to_srt_empty_transcript_is_empty_string() -> None:
    assert to_srt(_transcript()) == ""
