import json
from pathlib import Path
from typing import Any

import pytest

from echo.timed_transcript import Word
from echo.whisper_cpp import WhisperCppError, parse_full_json

# Real `whisper-cli -ojf` output (whisper.cpp e4acdfd, ggml-base) for the
# public-domain JFK sample from the whisper.cpp repo, played twice with 2 s of
# silence in between. Trimmed to the `result` and `transcription` keys.
FIXTURE = Path(__file__).parent / "fixtures" / "whisper_cli_full.json"
JFK_TEXT = (
    "And so my fellow Americans ask not what your country can do for you, "
    "ask what you can do for your country."
)


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def _token(text: str, start_ms: int, end_ms: int, p: float = 0.9) -> dict[str, Any]:
    return {"text": text, "offsets": {"from": start_ms, "to": end_ms}, "p": p}


def _one_segment(*tokens: dict[str, Any]) -> dict[str, Any]:
    return {
        "result": {"language": "en"},
        "transcription": [
            {"offsets": {"from": 0, "to": 5000}, "text": " x", "tokens": list(tokens)}
        ],
    }


def _parse(data: dict[str, Any]):
    return parse_full_json(data, source="clip.mp4", model="ggml-base.bin")


def test_parses_fixture_segments() -> None:
    transcript = _parse(_fixture())

    assert transcript.language == "en"
    assert transcript.source == "clip.mp4"
    assert transcript.model == "ggml-base.bin"
    assert len(transcript.segments) == 2
    first, second = transcript.segments
    assert (first.start, first.end, first.text) == (0.0, 10.5, JFK_TEXT)
    assert (second.start, second.end) == (13.0, 23.5)
    assert len(first.words) == 22
    assert first.words[0] == Word(start=0.32, end=0.4, text="And", probability=0.614265)


def test_fixture_punctuation_does_not_extend_word_end() -> None:
    words = _parse(_fixture()).segments[0].words

    you = next(w for w in words if w.text == "you,")
    assert (you.start, you.end, you.probability) == (7.26, 7.49, 0.991)
    assert words[-1] == Word(start=10.02, end=10.35, text="country.", probability=0.998106)


def test_merges_subword_tokens_into_one_word() -> None:
    data = _one_segment(
        _token(" un", 100, 200, p=0.9),
        _token("believ", 200, 300, p=0.5),
        _token("able", 300, 450, p=0.8),
    )

    assert _parse(data).segments[0].words == (
        Word(start=0.1, end=0.45, text="unbelievable", probability=0.5),
    )


def test_skips_special_tokens() -> None:
    data = _one_segment(
        _token("[_BEG_]", 0, 0), _token(" hi", 100, 200), _token("[_TT_25]", 500, 500)
    )

    assert [w.text for w in _parse(data).segments[0].words] == ["hi"]


def test_punctuation_attaches_to_previous_word() -> None:
    data = _one_segment(_token(" hello", 100, 200, p=0.9), _token(",", 900, 1000, p=0.1))

    assert _parse(data).segments[0].words == (
        Word(start=0.1, end=0.2, text="hello,", probability=0.9),
    )


def test_leading_punctuation_without_previous_word_is_dropped() -> None:
    data = _one_segment(_token("...", 0, 100), _token(" ok", 100, 200))

    assert [w.text for w in _parse(data).segments[0].words] == ["ok"]


def test_empty_transcription_returns_no_segments() -> None:
    transcript = _parse({"result": {"language": "en"}, "transcription": []})

    assert transcript.segments == ()
    assert transcript.language == "en"


@pytest.mark.parametrize(
    "data",
    [
        {"result": {"language": "en"}},
        {"transcription": []},
        {"result": {"language": "en"}, "transcription": [{"text": " no offsets"}]},
        {"result": {"language": "en"}, "transcription": "nope"},
    ],
)
def test_malformed_json_raises(data: dict[str, Any]) -> None:
    with pytest.raises(WhisperCppError, match="unexpected whisper-cli output"):
        _parse(data)


def test_spaced_opening_punctuation_prefixes_next_word_without_stretching() -> None:
    # Real whisper tokenization for "costs $100" after a pause: " $" carries a
    # leading space and its own time range. It must not glue onto "costs".
    data = _one_segment(
        _token(" costs", 0, 400, p=0.9),
        _token(" $", 1500, 1600, p=0.4),
        _token("100", 1600, 2000, p=0.8),
    )

    assert _parse(data).segments[0].words == (
        Word(start=0.0, end=0.4, text="costs", probability=0.9),
        Word(start=1.6, end=2.0, text="$100", probability=0.8),
    )


def test_spaced_opening_quote_at_segment_end_is_dropped() -> None:
    data = _one_segment(_token(" hi", 0, 100), _token(' "', 200, 300))

    assert [w.text for w in _parse(data).segments[0].words] == ["hi"]
