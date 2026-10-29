"""Local transcription via whisper.cpp's `whisper-cli`.

`whisper-cli -ojf` writes one JSON document per run: segments with millisecond
offsets, and per segment the decoder tokens with their own offsets and
probabilities. Tokens are sub-word pieces, so this module merges them back
into words for the timed transcript.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from echo.timed_transcript import Segment, TimedTranscript, Word


class WhisperCppError(Exception):
    """Raised when whisper-cli fails or its output can't be understood."""


_SPECIAL_TOKEN_PREFIX = "[_"


@dataclass
class _WordBuilder:
    start_ms: int
    end_ms: int
    text: str
    probabilities: list[float] = field(default_factory=list)

    def build(self) -> Word:
        return Word(
            start=self.start_ms / 1000,
            end=self.end_ms / 1000,
            text=self.text.strip(),
            probability=min(self.probabilities),
        )


def _is_punctuation(text: str) -> bool:
    return not any(ch.isalnum() for ch in text)


def _merge_tokens(tokens: list[dict[str, Any]]) -> tuple[Word, ...]:
    """Merge sub-word tokens into words.

    A token starting with a space opens a new word; other tokens continue the
    current one. Punctuation never moves a word's timing, because whisper gives
    punctuation its own time range, which can sit after a pause, and stretching
    a word over that pause would hide it from an editor looking for silences:

    - closing punctuation (no leading space, e.g. ",") is appended to the
      previous word;
    - opening punctuation (leading space, e.g. " $", ' "') is held and prefixed
      to the next word, which keeps its own start time.

    A word's probability is the minimum over its non-punctuation tokens, so a
    single shaky token marks the whole word as shaky.
    """
    builders: list[_WordBuilder] = []
    pending_prefix = ""
    for token in tokens:
        text: str = token["text"]
        if text.startswith(_SPECIAL_TOKEN_PREFIX):
            continue

        if _is_punctuation(text):
            if text.startswith(" "):
                pending_prefix += text.strip()
            elif builders:
                builders[-1].text += text
            continue

        start_ms: int = token["offsets"]["from"]
        end_ms: int = token["offsets"]["to"]
        if text.startswith(" ") or not builders or pending_prefix:
            word_text = pending_prefix + text.lstrip() if pending_prefix else text
            builders.append(_WordBuilder(start_ms=start_ms, end_ms=end_ms, text=word_text))
            pending_prefix = ""
        else:
            builders[-1].text += text
            builders[-1].end_ms = end_ms
        builders[-1].probabilities.append(float(token["p"]))

    return tuple(b.build() for b in builders if b.text.strip())


def _parse_segment(raw: dict[str, Any]) -> Segment:
    return Segment(
        start=raw["offsets"]["from"] / 1000,
        end=raw["offsets"]["to"] / 1000,
        text=raw["text"].strip(),
        words=_merge_tokens(raw.get("tokens", [])),
    )


def parse_full_json(data: dict[str, Any], *, source: str, model: str) -> TimedTranscript:
    try:
        language = data["result"]["language"]
        raw_segments = data["transcription"]
        if not isinstance(raw_segments, list):
            raise TypeError("transcription is not a list")
        segments = tuple(_parse_segment(raw) for raw in raw_segments)
    except (KeyError, TypeError, ValueError) as e:
        raise WhisperCppError(f"unexpected whisper-cli output: {e!r}") from e

    return TimedTranscript(source=source, language=language, model=model, segments=segments)
