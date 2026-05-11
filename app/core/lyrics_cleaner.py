"""Lyrics cleaning rules.

The cleaner has two responsibilities:

* Strip bracketed annotations such as ``[chorus]`` or ``(intro)`` from the
  *visible text* of a lyric line.
* Recognise LRC metadata tags like ``[ar:Artist]`` / ``[ti:Title]`` and
  refuse to surface them as lyric text.

It never touches the timestamps and never invents new ones — when a line
has no payload after cleaning, it is dropped (so it never shows up as an
empty subtitle on screen).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# LRC metadata tag keys that should never be rendered as lyrics.
_LRC_META_KEYS = {
    "ar", "ti", "al", "by", "au", "length", "offset", "re", "ve", "lang",
    "encoding", "tool",
}

# [00:12.50] or [01:02:03.456]
_TS_RE = re.compile(r"^\s*\[\s*(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\s*\]\s*")
# Inline annotations: square or round brackets (non-nested).
_BRACKETS_RE = re.compile(r"\[[^\[\]\n]*\]|\([^\(\)\n]*\)")


@dataclass
class LyricLine:
    """A timestamped lyric line ready for rendering."""

    time_ms: int  # absolute time, 0 means "from the start of the song"
    text: str

    def __post_init__(self) -> None:
        # Defensive: never let negative times leak through.
        if self.time_ms < 0:
            self.time_ms = 0


def _parse_timestamp(token: str) -> Optional[int]:
    """Parse an ``[mm:ss.xx]`` style timestamp into milliseconds."""
    m = _TS_RE.match(token if token.startswith("[") else f"[{token}]")
    if not m:
        return None
    mm = int(m.group(1))
    ss = int(m.group(2))
    frac = m.group(3) or "0"
    # ``frac`` may be 1-3 digits; normalise to milliseconds.
    if len(frac) == 1:
        ms = int(frac) * 100
    elif len(frac) == 2:
        ms = int(frac) * 10
    else:
        ms = int(frac[:3])
    return mm * 60_000 + ss * 1_000 + ms


def clean_text(text: str) -> str:
    """Remove bracketed annotations and collapse whitespace."""
    if not text:
        return ""
    cleaned = _BRACKETS_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def is_lrc_metadata_tag(token: str) -> bool:
    """Return True if ``token`` is an LRC metadata tag like ``[ar:Foo]``.

    Only the leading tag is considered; this is not a general LRC validator.
    """
    if not token.startswith("[") or "]" not in token:
        return False
    inner = token[1: token.index("]")]
    if ":" not in inner:
        return False
    key, _, _ = inner.partition(":")
    key = key.strip().lower()
    if key in _LRC_META_KEYS:
        return True
    # Pure timestamps look like "mm:ss" and have only digits/colons/dots.
    if re.fullmatch(r"\d{1,2}:\d{1,2}(?:[.:]\d{1,3})?", inner.strip()):
        return False
    # Anything else that's "word:value" but not a known key is probably
    # metadata too, but to be safe we only filter the known set above.
    return False


def parse_lrc(text: str) -> List[LyricLine]:
    """Parse an LRC body into clean :class:`LyricLine` objects.

    * Lines with no timestamp are dropped (we never invent times).
    * Multiple timestamps on one line are expanded into separate entries.
    * Bracketed annotations inside the lyric text are removed.
    * Metadata tags such as ``[ar:Foo]`` are discarded.
    * After cleaning, empty payloads are skipped.
    """
    lines: List[LyricLine] = []
    if not text:
        return lines

    for raw in text.splitlines():
        raw = raw.rstrip()
        if not raw.strip():
            continue
        # Strip BOM if present on the first line.
        if raw.startswith("\ufeff"):
            raw = raw.lstrip("\ufeff")

        timestamps: List[int] = []
        remainder = raw
        while True:
            m = _TS_RE.match(remainder)
            if not m:
                break
            tok = remainder[: m.end()]
            if is_lrc_metadata_tag(tok.strip()):
                # Skip metadata tag; consume and continue scanning.
                remainder = remainder[m.end():]
                continue
            ts = _parse_timestamp(tok.strip())
            if ts is not None:
                timestamps.append(ts)
            remainder = remainder[m.end():]

        if not timestamps:
            # Could still be a metadata line like "[ar:Foo]" by itself.
            if is_lrc_metadata_tag(raw.strip()):
                continue
            # Plain text with no timestamp - skip; we don't fabricate times.
            continue

        payload = clean_text(remainder)
        if not payload:
            continue
        for ts in timestamps:
            lines.append(LyricLine(time_ms=ts, text=payload))

    lines.sort(key=lambda l: l.time_ms)
    return _deduplicate(lines)


def _deduplicate(lines: List[LyricLine]) -> List[LyricLine]:
    """Drop consecutive duplicate (time, text) pairs."""
    out: List[LyricLine] = []
    seen_key = None
    for ln in lines:
        key = (ln.time_ms, ln.text)
        if key == seen_key:
            continue
        out.append(ln)
        seen_key = key
    return out


def clean_synced_lines(pairs: List[tuple[int, str]]) -> List[LyricLine]:
    """Apply text cleaning to already-synced (ms, text) pairs from tags.

    Timestamps are preserved exactly. Lines whose cleaned text is empty are
    dropped so they don't render as blank captions.
    """
    out: List[LyricLine] = []
    for ts, txt in pairs:
        if ts is None or ts < 0:
            continue
        clean = clean_text(txt)
        if not clean:
            continue
        out.append(LyricLine(time_ms=int(ts), text=clean))
    out.sort(key=lambda l: l.time_ms)
    return _deduplicate(out)


def clean_unsynced(text: str) -> List[str]:
    """Return cleaned unsynced lyric lines (no timestamps).

    The caller decides whether to show this static block to the user; the
    renderer must never paste unsynced lyrics onto the video without an
    explicit user-provided start time.
    """
    if not text:
        return []
    out: List[str] = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        if is_lrc_metadata_tag(raw):
            continue
        cleaned = clean_text(raw)
        if cleaned:
            out.append(cleaned)
    return out
