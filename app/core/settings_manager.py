"""Persistent application settings.

Settings live in a single JSON file at ``<project_root>/config.json`` so
the user can ship the whole project folder onto a USB stick and keep
their preferences. The schema is intentionally loose; we use ``get``
with defaults everywhere so older config files still load.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from app.utils.file_utils import project_root
from app.utils.logger import get_logger

log = get_logger("settings")

CONFIG_FILE = project_root() / "config.json"


@dataclass
class AppSettings:
    # General
    theme: str = "auto"                 # auto | light | dark
    low_spec_mode: bool = False

    # FFmpeg
    ffmpeg_path: Optional[str] = None
    encoder_preference: str = "auto"    # auto | nvenc | qsv | amf | cpu

    # Render defaults
    resolution: str = "1080p"           # 720p | 1080p | 1440p | 4K | custom
    custom_resolution: str = "1920x1080"
    fps: int = 30
    quality: str = "balanced"           # fast | balanced | high
    output_format: str = "mp4"
    output_folder: str = str(project_root() / "output")

    # Background / batch
    background_mode: str = "sequence"   # sequence | match | random
    background_fit: str = "cover"       # cover | fit-blur | stretch

    # Spectrum
    spectrum_style: str = "Modern Bars"
    spectrum_color: str = "#5AC8FF"
    spectrum_color2: str = "#FF5AC8"
    spectrum_gradient: bool = True
    spectrum_glow: bool = True
    spectrum_glow_strength: float = 1.0
    spectrum_smoothness: float = 0.35
    spectrum_sensitivity: float = 1.15
    spectrum_bar_count: int = 64
    spectrum_position: str = "bottom"

    # Logo
    logo_path: Optional[str] = None
    logo_circle: bool = True
    logo_size: float = 0.12             # fraction of width
    logo_position: str = "top-left"
    logo_opacity: int = 230
    logo_shadow: bool = True
    logo_border: bool = False
    logo_glow: bool = False

    # Lyrics
    lyric_font_family: str = "Arial"
    lyric_font_size: int = 56
    lyric_bold: bool = True
    lyric_italic: bool = False
    lyric_color: str = "#FFFFFF"
    lyric_stroke: bool = True
    lyric_stroke_color: str = "#000000"
    lyric_stroke_width: int = 3
    lyric_shadow: bool = True
    lyric_position: str = "center"      # top | center | bottom | custom
    lyric_align: str = "center"         # left | center | right
    lyric_max_lines: int = 2
    lyric_animation: bool = True
    lyric_preset: str = "Modern Clean"

    # Last-used paths
    last_audio: Optional[str] = None
    last_background: Optional[str] = None
    last_background_folder: Optional[str] = None
    last_audio_folder: Optional[str] = None
    last_output_folder: Optional[str] = None

    extras: Dict[str, Any] = field(default_factory=dict)


class SettingsManager:
    """Load and save :class:`AppSettings`."""

    def __init__(self, path: Path = CONFIG_FILE):
        self.path = path
        self._settings = AppSettings()
        self.load()

    # ---- IO ----------------------------------------------------------
    def load(self) -> AppSettings:
        if not self.path.exists():
            return self._settings
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Could not read settings (%s); using defaults", e)
            return self._settings
        merged = asdict(AppSettings())
        merged.update({k: v for k, v in data.items() if k in merged})
        # Stash unknown keys so we don't lose them on save.
        merged["extras"] = {k: v for k, v in data.items() if k not in merged}
        self._settings = AppSettings(**merged)
        return self._settings

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = asdict(self._settings)
            # Flatten extras back into the top-level for backwards compat.
            extras = payload.pop("extras", {}) or {}
            payload.update(extras)
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as e:
            log.warning("Could not save settings: %s", e)

    # ---- Access ------------------------------------------------------
    @property
    def settings(self) -> AppSettings:
        return self._settings

    def update(self, **kwargs: Any) -> AppSettings:
        for key, val in kwargs.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, val)
            else:
                self._settings.extras[key] = val
        self.save()
        return self._settings

    def reset(self) -> AppSettings:
        self._settings = AppSettings()
        self.save()
        return self._settings


_DEFAULT: Optional[SettingsManager] = None


def get_settings_manager() -> SettingsManager:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = SettingsManager()
    return _DEFAULT


# ---------------------------------------------------------------------------
# Resolution / quality helpers
# ---------------------------------------------------------------------------

RESOLUTIONS = {
    "720p":  (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4K":    (3840, 2160),
}


def resolve_resolution(name: str, custom: str = "1920x1080") -> tuple[int, int]:
    if name == "custom":
        try:
            w_s, h_s = custom.lower().split("x")
            return int(w_s), int(h_s)
        except ValueError:
            return 1920, 1080
    return RESOLUTIONS.get(name, (1920, 1080))


def quality_preset(name: str) -> Dict[str, str]:
    """Return ffmpeg-style parameters for our high-level quality picker."""
    name = (name or "balanced").lower()
    if name == "fast":
        return {"preset": "veryfast", "crf": "26", "bitrate": "4M"}
    if name in ("high", "high quality"):
        return {"preset": "slow", "crf": "18", "bitrate": "12M"}
    return {"preset": "medium", "crf": "21", "bitrate": "8M"}
