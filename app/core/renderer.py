"""Video renderer.

Pipeline (per file):

1. Resolve render config (resolution, fps, encoder, quality).
2. Pre-compute the spectrum data (cached) and load lyrics.
3. Compose background once (image) or open a background decoder (video).
4. Open an ``ffmpeg`` encoder over stdin (rawvideo / rgb24).
5. For each frame at the target fps:
   - take the next background frame
   - paint the spectrum overlay using :func:`render_style`
   - paint the logo
   - paint the active lyric line (or nothing, if no line is active)
   - write the RGB bytes to ffmpeg's stdin
6. Close the encoder and mux the original audio with the new video.

The renderer never writes intermediate PNGs to disk, which keeps it
friendly to laptops with small SSDs.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.core.audio_analyzer import (
    AudioAnalyzer,
    SpectrumData,
    apply_sensitivity_and_smoothness,
)
from app.core.ffmpeg_manager import FFmpegManager, get_default_manager
from app.core.lyrics_cleaner import LyricLine
from app.core.lyrics_extractor import LyricsResult, extract_lyrics
from app.core.spectrum_styles import (
    SpectrumStyleOptions,
    render_style,
)
from app.utils.file_utils import (
    BACKGROUND_EXTS,
    IMAGE_EXTS,
    VIDEO_EXTS,
    ensure_dir,
    safe_filename,
)
from app.utils.logger import get_logger

log = get_logger("renderer")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class LogoOptions:
    path: Optional[str] = None
    circle: bool = True
    size_ratio: float = 0.12          # relative to frame width
    position: str = "top-left"        # top-left, top-right, bottom-left, bottom-right, center
    opacity: int = 230                # 0..255
    shadow: bool = True
    border: bool = False
    glow: bool = False


@dataclass
class LyricOptions:
    font_family: str = "Arial"
    font_size: int = 56
    bold: bool = True
    italic: bool = False
    color: Tuple[int, int, int, int] = (255, 255, 255, 255)
    stroke: bool = True
    stroke_color: Tuple[int, int, int, int] = (0, 0, 0, 230)
    stroke_width: int = 3
    shadow: bool = True
    position: str = "center"          # top | center | bottom
    align: str = "center"             # left | center | right
    max_lines: int = 2
    animation: bool = True            # fade in/out
    preset: str = "Modern Clean"


@dataclass
class RenderConfig:
    audio_path: str
    output_path: str
    background_path: Optional[str] = None
    background_fit: str = "cover"     # cover | fit-blur | stretch

    width: int = 1920
    height: int = 1080
    fps: int = 30
    encoder: str = "libx264"          # libx264 | h264_nvenc | h264_qsv | h264_amf
    quality_preset: str = "medium"
    crf: str = "21"
    bitrate: str = "8M"
    low_spec: bool = False

    spectrum: SpectrumStyleOptions = field(default_factory=SpectrumStyleOptions)
    logo: LogoOptions = field(default_factory=LogoOptions)
    lyrics: LyricOptions = field(default_factory=LyricOptions)

    # If supplied, the renderer uses these lyrics instead of re-extracting.
    lyrics_override: Optional[LyricsResult] = None


# ---------------------------------------------------------------------------
# Background sources
# ---------------------------------------------------------------------------

class _StaticImageBackground:
    """A background that simply repeats a single composed PIL image."""

    def __init__(self, image: Image.Image):
        self.image = image

    def frame(self, t: float) -> Image.Image:
        return self.image

    def close(self) -> None:  # noqa: D401 - protocol
        pass


class _VideoBackground:
    """Stream raw RGB frames from a video file via ffmpeg subprocess.

    The video loops if it's shorter than the audio.
    """

    def __init__(self, ffmpeg_path: str, video_path: str, width: int, height: int,
                  fps: int, fit: str = "cover"):
        self.width = width
        self.height = height
        self.fit = fit
        vf = _build_bg_filter(width, height, fit)
        cmd = [
            ffmpeg_path, "-hide_banner", "-loglevel", "error",
            "-stream_loop", "-1", "-i", video_path,
            "-vf", vf,
            "-r", str(fps),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, bufsize=10**7)
        self._frame_bytes = width * height * 3
        self._last: Optional[Image.Image] = None

    def frame(self, t: float) -> Image.Image:
        del t  # unused; we read sequentially in lock-step with the main loop.
        if self._proc.stdout is None:
            raise RuntimeError("background ffmpeg has no stdout")
        raw = self._proc.stdout.read(self._frame_bytes)
        if len(raw) < self._frame_bytes:
            # Stream ended unexpectedly; loop by returning last good frame.
            if self._last is not None:
                return self._last
            raise RuntimeError("background ffmpeg returned no frames")
        img = Image.frombytes("RGB", (self.width, self.height), raw)
        self._last = img.convert("RGBA")
        return self._last

    def close(self) -> None:
        try:
            if self._proc.stdout:
                self._proc.stdout.close()
            self._proc.terminate()
            self._proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                self._proc.kill()
            except Exception:
                pass


def _build_bg_filter(w: int, h: int, fit: str) -> str:
    if fit == "stretch":
        return f"scale={w}:{h}"
    if fit == "fit-blur":
        return (
            f"split=2[bg][fg];"
            f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},boxblur=20:1[bg2];"
            f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fg2];"
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2"
        )
    # default cover
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}"
    )


def _compose_image_background(path: Optional[str], width: int, height: int,
                                fit: str) -> Image.Image:
    """Return a composed RGBA background image, using a generated gradient
    when ``path`` is None."""
    canvas = Image.new("RGBA", (width, height))
    if path and Path(path).exists():
        try:
            img = Image.open(path).convert("RGBA")
        except OSError:
            img = None
        else:
            if fit == "stretch":
                img = img.resize((width, height), Image.LANCZOS)
                canvas.paste(img, (0, 0))
                return canvas
            if fit == "fit-blur":
                # Blurred cover + centred fit overlay.
                bg = ImageOps.fit(img, (width, height), Image.LANCZOS).filter(
                    ImageFilter.GaussianBlur(radius=24)
                )
                fg = ImageOps.contain(img, (width, height), Image.LANCZOS)
                canvas.paste(bg, (0, 0))
                ox = (width - fg.width) // 2
                oy = (height - fg.height) // 2
                canvas.paste(fg, (ox, oy), fg if fg.mode == "RGBA" else None)
                return canvas
            # cover
            cover = ImageOps.fit(img, (width, height), Image.LANCZOS)
            canvas.paste(cover, (0, 0))
            return canvas

    # Fallback: subtle generated gradient with soft vignette.
    grad = Image.new("RGB", (width, height), (15, 15, 25))
    pixels = grad.load()
    for y in range(height):
        # Smooth top -> bottom darker
        t = y / max(1, height - 1)
        r = int(20 + 25 * (1 - t))
        g = int(22 + 30 * (1 - t))
        b = int(40 + 60 * (1 - t))
        for x in range(width):
            pixels[x, y] = (r, g, b)
    # Soft radial vignette for depth.
    vignette = Image.new("L", (width, height), 0)
    vd = ImageDraw.Draw(vignette)
    vd.ellipse(
        [-width // 4, -height // 4, width + width // 4, height + height // 4],
        fill=255,
    )
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=80))
    canvas.paste(grad, (0, 0))
    canvas.putalpha(255)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 80))
    overlay.putalpha(ImageOps.invert(vignette))
    canvas.alpha_composite(overlay)
    return canvas


# ---------------------------------------------------------------------------
# Logo overlay
# ---------------------------------------------------------------------------

def _prepare_logo(opts: LogoOptions, frame_w: int, frame_h: int) -> Optional[Image.Image]:
    if not opts.path or not Path(opts.path).exists():
        return None
    try:
        logo = Image.open(opts.path).convert("RGBA")
    except OSError:
        return None
    size = int(min(frame_w, frame_h) * opts.size_ratio)
    size = max(48, size)
    logo = ImageOps.contain(logo, (size, size), Image.LANCZOS)

    if opts.circle:
        mask = Image.new("L", logo.size, 0)
        ImageDraw.Draw(mask).ellipse([0, 0, logo.size[0] - 1, logo.size[1] - 1], fill=255)
        circ = Image.new("RGBA", logo.size, (0, 0, 0, 0))
        circ.paste(logo, (0, 0), mask=mask)
        logo = circ

    # Opacity
    if opts.opacity < 255:
        r, g, b, a = logo.split()
        a = a.point(lambda v: int(v * (opts.opacity / 255.0)))
        logo = Image.merge("RGBA", (r, g, b, a))

    # Border
    if opts.border:
        bordered = Image.new("RGBA", (logo.size[0] + 8, logo.size[1] + 8), (0, 0, 0, 0))
        d = ImageDraw.Draw(bordered)
        if opts.circle:
            d.ellipse([0, 0, bordered.size[0] - 1, bordered.size[1] - 1],
                       outline=(255, 255, 255, 220), width=4)
        else:
            d.rectangle([0, 0, bordered.size[0] - 1, bordered.size[1] - 1],
                         outline=(255, 255, 255, 220), width=4)
        bordered.paste(logo, (4, 4), logo)
        logo = bordered

    # Shadow / glow are baked into a larger canvas at draw time.
    return logo


def _logo_position_xy(opts: LogoOptions, frame_w: int, frame_h: int,
                       logo_size: Tuple[int, int]) -> Tuple[int, int]:
    pad = int(min(frame_w, frame_h) * 0.04)
    pos = (opts.position or "top-left").lower()
    if pos == "top-left":
        return pad, pad
    if pos == "top-right":
        return frame_w - logo_size[0] - pad, pad
    if pos == "bottom-left":
        return pad, frame_h - logo_size[1] - pad
    if pos == "bottom-right":
        return frame_w - logo_size[0] - pad, frame_h - logo_size[1] - pad
    if pos == "center":
        return (frame_w - logo_size[0]) // 2, (frame_h - logo_size[1]) // 2
    return pad, pad


def _draw_logo(canvas: Image.Image, logo: Image.Image, opts: LogoOptions) -> None:
    pos = _logo_position_xy(opts, canvas.width, canvas.height, logo.size)
    if opts.shadow:
        shadow = Image.new("RGBA", logo.size, (0, 0, 0, 0))
        s_mask = logo.split()[-1].point(lambda v: 160 if v > 0 else 0)
        sh = Image.new("RGBA", logo.size, (0, 0, 0, 0))
        sh.putalpha(s_mask)
        sh = sh.filter(ImageFilter.GaussianBlur(radius=6))
        canvas.alpha_composite(sh, (pos[0] + 4, pos[1] + 6))
        del shadow
    if opts.glow:
        glow = logo.filter(ImageFilter.GaussianBlur(radius=10))
        canvas.alpha_composite(glow, pos)
    canvas.alpha_composite(logo, pos)


# ---------------------------------------------------------------------------
# Lyric overlay
# ---------------------------------------------------------------------------

def _load_font(family: str, size: int, bold: bool, italic: bool) -> ImageFont.FreeTypeFont:
    """Try to load a TTF for the requested font family.

    Falls back to PIL's default font if nothing matches — the app still
    renders, just with a less polished typeface.
    """
    candidates: List[str] = []
    fam = (family or "Arial").lower()
    weights = []
    if bold and italic:
        weights = ["bolditalic", "bi", "boldoblique"]
    elif bold:
        weights = ["bold", "b"]
    elif italic:
        weights = ["italic", "oblique", "i"]
    else:
        weights = ["regular", ""]

    win_fonts = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
    linux_fonts = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts")]

    # Common name mappings to actual files on Windows.
    win_known = {
        "arial": "arial",
        "calibri": "calibri",
        "tahoma": "tahoma",
        "verdana": "verdana",
        "segoe ui": "segoeui",
        "times new roman": "times",
        "consolas": "consola",
        "georgia": "georgia",
        "trebuchet ms": "trebuc",
        "impact": "impact",
    }
    base = win_known.get(fam, fam.replace(" ", ""))
    for w in weights:
        suffix = "" if w in ("regular", "") else w
        candidates.append(str(win_fonts / f"{base}{suffix}.ttf"))
        candidates.append(str(win_fonts / f"{base}{suffix}.otf"))
    # Direct family.ttf
    candidates.append(str(win_fonts / f"{family}.ttf"))
    # Linux fallback
    for root in linux_fonts:
        if root.exists():
            for p in root.rglob("*.ttf"):
                if fam in p.stem.lower():
                    candidates.append(str(p))
                    break

    for c in candidates:
        try:
            return ImageFont.truetype(c, size=size)
        except (OSError, IOError):
            continue
    # Last resort fallback bundled in PIL.
    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def _lyric_active_index(now_ms: int, lines: List[LyricLine]) -> int:
    """Return the index of the currently visible line, or -1 if none."""
    if not lines or now_ms < lines[0].time_ms:
        return -1
    lo, hi = 0, len(lines) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if lines[mid].time_ms <= now_ms:
            lo = mid + 1
        else:
            hi = mid - 1
    return hi  # the last line whose time_ms <= now_ms


def _wrap_lyric(text: str, font: ImageFont.FreeTypeFont, max_width: int,
                max_lines: int) -> List[str]:
    words = text.split()
    if not words:
        return []
    lines: List[str] = []
    current = words[0]
    for w in words[1:]:
        trial = f"{current} {w}"
        bbox = font.getbbox(trial)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            current = trial
        else:
            lines.append(current)
            current = w
    lines.append(current)
    if len(lines) > max_lines:
        # Merge tail lines into the last allowed line.
        lines = lines[: max_lines - 1] + [" ".join(lines[max_lines - 1:])]
    return lines


def _draw_lyric(canvas: Image.Image, text: str, opts: LyricOptions, alpha: float) -> None:
    if not text:
        return
    font = _load_font(opts.font_family, opts.font_size, opts.bold, opts.italic)
    pad_x = int(canvas.width * 0.06)
    pad_y = int(canvas.height * 0.06)
    max_w = canvas.width - pad_x * 2

    lines = _wrap_lyric(text, font, max_w, max_lines=max(1, opts.max_lines))
    if not lines:
        return

    line_heights = [font.getbbox(l)[3] - font.getbbox(l)[1] for l in lines]
    total_h = sum(line_heights) + (len(lines) - 1) * int(opts.font_size * 0.25)

    if opts.position == "top":
        y = pad_y
    elif opts.position == "center":
        y = (canvas.height - total_h) // 2
    else:  # bottom (default)
        y = canvas.height - total_h - pad_y

    color = _apply_alpha(opts.color, alpha)
    stroke_col = _apply_alpha(opts.stroke_color, alpha) if opts.stroke else None

    draw = ImageDraw.Draw(canvas)
    cur_y = y
    for line, lh in zip(lines, line_heights):
        bbox = font.getbbox(line)
        text_w = bbox[2] - bbox[0]
        if opts.align == "left":
            x = pad_x
        elif opts.align == "right":
            x = canvas.width - pad_x - text_w
        else:
            x = (canvas.width - text_w) // 2

        if opts.shadow:
            shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            ImageDraw.Draw(shadow_layer).text(
                (x + 3, cur_y + 5), line, font=font,
                fill=(0, 0, 0, int(180 * alpha)),
            )
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=4))
            canvas.alpha_composite(shadow_layer)

        if opts.stroke and opts.stroke_width > 0:
            draw.text(
                (x, cur_y), line, font=font,
                fill=color,
                stroke_width=opts.stroke_width,
                stroke_fill=stroke_col or (0, 0, 0, int(255 * alpha)),
            )
        else:
            draw.text((x, cur_y), line, font=font, fill=color)
        cur_y += lh + int(opts.font_size * 0.25)


def _apply_alpha(rgba: Tuple[int, int, int, int], alpha: float) -> Tuple[int, int, int, int]:
    alpha = max(0.0, min(1.0, alpha))
    return (rgba[0], rgba[1], rgba[2], int(rgba[3] * alpha))


def _lyric_fade(now_ms: int, lines: List[LyricLine], idx: int,
                 animation: bool) -> float:
    """Return an alpha multiplier for the active lyric line."""
    if idx < 0:
        return 0.0
    if not animation:
        return 1.0
    line = lines[idx]
    next_t = lines[idx + 1].time_ms if idx + 1 < len(lines) else None
    fade = 250  # ms
    if now_ms - line.time_ms < fade:
        return (now_ms - line.time_ms) / fade
    if next_t is not None and next_t - now_ms < fade:
        return max(0.0, (next_t - now_ms) / fade)
    return 1.0


# ---------------------------------------------------------------------------
# Frame composition
# ---------------------------------------------------------------------------

@dataclass
class FrameContext:
    """Pre-computed state passed to each frame render."""

    config: RenderConfig
    spectrum: SpectrumData
    lyrics: List[LyricLine]
    background: Image.Image | None  # None for video bg (we read per-frame)
    logo: Optional[Image.Image]
    spectrum_size: Tuple[int, int]
    spectrum_xy: Tuple[int, int]


def _spectrum_area(config: RenderConfig) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Return ``(size, xy)`` for the spectrum overlay inside the frame."""
    w, h = config.width, config.height
    pos = (config.spectrum.position or "bottom").lower()
    height = int(h * 0.32)
    width = int(w * 0.9)
    x = (w - width) // 2
    if pos == "top":
        y = int(h * 0.06)
    elif pos == "center":
        y = (h - height) // 2
    elif pos == "left":
        height = int(h * 0.6)
        width = int(w * 0.4)
        y = (h - height) // 2
        x = int(w * 0.04)
    elif pos == "right":
        height = int(h * 0.6)
        width = int(w * 0.4)
        y = (h - height) // 2
        x = w - width - int(w * 0.04)
    else:  # bottom
        y = h - height - int(h * 0.05)
    return (width, height), (x, y)


def render_frame(now_seconds: float, ctx: FrameContext,
                  bg_source: Optional[object] = None) -> Image.Image:
    """Render a single composited frame at ``now_seconds`` of the song."""
    config = ctx.config

    # Background
    if ctx.background is not None:
        bg = ctx.background.copy()
    else:
        assert bg_source is not None, "video background requires bg_source"
        bg = bg_source.frame(now_seconds).copy()

    # Spectrum overlay
    fps = config.fps
    frame_idx = min(int(now_seconds * fps), ctx.spectrum.num_frames - 1)
    levels = ctx.spectrum.spectrum[max(0, frame_idx)]
    spec_opts = ctx.config.spectrum.with_size(ctx.spectrum_size)
    if config.low_spec:
        spec_opts.glow = False
    spec_img = render_style(levels, spec_opts)
    bg.alpha_composite(spec_img, ctx.spectrum_xy)

    # Logo
    if ctx.logo is not None:
        _draw_logo(bg, ctx.logo, config.logo)

    # Lyrics (only if any active line)
    if ctx.lyrics:
        now_ms = int(now_seconds * 1000)
        idx = _lyric_active_index(now_ms, ctx.lyrics)
        if idx >= 0:
            alpha = _lyric_fade(now_ms, ctx.lyrics, idx, config.lyrics.animation)
            if alpha > 0:
                _draw_lyric(bg, ctx.lyrics[idx].text, config.lyrics, alpha)
    return bg


# ---------------------------------------------------------------------------
# Main Renderer
# ---------------------------------------------------------------------------

class Renderer:
    """Coordinates audio analysis + frame composition + ffmpeg encoding."""

    def __init__(self, ffmpeg: Optional[FFmpegManager] = None,
                  analyzer: Optional[AudioAnalyzer] = None):
        self.ffmpeg = ffmpeg or get_default_manager()
        self.analyzer = analyzer or AudioAnalyzer(self.ffmpeg)
        self._cancel = threading.Event()

    # ------------------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def reset_cancel(self) -> None:
        self._cancel.clear()

    # ------------------------------------------------------------------
    def prepare_context(self, config: RenderConfig) -> FrameContext:
        """Pre-compute spectrum, lyrics, background and logo."""
        spectrum = self.analyzer.analyze(
            config.audio_path, fps=config.fps,
            num_bins=max(8, config.spectrum.bar_count),
        )
        if config.spectrum.sensitivity != 1.0 or config.spectrum.smoothness > 0:
            adj = apply_sensitivity_and_smoothness(
                spectrum.spectrum,
                sensitivity=config.spectrum.sensitivity,
                smoothness=config.spectrum.smoothness,
            )
            spectrum = SpectrumData(
                fps=spectrum.fps, num_bins=spectrum.num_bins,
                fmin=spectrum.fmin, fmax=spectrum.fmax,
                duration=spectrum.duration,
                waveform=spectrum.waveform,
                spectrum=adj,
                sample_rate=spectrum.sample_rate,
            )

        # Lyrics
        if config.lyrics_override is not None:
            lyr = config.lyrics_override
        else:
            lyr = extract_lyrics(config.audio_path)
        lines = lyr.synced  # never invent times from unsynced

        # Background (image only here; video is streamed per-frame).
        bg_image = None
        bg_ext = (Path(config.background_path).suffix.lower()
                  if config.background_path else "")
        if not config.background_path or bg_ext not in VIDEO_EXTS:
            # For images or unknown formats, fall back to compose helper
            # (it generates a gradient when the path is missing/unsupported).
            bg_image = _compose_image_background(
                config.background_path, config.width, config.height,
                config.background_fit,
            )

        # Logo
        logo_img = _prepare_logo(config.logo, config.width, config.height)

        spec_size, spec_xy = _spectrum_area(config)
        return FrameContext(
            config=config,
            spectrum=spectrum,
            lyrics=lines,
            background=bg_image,
            logo=logo_img,
            spectrum_size=spec_size,
            spectrum_xy=spec_xy,
        )

    # ------------------------------------------------------------------
    def render_preview_frame(self, config: RenderConfig, t_seconds: float,
                              preview_scale: float = 0.5) -> Image.Image:
        """Render a single preview frame, optionally at lower resolution."""
        scale = max(0.2, min(1.0, preview_scale))
        cfg = RenderConfig(**{**config.__dict__,
                              "width": int(config.width * scale),
                              "height": int(config.height * scale)})
        ctx = self.prepare_context(cfg)
        if ctx.background is None:
            # For preview we don't open the video background subprocess;
            # synthesize a static placeholder so previews are cheap.
            ctx.background = _compose_image_background(
                None, cfg.width, cfg.height, cfg.background_fit,
            )
        return render_frame(t_seconds, ctx)

    # ------------------------------------------------------------------
    def render(
        self,
        config: RenderConfig,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> Path:
        """Render the full video. Returns the output Path on success."""
        self.reset_cancel()
        info = self.ffmpeg.detect()
        if not info.ffmpeg_path:
            raise RuntimeError("FFmpeg is not available. Configure it in Settings.")

        out = Path(config.output_path)
        ensure_dir(out.parent)

        ctx = self.prepare_context(config)
        total_frames = int(np.ceil(ctx.spectrum.duration * config.fps))
        if total_frames <= 0:
            raise RuntimeError("Audio appears to be empty.")

        # If background is a video, open the decoder now.
        bg_source: Optional[object] = None
        if (config.background_path and
                Path(config.background_path).suffix.lower() in VIDEO_EXTS):
            try:
                bg_source = _VideoBackground(
                    info.ffmpeg_path, config.background_path,
                    config.width, config.height, config.fps,
                    fit=config.background_fit,
                )
            except Exception as e:  # noqa: BLE001
                log.warning("Video background failed (%s); using image fallback", e)
                bg_source = None
                if ctx.background is None:
                    ctx.background = _compose_image_background(
                        None, config.width, config.height, config.background_fit,
                    )

        # Open ffmpeg encoder pipe.
        encoder_cmd = self._encoder_cmd(info.ffmpeg_path, config, out)
        log.info("Render start: %s -> %s", Path(config.audio_path).name, out.name)
        log.debug("ffmpeg encode cmd: %s", " ".join(encoder_cmd))
        try:
            proc = subprocess.Popen(
                encoder_cmd,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                bufsize=10**7,
            )
        except OSError as e:
            raise RuntimeError(f"Could not launch FFmpeg: {e}") from e

        if on_progress:
            on_progress(0.0, f"Starting render: {out.name}")

        start = time.time()
        try:
            assert proc.stdin is not None
            for i in range(total_frames):
                if self._cancel.is_set():
                    log.info("Render cancelled by user")
                    break
                now_s = i / config.fps
                frame = render_frame(now_s, ctx, bg_source=bg_source)
                proc.stdin.write(frame.convert("RGB").tobytes())
                if on_progress and (i % max(1, config.fps) == 0):
                    elapsed = time.time() - start
                    rate = (i + 1) / max(0.01, elapsed)
                    remaining = max(0.0, (total_frames - i) / max(0.1, rate))
                    on_progress(
                        i / total_frames,
                        f"Frame {i + 1}/{total_frames}  "
                        f"~{remaining:.0f}s left",
                    )
            proc.stdin.close()
        except BrokenPipeError as e:
            raise RuntimeError(
                "FFmpeg closed the pipe unexpectedly. See log for ffmpeg stderr."
            ) from e
        finally:
            if bg_source is not None:
                bg_source.close()

        rc = proc.wait()
        stderr_tail = b""
        if proc.stderr is not None:
            try:
                stderr_tail = proc.stderr.read()
            except Exception:
                pass
            finally:
                proc.stderr.close()
        if rc != 0:
            err_text = stderr_tail.decode("utf-8", errors="ignore")[-1500:]
            log.error("FFmpeg failed (rc=%s)\ncmd: %s\nstderr:\n%s",
                      rc, " ".join(encoder_cmd), err_text)
            short = err_text.strip().splitlines()[-1] if err_text.strip() else ""
            if not short:
                short = (
                    "FFmpeg returned a non-zero exit code. "
                    "See logs/app.log for full details."
                )
            raise RuntimeError(f"FFmpeg failed (rc={rc}): {short}")

        if on_progress:
            on_progress(1.0, f"Done: {out.name}")
        log.info("Render finished: %s (%.1fs)", out, time.time() - start)
        return out

    # ------------------------------------------------------------------
    def _encoder_cmd(self, ffmpeg_path: str, config: RenderConfig,
                     out: Path) -> List[str]:
        encoder = config.encoder or "libx264"
        if config.low_spec and encoder == "libx264":
            preset = "veryfast"
        else:
            preset = config.quality_preset or "medium"

        cmd: List[str] = [
            ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error",
            # Video from stdin
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{config.width}x{config.height}", "-r", str(config.fps),
            "-i", "-",
            # Audio from the source file
            "-i", str(config.audio_path),
            "-map", "0:v:0", "-map", "1:a:0?",
            # Encoder
            "-c:v", encoder,
        ]
        if encoder == "libx264":
            cmd += ["-preset", preset, "-crf", str(config.crf), "-pix_fmt", "yuv420p"]
        elif encoder == "h264_nvenc":
            cmd += ["-preset", "p5", "-rc", "vbr", "-cq", str(config.crf),
                     "-b:v", str(config.bitrate), "-pix_fmt", "yuv420p"]
        elif encoder == "h264_qsv":
            cmd += ["-preset", "medium", "-global_quality", str(config.crf),
                     "-pix_fmt", "yuv420p"]
        elif encoder == "h264_amf":
            cmd += ["-quality", "balanced", "-rc", "vbr_peak",
                     "-b:v", str(config.bitrate), "-pix_fmt", "yuv420p"]
        else:
            cmd += ["-pix_fmt", "yuv420p"]

        # Audio: re-encode to AAC to keep MP4 compatibility predictable.
        cmd += [
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(out),
        ]
        return cmd


# ---------------------------------------------------------------------------
# Helpers used by UI
# ---------------------------------------------------------------------------

def default_output_path(audio_path: str, output_folder: str,
                         extension: str = "mp4") -> Path:
    stem = safe_filename(Path(audio_path).stem)
    return Path(output_folder) / f"{stem}.{extension.lstrip('.')}"
