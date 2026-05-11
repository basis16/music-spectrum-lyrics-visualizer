"""Filesystem helpers shared across the app."""
from __future__ import annotations

import hashlib
import os
import random
import re
import shutil
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
BACKGROUND_EXTS = IMAGE_EXTS | VIDEO_EXTS


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def cache_dir() -> Path:
    p = project_root() / ".cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_files(folder: str | os.PathLike[str], extensions: Iterable[str],
                recursive: bool = True) -> List[Path]:
    """Return a sorted list of files inside ``folder`` matching ``extensions``."""
    folder = Path(folder)
    if not folder.exists():
        return []
    exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}
    if recursive:
        files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in exts]
    else:
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts]
    files.sort(key=lambda p: p.name.lower())
    return files


def list_audio_files(folder: str | os.PathLike[str], recursive: bool = True) -> List[Path]:
    return list_files(folder, AUDIO_EXTS, recursive=recursive)


def list_background_files(folder: str | os.PathLike[str], recursive: bool = True) -> List[Path]:
    return list_files(folder, BACKGROUND_EXTS, recursive=recursive)


def safe_filename(name: str) -> str:
    """Replace characters that are illegal on Windows filesystems."""
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if c in bad else c for c in name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "untitled"


def file_hash(path: str | os.PathLike[str], chunk: int = 1 << 20) -> str:
    """Return a short content hash; reads up to 8 chunks for speed.

    The renderer uses this to key the spectrum cache, so it doesn't need to be
    cryptographically strong, just stable.
    """
    h = hashlib.sha1()
    p = Path(path)
    size = p.stat().st_size
    h.update(str(size).encode())
    with p.open("rb") as f:
        # First chunk
        h.update(f.read(chunk))
        # Last chunk
        if size > chunk * 2:
            f.seek(-chunk, os.SEEK_END)
            h.update(f.read(chunk))
    return h.hexdigest()[:16]


def pick_background(song_path: Path, backgrounds: Sequence[Path], mode: str,
                     index: int, default: Optional[Path] = None) -> Optional[Path]:
    """Choose a background for ``song_path`` according to ``mode``.

    Modes: ``sequence``, ``match``, ``random``. Returns ``None`` if no
    background is available (caller should use a generated fallback).
    """
    if not backgrounds:
        return default
    mode = (mode or "sequence").lower()
    if mode == "sequence":
        return backgrounds[index % len(backgrounds)]
    if mode == "random":
        return random.choice(backgrounds)
    if mode == "match":
        target = song_path.stem.lower()
        for bg in backgrounds:
            if bg.stem.lower() == target:
                return bg
        return default
    return backgrounds[index % len(backgrounds)]


class TempWorkspace:
    """Context manager that creates and cleans a temporary workspace."""

    def __init__(self, prefix: str = "msvm_"):
        self._prefix = prefix
        self._path: Optional[Path] = None

    def __enter__(self) -> Path:
        self._path = Path(tempfile.mkdtemp(prefix=self._prefix))
        return self._path

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._path and self._path.exists():
            shutil.rmtree(self._path, ignore_errors=True)


def ensure_dir(path: str | os.PathLike[str]) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p
