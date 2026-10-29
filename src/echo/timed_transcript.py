"""Timestamped transcript value types and their JSON / SRT serializers.

Times are seconds as floats. Serializers round to milliseconds (3 decimals),
which is the resolution whisper.cpp reports and what video editors work in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_DECIMALS = 3


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str
    probability: float

    @property
    def approx(self) -> bool:
        """True when whisper gave the word no duration, so its timing is unreliable.

        Seen on real recordings at whisper's 30 s window edges, where several
        words collapse onto the same instant. Editors shouldn't cut on these.
        """
        return self.end <= self.start


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    words: tuple[Word, ...]


@dataclass(frozen=True)
class TimedTranscript:
    source: str
    language: str
    model: str
    segments: tuple[Segment, ...]


def _round(value: float) -> float:
    return round(value, _DECIMALS)


def _word_dict(word: Word) -> dict[str, Any]:
    return {
        "start": _round(word.start),
        "end": _round(word.end),
        "text": word.text,
        "probability": _round(word.probability),
        "approx": word.approx,
    }


def _segment_dict(segment: Segment) -> dict[str, Any]:
    return {
        "start": _round(segment.start),
        "end": _round(segment.end),
        "text": segment.text,
        "words": [_word_dict(w) for w in segment.words],
    }


def to_json_dict(transcript: TimedTranscript) -> dict[str, Any]:
    return {
        "source": transcript.source,
        "language": transcript.language,
        "model": transcript.model,
        "segments": [_segment_dict(s) for s in transcript.segments],
    }


def _srt_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


# Subtitle conventions: one readable line, short enough to follow at speech
# pace, and never flashing by too fast to read.
_MAX_CUE_CHARS = 42
_MAX_CUE_SECONDS = 3.0
_MIN_CUE_SECONDS = 0.5
_SENTENCE_END = (".", "?", "!")


@dataclass(frozen=True)
class _Cue:
    start: float
    end: float
    text: str


def _word_cues(words: tuple[Word, ...]) -> list[_Cue]:
    cues: list[_Cue] = []
    group: list[Word] = []
    for word in words:
        if group:
            text = " ".join(w.text for w in [*group, word])
            too_long = len(text) > _MAX_CUE_CHARS
            too_slow = word.end - group[0].start > _MAX_CUE_SECONDS
            sentence_done = group[-1].text.endswith(_SENTENCE_END)
            if too_long or too_slow or sentence_done:
                cues.append(_Cue(group[0].start, group[-1].end, " ".join(w.text for w in group)))
                group = []
        group.append(word)
    if group:
        cues.append(_Cue(group[0].start, group[-1].end, " ".join(w.text for w in group)))
    return cues


def _cues(transcript: TimedTranscript) -> list[_Cue]:
    cues: list[_Cue] = []
    for segment in transcript.segments:
        if segment.words:
            cues.extend(_word_cues(segment.words))
        else:
            cues.append(_Cue(segment.start, segment.end, segment.text))
    # Collapsed words (see Word.approx) produce zero-length cues; stretch them
    # to stay readable, but never into the next cue.
    stretched: list[_Cue] = []
    for index, cue in enumerate(cues):
        end = max(cue.end, cue.start + _MIN_CUE_SECONDS)
        if index + 1 < len(cues):
            end = min(end, max(cue.end, cues[index + 1].start))
        stretched.append(_Cue(cue.start, end, cue.text))
    return stretched


def to_srt(transcript: TimedTranscript) -> str:
    """One cue per short run of words, falling back to the segment without words."""
    blocks = [
        f"{index}\n{_srt_timestamp(c.start)} --> {_srt_timestamp(c.end)}\n{c.text}\n"
        for index, c in enumerate(_cues(transcript), start=1)
    ]
    return "\n".join(blocks)
