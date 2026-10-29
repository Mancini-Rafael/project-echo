"""Local transcription via whisper.cpp's `whisper-cli`.

`whisper-cli -ojf` writes one JSON document per run: segments with millisecond
offsets, and per segment the decoder tokens with their own offsets and
probabilities. Tokens are sub-word pieces, so this module merges them back
into words for the timed transcript.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from echo.config import LocalWhisperConfig
from echo.timed_transcript import Segment, TimedTranscript, Word

Runner = Callable[..., subprocess.CompletedProcess[str]]


class WhisperCppError(Exception):
    """Raised when whisper-cli fails or its output can't be understood."""


_SPECIAL_TOKEN_PREFIX = "[_"
# whisper-cli prints its full usage text on most errors; keep only the tail.
_STDERR_TAIL_CHARS = 2000


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


# ----- running whisper-cli -----


def build_command(
    config: LocalWhisperConfig, wav_path: Path, out_base: Path, language: str, prompt: str
) -> list[str]:
    argv = [
        config.binary,
        "-m",
        str(config.model_path),
        "-f",
        str(wav_path),
        "-l",
        language,
        "-ojf",
        "-of",
        str(out_base),
        "--no-prints",
    ]
    # Whisper treats the prompt as text that came *before* the audio, not as an
    # instruction, so it carries the vocabulary only (flattened to one line).
    flattened = re.sub(r"\s+", " ", prompt).strip()
    if flattened:
        argv += ["--prompt", flattened]
    return argv


def transcribe_with_timestamps(
    *,
    wav_path: Path,
    config: LocalWhisperConfig,
    language: str,
    vocabulary_prompt: str,
    source: str,
    run: Runner = subprocess.run,
) -> TimedTranscript:
    with tempfile.TemporaryDirectory(prefix="echo-whisper-") as tmp:
        out_base = Path(tmp) / "transcript"
        argv = build_command(config, wav_path, out_base, language, vocabulary_prompt)
        try:
            completed = run(argv, check=False, capture_output=True, text=True)
        except FileNotFoundError as e:
            raise WhisperCppError(
                f"{config.binary} not found. Install it with `brew install whisper-cpp` "
                "or set local_whisper.binary in your config."
            ) from e

        if completed.returncode != 0:
            tail = (completed.stderr or "").strip()[-_STDERR_TAIL_CHARS:]
            raise WhisperCppError(f"whisper-cli exited with code {completed.returncode}: {tail}")

        output = out_base.with_name(out_base.name + ".json")
        if not output.exists():
            raise WhisperCppError(f"whisper-cli produced no JSON output at {output}")
        try:
            data = json.loads(output.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise WhisperCppError(f"unexpected whisper-cli output: {e}") from e

    return parse_full_json(data, source=source, model=config.model_path.name)
