"""Application-wide settings, presets and dataclasses.

Centralising these in one module keeps the UI and renderer in sync.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Tuple, Optional, Dict


# ---------------------------------------------------------------------------
# Performance / quality
# ---------------------------------------------------------------------------
class PerfMode(str, Enum):
    LOW = "Low Spec"
    BALANCED = "Balanced"
    HIGH = "High Quality"


# ---------------------------------------------------------------------------
# Spectrum
# ---------------------------------------------------------------------------
class SpectrumStyle(str, Enum):
    BAR = "Bar Spectrum"
    CIRCULAR = "Circular Spectrum"
    WAVEFORM = "Waveform"
    NEON = "Neon Spectrum"
    MODERN = "Modern Visualizer"
    SMOOTH = "Smooth Reactive"


@dataclass
class SpectrumConfig:
    style: SpectrumStyle = SpectrumStyle.BAR
    preset: str = "Neon Rainbow"
    bar_count: int = 64
    bar_width_ratio: float = 0.65          # of bar slot
    max_height_ratio: float = 0.32         # of frame height
    sensitivity: float = 1.0
    bass_boost: float = 1.4
    treble_boost: float = 1.05
    smoothing: float = 0.55                # 0=no smoothing, 0.9=very smooth
    rounded: bool = True
    glow: bool = True
    reflection: bool = False
    rainbow: bool = True
    gradient_top: Tuple[int, int, int] = (255, 80, 220)
    gradient_bottom: Tuple[int, int, int] = (80, 200, 255)


# Bar Spectrum presets - colors are (R,G,B) 0-255.
BAR_PRESETS: Dict[str, Dict] = {
    "Neon Rainbow":  dict(rainbow=True,  glow=True,  gradient_top=(255, 80, 220), gradient_bottom=(80, 200, 255)),
    "Cyberpunk":     dict(rainbow=False, glow=True,  gradient_top=(255, 0, 200),   gradient_bottom=(0, 220, 255)),
    "Ocean Blue":    dict(rainbow=False, glow=True,  gradient_top=(140, 220, 255), gradient_bottom=(20, 90, 200)),
    "Sunset Glow":   dict(rainbow=False, glow=True,  gradient_top=(255, 220, 100), gradient_bottom=(255, 60, 80)),
    "Fire Beat":     dict(rainbow=False, glow=True,  gradient_top=(255, 240, 80),  gradient_bottom=(255, 40, 0)),
    "Purple Night":  dict(rainbow=False, glow=True,  gradient_top=(220, 120, 255), gradient_bottom=(70, 30, 160)),
    "Minimal Clean": dict(rainbow=False, glow=False, gradient_top=(240, 240, 240), gradient_bottom=(180, 180, 180)),
    "Colorful Pop":  dict(rainbow=True,  glow=False, gradient_top=(255, 120, 80),  gradient_bottom=(80, 255, 200)),
}


# ---------------------------------------------------------------------------
# Lyrics
# ---------------------------------------------------------------------------
class LyricMode(str, Enum):
    NONE = "Off"
    NORMAL = "Normal"
    KARAOKE_LINE = "Karaoke Line"
    KARAOKE_WORD = "Karaoke Word"
    KARAOKE_SWEEP = "Karaoke Sweep"


@dataclass
class LyricConfig:
    mode: LyricMode = LyricMode.NORMAL
    font_path: Optional[str] = None
    font_size: int = 56
    color_normal: Tuple[int, int, int] = (240, 240, 240)
    color_highlight: Tuple[int, int, int] = (255, 215, 0)
    outline: int = 3
    outline_color: Tuple[int, int, int] = (0, 0, 0)
    shadow: bool = True
    glow: bool = True
    opacity: float = 1.0
    transition_speed: float = 1.0
    # vertical placement: fraction of frame height (0=top, 1=bottom).
    # The default keeps lyrics ABOVE the bar spectrum (which sits at the bottom).
    y_ratio: float = 0.66


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------
class LogoPos(str, Enum):
    TOP_LEFT = "Top Left"
    TOP_RIGHT = "Top Right"
    BOTTOM_LEFT = "Bottom Left"
    BOTTOM_RIGHT = "Bottom Right"
    CENTER = "Center"


class LogoAnim(str, Enum):
    NONE = "None"
    FADE_IN = "Fade In"
    FADE_OUT = "Fade Out"
    PULSE = "Pulse"
    ZOOM = "Zoom"


@dataclass
class LogoConfig:
    enabled: bool = False
    path: Optional[str] = None
    position: LogoPos = LogoPos.TOP_RIGHT
    size_ratio: float = 0.12        # of frame width
    opacity: float = 0.85
    margin: int = 24
    animation: LogoAnim = LogoAnim.FADE_IN


# ---------------------------------------------------------------------------
# CTA
# ---------------------------------------------------------------------------
class CTATiming(str, Enum):
    START = "Start"
    MIDDLE = "Middle"
    END = "End"
    CUSTOM = "Custom"


class CTAAnim(str, Enum):
    POP = "Subscribe Pop Up"
    LIKE_SUB = "Like and Subscribe"
    BELL = "Bell Notification"
    SLIDE = "Smooth Slide In"
    BOUNCE = "Bounce Subscribe"
    MINIMAL = "Minimal Clean"
    YOUTUBE = "YouTube Style"


@dataclass
class CTAConfig:
    enabled: bool = False
    text: str = "SUBSCRIBE"
    timing: CTATiming = CTATiming.MIDDLE
    custom_time: float = 5.0           # seconds, used when timing == CUSTOM
    duration: float = 4.0
    color_text: Tuple[int, int, int] = (255, 255, 255)
    color_button: Tuple[int, int, int] = (220, 30, 30)
    size_ratio: float = 0.22           # of frame width
    opacity: float = 1.0
    shadow: bool = True
    glow: bool = True
    animation: CTAAnim = CTAAnim.POP


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
@dataclass
class RenderConfig:
    width: int = 1280
    height: int = 720
    fps: int = 30
    ffmpeg_preset: str = "veryfast"      # ultrafast, veryfast, fast, medium, slow
    bitrate: Optional[str] = None         # e.g. "6M"; None = auto (CRF)
    crf: int = 20                         # used when bitrate is None
    perf_mode: PerfMode = PerfMode.BALANCED


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------
class BackgroundType(str, Enum):
    IMAGE = "Image"
    VIDEO = "Video"
    SOLID = "Solid"


@dataclass
class BackgroundConfig:
    kind: BackgroundType = BackgroundType.SOLID
    path: Optional[str] = None
    solid_color: Tuple[int, int, int] = (12, 14, 24)


# ---------------------------------------------------------------------------
# Top-level project state
# ---------------------------------------------------------------------------
@dataclass
class ProjectSettings:
    audio_path: Optional[str] = None
    background: BackgroundConfig = field(default_factory=BackgroundConfig)
    spectrum: SpectrumConfig = field(default_factory=SpectrumConfig)
    lyrics: LyricConfig = field(default_factory=LyricConfig)
    logo: LogoConfig = field(default_factory=LogoConfig)
    cta: CTAConfig = field(default_factory=CTAConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    output_dir: str = "output"

    def apply_perf_mode(self, mode: PerfMode) -> None:
        """Mutate render + spectrum config to match the requested perf mode."""
        self.render.perf_mode = mode
        if mode == PerfMode.LOW:
            self.render.width, self.render.height = 1280, 720
            self.render.fps = 24
            self.render.ffmpeg_preset = "ultrafast"
            self.render.crf = 24
            self.spectrum.bar_count = 40
            self.spectrum.glow = False
            self.spectrum.reflection = False
        elif mode == PerfMode.BALANCED:
            self.render.width, self.render.height = 1280, 720
            self.render.fps = 30
            self.render.ffmpeg_preset = "veryfast"
            self.render.crf = 20
            self.spectrum.bar_count = 64
            self.spectrum.glow = True
            self.spectrum.reflection = False
        elif mode == PerfMode.HIGH:
            self.render.width, self.render.height = 1920, 1080
            self.render.fps = 60
            self.render.ffmpeg_preset = "medium"
            self.render.crf = 18
            self.spectrum.bar_count = 96
            self.spectrum.glow = True
            self.spectrum.reflection = True

    def to_dict(self) -> dict:
        return asdict(self)
