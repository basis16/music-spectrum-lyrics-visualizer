"""Read lyrics out of audio metadata.

Priority order:

1. Synced lyrics in tags (ID3 ``SYLT`` frames, FLAC/Vorbis ``LYRICS``
   tag with LRC body, MP4 ``\\xa9lyr`` with LRC body).
2. Side-car ``.lrc`` file next to the audio file (synced).
3. Unsynced lyrics (ID3 ``USLT``, FLAC ``LYRICS`` plain text, etc.) -
   exposed as plain text only; the renderer never invents timestamps.

The result is a :class:`LyricsResult` carrying both synced and unsynced
representations, plus the source we used (useful for the UI's "where did
the lyrics come from" hint and for the application log).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from app.core.lyrics_cleaner import (
    LyricLine,
    clean_synced_lines,
    clean_unsynced,
    parse_lrc,
)
from app.utils.logger import get_logger

log = get_logger("lyrics")


@dataclass
class LyricsResult:
    synced: List[LyricLine] = field(default_factory=list)
    unsynced: List[str] = field(default_factory=list)
    source: str = "none"

    @property
    def has_synced(self) -> bool:
        return bool(self.synced)

    @property
    def has_any(self) -> bool:
        return self.has_synced or bool(self.unsynced)


def _read_sidecar(audio_path: Path) -> Optional[str]:
    """Return the contents of ``audio.lrc`` next to ``audio_path`` if any."""
    candidates = [
        audio_path.with_suffix(".lrc"),
        audio_path.with_suffix(".LRC"),
    ]
    for c in candidates:
        if c.exists():
            try:
                return c.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return None
    return None


def _looks_like_lrc(text: str) -> bool:
    return "[" in text and "]" in text and any(
        ch.isdigit() for ch in text[:200]
    )


def extract_lyrics(audio_path: str | Path) -> LyricsResult:
    """Return cleaned lyrics from ``audio_path``."""
    path = Path(audio_path)
    if not path.exists():
        return LyricsResult(source="missing")

    # Side-car .lrc wins because users explicitly drop them next to songs.
    sidecar = _read_sidecar(path)
    if sidecar and _looks_like_lrc(sidecar):
        lines = parse_lrc(sidecar)
        if lines:
            log.info("Lyrics: loaded %d synced lines from sidecar .lrc", len(lines))
            return LyricsResult(synced=lines, source="lrc-sidecar")

    # Otherwise read tags via mutagen.
    try:
        import mutagen  # local import so the app still imports w/o mutagen
        from mutagen import id3
    except ImportError:
        log.warning("mutagen not installed; cannot read embedded lyrics")
        return LyricsResult(source="no-mutagen")

    try:
        meta = mutagen.File(str(path))
    except Exception as e:  # noqa: BLE001 - mutagen has many error types
        log.warning("Lyrics: mutagen failed on %s: %s", path.name, e)
        return LyricsResult(source="error")
    if meta is None:
        return LyricsResult(source="unknown-format")

    # --- 1. SYLT (ID3 synced) ---
    sylt_pairs = _collect_sylt(meta)
    if sylt_pairs:
        cleaned = clean_synced_lines(sylt_pairs)
        if cleaned:
            log.info("Lyrics: loaded %d synced lines from ID3 SYLT", len(cleaned))
            return LyricsResult(synced=cleaned, source="id3-sylt")

    # --- 2. Synced LRC body inside USLT / generic 'lyrics' tag ---
    raw_blocks = _collect_lyrics_text(meta)
    for raw in raw_blocks:
        if _looks_like_lrc(raw):
            parsed = parse_lrc(raw)
            if parsed:
                log.info("Lyrics: loaded %d synced lines from embedded LRC body",
                         len(parsed))
                return LyricsResult(synced=parsed, source="embedded-lrc")

    # --- 3. Unsynced fallback ---
    unsynced: List[str] = []
    for raw in raw_blocks:
        unsynced.extend(clean_unsynced(raw))
    if unsynced:
        log.info("Lyrics: loaded %d unsynced lines (no timestamps)", len(unsynced))
        return LyricsResult(unsynced=unsynced, source="unsynced")

    log.info("Lyrics: no lyrics found in %s", path.name)
    return LyricsResult(source="none")


def _collect_sylt(meta) -> List[Tuple[int, str]]:
    """Return ``(ms, text)`` pairs from ID3 SYLT frames if present."""
    pairs: List[Tuple[int, str]] = []
    try:
        # mutagen.id3.ID3 tags expose SYLT frames
        frames = getattr(meta, "tags", None)
        if frames is None:
            return pairs
        # ``frames.getall`` exists on ID3 tags.
        if not hasattr(frames, "getall"):
            return pairs
        for frame in frames.getall("SYLT"):
            # Frame.text is a list of (text, timestamp_ms) tuples.
            data = getattr(frame, "text", None) or []
            # ``format`` 2 means timestamp in ms; format 1 = frames. We only
            # trust ms timestamps.
            fmt = getattr(frame, "format", 2)
            if fmt != 2:
                continue
            for item in data:
                if not isinstance(item, tuple) or len(item) != 2:
                    continue
                text, ts = item
                if isinstance(text, bytes):
                    text = text.decode("utf-8", errors="ignore")
                pairs.append((int(ts), str(text)))
    except Exception as e:  # noqa: BLE001
        log.debug("SYLT parse error: %s", e)
    return pairs


def _collect_lyrics_text(meta) -> List[str]:
    """Return any unsynced lyrics text blobs found in tags."""
    blobs: List[str] = []
    tags = getattr(meta, "tags", None)
    if tags is None:
        return blobs

    # 1. ID3 USLT
    try:
        if hasattr(tags, "getall"):
            for frame in tags.getall("USLT"):
                text = getattr(frame, "text", None)
                if isinstance(text, list):
                    for t in text:
                        if t:
                            blobs.append(str(t))
                elif text:
                    blobs.append(str(text))
    except Exception:
        pass

    # 2. Generic mappings: dict-like tags (Vorbis/FLAC, MP4, APE).
    for key in ("LYRICS", "lyrics", "UNSYNCED LYRICS", "unsyncedlyrics",
                "\u00a9lyr", "USLT::eng", "USLT::XXX"):
        try:
            val = tags[key]
        except Exception:
            continue
        if val is None:
            continue
        if isinstance(val, list):
            for v in val:
                blobs.append(str(v))
        else:
            blobs.append(str(val))

    # Deduplicate while preserving order.
    out: List[str] = []
    seen: set[str] = set()
    for b in blobs:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out


def extract_basic_metadata(audio_path: str | Path) -> dict:
    """Return a tiny metadata dict ``{title, artist, album, duration}``.

    Each value may be ``None``. Used by the UI to label the preview.
    """
    path = Path(audio_path)
    info = {"title": None, "artist": None, "album": None, "duration": None}
    try:
        import mutagen
    except ImportError:
        return info
    try:
        meta = mutagen.File(str(path), easy=True)
    except Exception:
        return info
    if meta is None:
        return info
    for key, target in (("title", "title"), ("artist", "artist"),
                         ("album", "album")):
        try:
            val = meta.get(key)
            if isinstance(val, list):
                val = val[0] if val else None
            if val:
                info[target] = str(val)
        except Exception:
            pass
    try:
        if getattr(meta, "info", None):
            info["duration"] = float(meta.info.length)
    except Exception:
        pass
    return info
