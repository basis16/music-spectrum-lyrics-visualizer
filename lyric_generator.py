"""Auto lyric generation.

Wraps Whisper / WhisperX so the rest of the app does not have to care which
backend is available. Returns a normalised :class:`LyricsTrack` containing
segments and (when possible) per-word timestamps.

Whisper is OPTIONAL - we import it lazily so the app still launches on systems
without the dependency. Callers can also supply a manual ``.lrc``/``.srt`` file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from logger_manager import get_logger

log = get_logger(__name__)


@dataclass
class WordTiming:
    text: str
    start: float
    end: float


@dataclass
class LyricLine:
    text: str
    start: float
    end: float
    words: List[WordTiming] = field(default_factory=list)


@dataclass
class LyricsTrack:
    lines: List[LyricLine]
    language: Optional[str] = None
    source: str = "manual"   # "whisper" / "whisperx" / "manual" / "lrc" / "srt"

    def __bool__(self) -> bool:
        return bool(self.lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate(audio_path: str | Path,
             *,
             prefer_whisperx: bool = True,
             model_size: str = "base",
             progress: Optional[Callable[[str], None]] = None,
             ) -> LyricsTrack:
    """Run automatic transcription on ``audio_path``.

    Returns an empty :class:`LyricsTrack` if no Whisper backend is available.
    """
    audio_path = str(audio_path)

    # 1) Try WhisperX (gives word-level alignment).
    if prefer_whisperx:
        try:
            return _generate_whisperx(audio_path, model_size, progress)
        except _BackendUnavailable as exc:
            log.info("WhisperX unavailable: %s", exc)
        except Exception as exc:
            log.warning("WhisperX failed: %s", exc)

    # 2) Fall back to plain Whisper.
    try:
        return _generate_whisper(audio_path, model_size, progress)
    except _BackendUnavailable as exc:
        log.info("Whisper unavailable: %s", exc)
    except Exception as exc:
        log.warning("Whisper failed: %s", exc)

    log.warning("No transcription backend available. Returning empty lyrics.")
    return LyricsTrack(lines=[], source="none")


class _BackendUnavailable(RuntimeError):
    pass


def _say(progress: Optional[Callable[[str], None]], msg: str) -> None:
    log.info(msg)
    if progress:
        try:
            progress(msg)
        except Exception:
            pass


def _generate_whisperx(audio_path: str, model_size: str,
                       progress: Optional[Callable[[str], None]]) -> LyricsTrack:
    try:
        import whisperx  # type: ignore
    except Exception as exc:
        raise _BackendUnavailable(f"whisperx not installed ({exc})")

    _say(progress, "Loading WhisperX model...")
    device = "cpu"
    model = whisperx.load_model(model_size, device, compute_type="int8")
    _say(progress, "Transcribing with WhisperX...")
    result = model.transcribe(audio_path)
    language = result.get("language")

    align_model, metadata = whisperx.load_align_model(language_code=language, device=device)
    _say(progress, "Forced alignment (word-level)...")
    aligned = whisperx.align(result["segments"], align_model, metadata,
                             audio_path, device=device, return_char_alignments=False)

    lines: List[LyricLine] = []
    for seg in aligned.get("segments", []):
        words: List[WordTiming] = []
        for w in seg.get("words", []) or []:
            try:
                words.append(WordTiming(
                    text=str(w.get("word", "")).strip(),
                    start=float(w.get("start", 0.0)),
                    end=float(w.get("end", 0.0)),
                ))
            except Exception:
                continue
        if not words:
            continue
        lines.append(LyricLine(
            text=" ".join(w.text for w in words).strip(),
            start=float(seg.get("start", words[0].start)),
            end=float(seg.get("end", words[-1].end)),
            words=words,
        ))
    return LyricsTrack(lines=lines, language=language, source="whisperx")


def _generate_whisper(audio_path: str, model_size: str,
                      progress: Optional[Callable[[str], None]]) -> LyricsTrack:
    try:
        import whisper  # type: ignore
    except Exception as exc:
        raise _BackendUnavailable(f"whisper not installed ({exc})")

    _say(progress, "Loading Whisper model...")
    model = whisper.load_model(model_size)
    _say(progress, "Transcribing with Whisper (word_timestamps=True)...")
    result = model.transcribe(audio_path, word_timestamps=True, verbose=False)
    lines: List[LyricLine] = []
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        words: List[WordTiming] = []
        for w in seg.get("words", []) or []:
            try:
                words.append(WordTiming(
                    text=str(w.get("word", "")).strip(),
                    start=float(w.get("start", 0.0)),
                    end=float(w.get("end", 0.0)),
                ))
            except Exception:
                continue
        # Whisper without word timestamps: distribute proportionally below.
        if not words:
            words = _estimate_word_timings(text, float(seg["start"]), float(seg["end"]))
        lines.append(LyricLine(
            text=text,
            start=float(seg["start"]),
            end=float(seg["end"]),
            words=words,
        ))
    return LyricsTrack(lines=lines, language=result.get("language"), source="whisper")


# ---------------------------------------------------------------------------
# Manual subtitle files (LRC / SRT)
# ---------------------------------------------------------------------------
def load_manual(path: str | Path) -> LyricsTrack:
    """Load a hand-prepared lyrics file. Supports .lrc and .srt."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="ignore")
    if p.suffix.lower() == ".lrc":
        return _parse_lrc(text)
    if p.suffix.lower() == ".srt":
        return _parse_srt(text)
    raise ValueError(f"Unsupported lyrics format: {p.suffix}")


_LRC_LINE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)")


def _parse_lrc(text: str) -> LyricsTrack:
    raw: list[tuple[float, str]] = []
    for line in text.splitlines():
        m = _LRC_LINE.match(line.strip())
        if not m:
            continue
        minutes = int(m.group(1))
        seconds = float(m.group(2))
        body = m.group(3).strip()
        if not body:
            continue
        raw.append((minutes * 60 + seconds, body))
    raw.sort(key=lambda x: x[0])

    lines: List[LyricLine] = []
    for i, (start, body) in enumerate(raw):
        end = raw[i + 1][0] if i + 1 < len(raw) else start + 4.0
        words = _estimate_word_timings(body, start, end)
        lines.append(LyricLine(text=body, start=start, end=end, words=words))
    return LyricsTrack(lines=lines, source="lrc")


_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,\.](\d+)")


def _parse_srt(text: str) -> LyricsTrack:
    blocks = re.split(r"\n\s*\n", text.strip())
    lines: List[LyricLine] = []
    for block in blocks:
        rows = [r for r in block.splitlines() if r.strip()]
        if len(rows) < 2:
            continue
        # Find timing line (it might not be the second row if numbering differs).
        timing = next((r for r in rows if "-->" in r), None)
        if not timing:
            continue
        idx = rows.index(timing)
        body = " ".join(rows[idx + 1:]).strip()
        if not body:
            continue
        a, b = [s.strip() for s in timing.split("-->")]
        start = _srt_to_seconds(a)
        end = _srt_to_seconds(b)
        if start is None or end is None:
            continue
        words = _estimate_word_timings(body, start, end)
        lines.append(LyricLine(text=body, start=start, end=end, words=words))
    return LyricsTrack(lines=lines, source="srt")


def _srt_to_seconds(s: str) -> Optional[float]:
    m = _SRT_TIME.match(s)
    if not m:
        return None
    h, mi, se, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(se) + int(ms) / 1000.0


# ---------------------------------------------------------------------------
# Heuristic word timing
# ---------------------------------------------------------------------------
def _estimate_word_timings(text: str, start: float, end: float) -> List[WordTiming]:
    """Distribute ``text`` words proportionally between ``start`` and ``end``.

    Used as a fallback when the transcription model only gives line timings.
    Word durations are weighted by character length so longer words take
    proportionally more time, which feels more natural for karaoke sweep.
    """
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    if not words or end <= start:
        return [WordTiming(text=text, start=start, end=max(end, start + 0.5))]
    # weights = max(1, len(word stripped of punctuation))
    weights = [max(1, len(re.sub(r"[^\w]", "", w))) for w in words]
    total = float(sum(weights))
    duration = end - start
    out: List[WordTiming] = []
    cursor = start
    for w, weight in zip(words, weights):
        dur = duration * (weight / total)
        out.append(WordTiming(text=w, start=cursor, end=cursor + dur))
        cursor += dur
    # Snap last word's end to segment end.
    out[-1].end = end
    return out
