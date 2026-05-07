"""FFmpeg detection and helpers.

Responsibilities:
- Detect whether ``ffmpeg`` is on PATH.
- Optionally fall back to ``imageio_ffmpeg``'s bundled binary.
- Provide a one-call online installer (Windows: ``imageio_ffmpeg`` ships an
  ffmpeg binary that we can reuse without admin rights; Linux/macOS: instructs
  the user via the OS package manager).
- Probe audio duration via ``ffprobe`` (or fall back to ``soundfile``).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from logger_manager import get_logger

log = get_logger(__name__)

# Cache for the resolved ffmpeg path.
_ffmpeg_path: Optional[str] = None


def _try_imageio_ffmpeg() -> Optional[str]:
    """Return the path to the ffmpeg binary bundled with imageio-ffmpeg, if any."""
    try:
        import imageio_ffmpeg  # type: ignore

        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and Path(path).exists():
            return path
    except Exception as exc:  # pragma: no cover - import optional
        log.debug("imageio_ffmpeg unavailable: %s", exc)
    return None


def find_ffmpeg() -> Optional[str]:
    """Return path to a working ffmpeg binary, or ``None``."""
    global _ffmpeg_path
    if _ffmpeg_path and Path(_ffmpeg_path).exists():
        return _ffmpeg_path

    # 1. PATH
    found = shutil.which("ffmpeg")
    if found:
        _ffmpeg_path = found
        log.info("FFmpeg found on PATH: %s", found)
        return found

    # 2. imageio_ffmpeg fallback
    bundled = _try_imageio_ffmpeg()
    if bundled:
        _ffmpeg_path = bundled
        log.info("Using bundled FFmpeg from imageio-ffmpeg: %s", bundled)
        return bundled

    log.warning("FFmpeg not found.")
    return None


def find_ffprobe() -> Optional[str]:
    """Locate ``ffprobe``. Most builds ship it next to ``ffmpeg``."""
    direct = shutil.which("ffprobe")
    if direct:
        return direct

    ffmpeg = find_ffmpeg()
    if ffmpeg:
        candidate = Path(ffmpeg).with_name(
            "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
        )
        if candidate.exists():
            return str(candidate)
    return None


def get_version() -> Optional[str]:
    """Return the first line of ``ffmpeg -version`` output, or ``None``."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    try:
        out = subprocess.run(
            [ffmpeg, "-version"],
            capture_output=True, text=True, timeout=5,
            check=False,
        )
        first = (out.stdout or out.stderr).splitlines()[0]
        return first.strip()
    except Exception as exc:  # pragma: no cover
        log.warning("Failed to query ffmpeg -version: %s", exc)
        return None


def install_online() -> bool:
    """Try to provision an FFmpeg binary without admin rights.

    On all platforms we try ``imageio_ffmpeg`` first - it ships a redistributable
    ffmpeg binary that pip can install in user scope. Returns True on success.
    """
    log.info("Attempting online FFmpeg install via imageio-ffmpeg...")
    try:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "imageio-ffmpeg"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            log.error("pip install failed: %s", proc.stderr.strip())
            return False
        # Reset cache and re-probe.
        global _ffmpeg_path
        _ffmpeg_path = None
        path = find_ffmpeg()
        if path:
            log.info("FFmpeg installed: %s", path)
            return True
        log.error("FFmpeg install reported success but binary still not found.")
        return False
    except Exception as exc:
        log.exception("Install failed: %s", exc)
        return False


def probe_duration(path: str | os.PathLike[str]) -> Optional[float]:
    """Return media duration in seconds, or None if probing fails."""
    p = str(path)
    ffprobe = find_ffprobe()
    if ffprobe:
        try:
            out = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", p],
                capture_output=True, text=True, timeout=10, check=False,
            )
            value = out.stdout.strip()
            if value:
                return float(value)
        except Exception as exc:
            log.debug("ffprobe duration failed for %s: %s", p, exc)

    # Fallback: soundfile for audio.
    try:
        import soundfile as sf  # type: ignore

        info = sf.info(p)
        return float(info.frames) / float(info.samplerate)
    except Exception as exc:
        log.debug("soundfile probe failed for %s: %s", p, exc)
        return None


def probe_video_size(path: str | os.PathLike[str]) -> Optional[tuple[int, int]]:
    """Return (width, height) of a video, or None."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=s=x:p=0", str(path)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        line = out.stdout.strip()
        if "x" in line:
            w, h = line.split("x", 1)
            return int(w), int(h)
    except Exception as exc:
        log.debug("ffprobe video size failed: %s", exc)
    return None
