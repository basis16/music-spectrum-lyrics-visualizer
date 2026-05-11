"""FFmpeg detection, installation and hardware-acceleration probing.

Resolution order for ``ffmpeg.exe``:

1. Explicit path saved in settings (``settings_manager``).
2. ``ffmpeg`` on ``PATH`` (``shutil.which``).
3. Bundled binary at ``app/assets/ffmpeg/ffmpeg.exe``.

Downloading from the trusted gyan.dev "essentials" build is supported through
:meth:`FFmpegManager.install_online`. The download runs in a worker thread
and reports progress via callbacks; the UI never blocks.
"""
from __future__ import annotations

import io
import os
import platform
import shutil
import subprocess
import sys
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from app.utils.file_utils import project_root
from app.utils.logger import get_logger

log = get_logger("ffmpeg")

# Trusted source for Windows FFmpeg builds.
GYAN_ESSENTIALS_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


@dataclass(frozen=True)
class FFmpegInfo:
    """Information about a detected FFmpeg installation."""

    ffmpeg_path: Optional[str]
    ffprobe_path: Optional[str]
    version: Optional[str]
    encoders: List[str]

    @property
    def available(self) -> bool:
        return self.ffmpeg_path is not None

    @property
    def hwaccels(self) -> List[str]:
        """Detected hardware encoder names (NVENC, QSV, AMF)."""
        result: List[str] = []
        names = {enc.lower() for enc in self.encoders}
        if "h264_nvenc" in names:
            result.append("nvenc")
        if "h264_qsv" in names:
            result.append("qsv")
        if "h264_amf" in names:
            result.append("amf")
        return result


class FFmpegManager:
    """Detect and manage the FFmpeg binary used by the renderer."""

    def __init__(self, custom_path: Optional[str] = None):
        self._custom_path = custom_path
        self._info: Optional[FFmpegInfo] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def set_custom_path(self, path: Optional[str]) -> None:
        with self._lock:
            self._custom_path = path or None
            self._info = None

    def bundled_dir(self) -> Path:
        return project_root() / "app" / "assets" / "ffmpeg"

    def detect(self, force: bool = False) -> FFmpegInfo:
        """Return cached info, or perform a fresh detection."""
        with self._lock:
            if self._info is not None and not force:
                return self._info
            self._info = self._detect_locked()
            return self._info

    def _detect_locked(self) -> FFmpegInfo:
        ffmpeg = self._resolve_ffmpeg()
        if not ffmpeg:
            log.warning("FFmpeg not found")
            return FFmpegInfo(None, None, None, [])

        ffprobe = self._resolve_ffprobe(ffmpeg)
        version = self._probe_version(ffmpeg)
        encoders = self._probe_encoders(ffmpeg)
        log.info("FFmpeg detected: %s (%s)", ffmpeg, version or "unknown version")
        if encoders:
            log.info("Available H.264 encoders: %s", ", ".join(encoders))
        return FFmpegInfo(ffmpeg, ffprobe, version, encoders)

    def _resolve_ffmpeg(self) -> Optional[str]:
        # 1. User-provided custom path
        if self._custom_path:
            p = Path(self._custom_path)
            if p.is_file():
                return str(p)
            # Maybe they pointed at a directory
            if p.is_dir():
                cand = p / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
                if cand.is_file():
                    return str(cand)
        # 2. PATH
        which = shutil.which("ffmpeg")
        if which:
            return which
        # 3. Bundled
        cand = self.bundled_dir() / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if cand.is_file():
            return str(cand)
        return None

    def _resolve_ffprobe(self, ffmpeg_path: str) -> Optional[str]:
        # Try alongside ffmpeg first.
        p = Path(ffmpeg_path).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if p.is_file():
            return str(p)
        which = shutil.which("ffprobe")
        return which

    def _probe_version(self, ffmpeg_path: str) -> Optional[str]:
        try:
            out = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-version"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            line = (out.stdout or "").splitlines()[:1]
            if line:
                return line[0].strip()
        except (OSError, subprocess.SubprocessError):
            return None
        return None

    def _probe_encoders(self, ffmpeg_path: str) -> List[str]:
        encoders: List[str] = []
        try:
            out = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            in_table = False
            for line in (out.stdout or "").splitlines():
                stripped = line.strip()
                if not in_table:
                    if stripped.startswith("------"):
                        in_table = True
                    continue
                # ' V..... libx264              libx264 H.264 ...'
                if not stripped:
                    continue
                parts = stripped.split()
                # First token is a 6-char flag like 'V.....' or 'VFS..D'.
                flag = parts[0]
                if len(flag) != 6 or flag[0] not in {"V", "A", "S"}:
                    continue
                if flag[0] != "V" or len(parts) < 2:
                    continue
                encoders.append(parts[1])
        except (OSError, subprocess.SubprocessError):
            pass
        return encoders

    # ------------------------------------------------------------------
    # Online install
    # ------------------------------------------------------------------
    def install_online(
        self,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> Optional[FFmpegInfo]:
        """Download a fresh FFmpeg build into the bundled directory.

        ``on_progress(downloaded, total)`` and ``on_status(message)`` may be
        provided so the UI can render a progress bar. ``total`` is ``-1`` if
        the server doesn't expose ``Content-Length``.
        """
        if platform.system().lower() not in {"windows"}:
            msg = ("Online FFmpeg installer currently targets Windows. "
                   "On other systems install FFmpeg via your package manager.")
            log.warning(msg)
            if on_status:
                on_status(msg)
            return None

        try:
            import requests  # local import so tests without the dep don't break
        except ImportError:
            msg = "Python 'requests' is missing; run setup.bat to install dependencies."
            log.error(msg)
            if on_status:
                on_status(msg)
            return None

        target_dir = self.bundled_dir()
        target_dir.mkdir(parents=True, exist_ok=True)

        if on_status:
            on_status("Downloading FFmpeg from gyan.dev...")
        log.info("Downloading FFmpeg from %s", GYAN_ESSENTIALS_URL)

        try:
            with requests.get(GYAN_ESSENTIALS_URL, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length", "-1") or -1)
                buf = io.BytesIO()
                downloaded = 0
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if not chunk:
                        continue
                    buf.write(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(downloaded, total)
                buf.seek(0)
        except Exception as e:
            msg = f"FFmpeg download failed: {e}"
            log.error(msg)
            if on_status:
                on_status(msg)
            return None

        if on_status:
            on_status("Extracting FFmpeg archive...")
        try:
            with zipfile.ZipFile(buf) as zf:
                for info in zf.infolist():
                    name = info.filename.lower()
                    if name.endswith("ffmpeg.exe"):
                        dst = target_dir / "ffmpeg.exe"
                        with zf.open(info) as src, open(dst, "wb") as out:
                            shutil.copyfileobj(src, out)
                    elif name.endswith("ffprobe.exe"):
                        dst = target_dir / "ffprobe.exe"
                        with zf.open(info) as src, open(dst, "wb") as out:
                            shutil.copyfileobj(src, out)
        except Exception as e:
            msg = f"FFmpeg extract failed: {e}"
            log.error(msg)
            if on_status:
                on_status(msg)
            return None

        if on_status:
            on_status("FFmpeg installed. Re-detecting...")
        log.info("FFmpeg installed at %s", target_dir)
        info = self.detect(force=True)
        if on_status:
            on_status("FFmpeg ready." if info.available else "FFmpeg still missing")
        return info

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    def ffprobe_duration(self, audio_path: str) -> Optional[float]:
        """Return the duration in seconds via ffprobe (or None on failure)."""
        info = self.detect()
        ffprobe = info.ffprobe_path
        if not ffprobe:
            return None
        try:
            out = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", audio_path],
                capture_output=True, text=True, timeout=15, check=False,
            )
            val = (out.stdout or "").strip()
            return float(val) if val else None
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def encoder_for(self, preference: str) -> str:
        """Map a preference (auto/nvenc/qsv/amf/cpu) to the actual encoder name."""
        info = self.detect()
        pref = (preference or "auto").lower()
        if pref == "cpu":
            return "libx264"
        if pref in info.hwaccels:
            return {"nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf"}[pref]
        if pref == "auto":
            for cand in ("nvenc", "qsv", "amf"):
                if cand in info.hwaccels:
                    return {"nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf"}[cand]
        return "libx264"


_DEFAULT_MANAGER: Optional[FFmpegManager] = None


def get_default_manager() -> FFmpegManager:
    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is None:
        _DEFAULT_MANAGER = FFmpegManager()
    return _DEFAULT_MANAGER


if __name__ == "__main__":
    mgr = FFmpegManager()
    info = mgr.detect()
    print("FFmpeg:", info.ffmpeg_path)
    print("FFprobe:", info.ffprobe_path)
    print("Version:", info.version)
    print("Encoders:", ", ".join(info.encoders[:10]))
    print("HW accels:", info.hwaccels)
    sys.exit(0 if info.available else 1)
