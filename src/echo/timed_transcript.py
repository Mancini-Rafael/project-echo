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


def to_srt(transcript: TimedTranscript) -> str:
    blocks = [
        f"{index}\n{_srt_timestamp(s.start)} --> {_srt_timestamp(s.end)}\n{s.text}\n"
        for index, s in enumerate(transcript.segments, start=1)
    ]
    return "\n".join(blocks)
