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
                    {
                        "start": 0.32,
                        "end": 0.4,
                        "text": "And",
                        "probability": 0.675,
                        "approx": False,
                    },
                    {
                        "start": 0.4,
                        "end": 1.235,
                        "text": "so",
                        "probability": 0.99,
                        "approx": False,
                    },
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


def test_zero_length_word_is_marked_approx() -> None:
    # Whisper sometimes collapses words onto one instant (seen at 30 s window
    # edges on real recordings); their timing must not be trusted for cuts.
    collapsed = Word(start=65.0, end=65.0, text="exactly", probability=0.9)
    normal = Word(start=64.0, end=64.5, text="basically", probability=0.9)

    assert collapsed.approx is True
    assert normal.approx is False


def test_json_marks_collapsed_word_approx() -> None:
    word = Word(start=2.0, end=2.0, text="hey", probability=0.9)
    transcript = _transcript(Segment(start=0.0, end=3.0, text="hey", words=(word,)))

    assert to_json_dict(transcript)["segments"][0]["words"][0]["approx"] is True


# ----- SRT cues built from word timings -----


def _w(text: str, start: float, end: float) -> Word:
    return Word(start=start, end=end, text=text, probability=0.9)


def _cues(srt: str) -> list[tuple[str, str]]:
    """(timing line, text) per cue."""
    blocks = [b.split("\n") for b in srt.strip().split("\n\n")]
    return [(lines[1], lines[2]) for lines in blocks]


def _segment(*words: Word) -> Segment:
    return Segment(
        start=words[0].start,
        end=words[-1].end,
        text=" ".join(w.text for w in words),
        words=words,
    )


def test_srt_splits_long_segment_at_42_characters() -> None:
    words = tuple(_w(f"word{i:02d}", i * 0.2, i * 0.2 + 0.2) for i in range(12))
    cues = _cues(to_srt(_transcript(_segment(*words))))

    assert [text for _, text in cues] == [
        "word00 word01 word02 word03 word04 word05",
        "word06 word07 word08 word09 word10 word11",
    ]
    assert cues[0][0] == "00:00:00,000 --> 00:00:01,200"
    assert cues[1][0] == "00:00:01,200 --> 00:00:02,400"


def test_srt_starts_new_cue_after_sentence_end() -> None:
    words = (_w("Done.", 0.0, 0.4), _w("Next", 0.5, 0.8), _w("one?", 0.8, 1.0), _w("Yes", 1.1, 1.3))
    cues = _cues(to_srt(_transcript(_segment(*words))))

    assert [text for _, text in cues] == ["Done.", "Next one?", "Yes"]


def test_srt_splits_cue_longer_than_3_seconds() -> None:
    words = (_w("slow", 0.0, 1.0), _w("speech", 1.5, 2.5), _w("here", 3.0, 3.5))
    cues = _cues(to_srt(_transcript(_segment(*words))))

    assert [text for _, text in cues] == ["slow speech", "here"]


def test_srt_collapsed_cue_gets_minimum_duration_without_overlap() -> None:
    words = (_w("basically", 65.0, 65.0), _w("exactly.", 65.0, 65.0), _w("The", 65.3, 65.5))
    cues = _cues(to_srt(_transcript(_segment(*words))))

    assert cues[0] == ("00:01:05,000 --> 00:01:05,300", "basically exactly.")
    assert cues[1][0] == "00:01:05,300 --> 00:01:05,800"
