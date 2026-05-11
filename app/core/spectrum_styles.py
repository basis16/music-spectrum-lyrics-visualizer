"""Spectrum visualisations.

Each style takes:

* ``levels`` – a 1-D ``numpy`` array of magnitudes in ``[0, 1]`` for the
  current video frame (length is the user-chosen bar count),
* an ``size = (width, height)`` for the spectrum area,
* a :class:`SpectrumStyleOptions` describing colours, glow, etc,

and returns an ``RGBA`` :class:`PIL.Image.Image` sized exactly
``width x height``. The renderer paints that image into the final frame
according to the requested position.

All styles strive to be GPU-free, dependency-light (PIL + numpy only)
and quick enough for live preview on weak hardware. Heavy glow effects
are gated behind the ``glow`` flag so Low-Spec Mode can disable them.
"""
from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

RGBA = Tuple[int, int, int, int]

# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

@dataclass
class SpectrumStyleOptions:
    style: str = "Modern Bars"
    color: RGBA = (90, 200, 255, 255)
    gradient: bool = True
    gradient_color: RGBA = (255, 90, 200, 255)
    glow: bool = True
    glow_strength: float = 1.0          # 0..2
    smoothness: float = 0.35            # 0..1 (temporal smoothing applied upstream)
    sensitivity: float = 1.15           # 0.5..3
    bar_count: int = 64
    size: Tuple[int, int] = (1280, 360)
    position: str = "bottom"            # bottom, top, center, left, right
    line_width: int = 4
    background_alpha: int = 0           # 0..255 backdrop behind the spectrum

    def with_size(self, size: Tuple[int, int]) -> "SpectrumStyleOptions":
        new = SpectrumStyleOptions(**self.__dict__)
        new.size = size
        return new


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_levels(levels: np.ndarray, n: int) -> np.ndarray:
    """Resample / pad ``levels`` to length ``n``."""
    if levels.size == n:
        return levels
    if levels.size == 0:
        return np.zeros(n, dtype=np.float32)
    xs = np.linspace(0, 1, levels.size)
    xt = np.linspace(0, 1, n)
    return np.interp(xt, xs, levels).astype(np.float32)


def _lerp_color(a: RGBA, b: RGBA, t: float) -> RGBA:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
        int(a[3] + (b[3] - a[3]) * t),
    )


def _with_alpha(rgba: RGBA, alpha: int) -> RGBA:
    return (rgba[0], rgba[1], rgba[2], max(0, min(255, alpha)))


def _glow(img: Image.Image, strength: float) -> Image.Image:
    """Return a glow layer derived from ``img`` (its colour-bearing pixels)."""
    if strength <= 0:
        return Image.new("RGBA", img.size, (0, 0, 0, 0))
    radius = max(1, int(8 * strength))
    blur = img.filter(ImageFilter.GaussianBlur(radius=radius))
    # Brighten the alpha channel a bit so glow reads.
    r, g, b, a = blur.split()
    a = a.point(lambda v: min(255, int(v * (1.0 + 0.5 * strength))))
    return Image.merge("RGBA", (r, g, b, a))


def _composite(base: Image.Image, layer: Image.Image) -> Image.Image:
    base.alpha_composite(layer)
    return base


def _gradient_color(t: float, opts: SpectrumStyleOptions) -> RGBA:
    if opts.gradient:
        return _lerp_color(opts.color, opts.gradient_color, t)
    return opts.color


def _base_canvas(opts: SpectrumStyleOptions) -> Image.Image:
    canvas = Image.new("RGBA", opts.size, (0, 0, 0, opts.background_alpha))
    return canvas


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _modern_bars(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    w, h = opts.size
    canvas = _base_canvas(opts)
    draw = ImageDraw.Draw(canvas)
    n = max(2, opts.bar_count)
    lv = _ensure_levels(levels, n)
    gap = max(2, w // (n * 8))
    bar_w = max(2, (w - gap * (n + 1)) // n)
    for i, v in enumerate(lv):
        bar_h = int(v * (h - 6))
        x0 = gap + i * (bar_w + gap)
        y0 = h - bar_h
        col = _gradient_color(i / max(1, n - 1), opts)
        # Rounded top bar
        radius = min(bar_w // 2, 12)
        draw.rounded_rectangle([x0, y0, x0 + bar_w, h], radius=radius, fill=col)
    if opts.glow:
        canvas = _composite(_glow(canvas, opts.glow_strength), canvas)
    return canvas


def _smooth_wave(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    w, h = opts.size
    canvas = _base_canvas(opts)
    n = max(8, opts.bar_count * 2)
    lv = _ensure_levels(levels, n)
    pts: List[Tuple[float, float]] = []
    for i, v in enumerate(lv):
        x = i * (w / (n - 1))
        y = h - v * (h - 8) - 4
        pts.append((x, y))

    # Catmull-Rom-ish smoothing via simple bezier-ish midpoints.
    smooth_pts: List[Tuple[float, float]] = [pts[0]]
    for i in range(1, len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        smooth_pts.append(((x0 + x1) / 2.0, (y0 + y1) / 2.0))
    smooth_pts.append(pts[-1])

    line_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    line_draw = ImageDraw.Draw(line_layer)
    line_draw.line(smooth_pts, fill=opts.color, width=max(2, opts.line_width), joint="curve")

    # Fill underneath the line for a "wave" feel.
    fill_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fill_draw = ImageDraw.Draw(fill_layer)
    poly = smooth_pts + [(w, h), (0, h)]
    fill_color = _with_alpha(_gradient_color(0.5, opts), 90)
    fill_draw.polygon(poly, fill=fill_color)

    canvas = _composite(canvas, fill_layer)
    canvas = _composite(canvas, line_layer)
    if opts.glow:
        canvas = _composite(_glow(line_layer, opts.glow_strength), canvas)
    return canvas


def _circular(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    w, h = opts.size
    canvas = _base_canvas(opts)
    draw = ImageDraw.Draw(canvas)
    n = max(16, opts.bar_count)
    lv = _ensure_levels(levels, n)
    cx, cy = w / 2.0, h / 2.0
    radius = min(w, h) * 0.25
    max_len = min(w, h) * 0.22
    for i, v in enumerate(lv):
        angle = (i / n) * 2 * math.pi - math.pi / 2
        length = max(2, v * max_len)
        x0 = cx + math.cos(angle) * radius
        y0 = cy + math.sin(angle) * radius
        x1 = cx + math.cos(angle) * (radius + length)
        y1 = cy + math.sin(angle) * (radius + length)
        col = _gradient_color(i / max(1, n - 1), opts)
        draw.line([(x0, y0), (x1, y1)], fill=col, width=max(2, opts.line_width))
    # Center ring
    ring_col = _with_alpha(opts.color, 180)
    draw.ellipse(
        [cx - radius - 2, cy - radius - 2, cx + radius + 2, cy + radius + 2],
        outline=ring_col, width=2,
    )
    if opts.glow:
        canvas = _composite(_glow(canvas, opts.glow_strength), canvas)
    return canvas


def _radial_pulse(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    w, h = opts.size
    canvas = _base_canvas(opts)
    draw = ImageDraw.Draw(canvas)
    n = max(16, opts.bar_count)
    lv = _ensure_levels(levels, n)
    cx, cy = w / 2.0, h / 2.0
    rings = 4
    max_r = min(w, h) * 0.42
    overall = float(lv.mean())
    for r_i in range(rings):
        t = r_i / max(1, rings - 1)
        radius = max_r * (0.35 + 0.65 * t) * (0.8 + 0.4 * overall)
        col = _with_alpha(_gradient_color(t, opts), int(180 - 35 * r_i))
        draw.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            outline=col, width=max(2, opts.line_width),
        )
    # Spokes that follow per-bin energy.
    for i, v in enumerate(lv):
        angle = (i / n) * 2 * math.pi
        length = v * max_r * 0.6
        x1 = cx + math.cos(angle) * length
        y1 = cy + math.sin(angle) * length
        col = _gradient_color(i / max(1, n - 1), opts)
        draw.line([(cx, cy), (x1, y1)], fill=_with_alpha(col, 200), width=2)
    if opts.glow:
        canvas = _composite(_glow(canvas, opts.glow_strength), canvas)
    return canvas


def _neon_equalizer(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    w, h = opts.size
    canvas = _base_canvas(opts)
    draw = ImageDraw.Draw(canvas)
    n = max(8, opts.bar_count)
    lv = _ensure_levels(levels, n)
    gap = max(2, w // (n * 8))
    bar_w = max(3, (w - gap * (n + 1)) // n)
    segment_h = max(4, h // 28)
    for i, v in enumerate(lv):
        segs = int(v * (h // (segment_h + 2)))
        for s in range(segs):
            y1 = h - (s + 1) * (segment_h + 2)
            y0 = y1 + segment_h
            x0 = gap + i * (bar_w + gap)
            # Color shifts as we go up.
            col = _gradient_color(s / max(1, segs - 1) if segs > 1 else 0, opts)
            draw.rectangle([x0, y1, x0 + bar_w, y0], fill=col)
    if opts.glow:
        canvas = _composite(_glow(canvas, opts.glow_strength), canvas)
    return canvas


def _minimal_line(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    w, h = opts.size
    canvas = _base_canvas(opts)
    draw = ImageDraw.Draw(canvas)
    n = max(64, opts.bar_count * 2)
    lv = _ensure_levels(levels, n)
    pts = [(i * (w / (n - 1)), h - v * (h - 6) - 3) for i, v in enumerate(lv)]
    draw.line(pts, fill=opts.color, width=max(2, opts.line_width))
    if opts.glow:
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(layer).line(pts, fill=opts.color, width=max(2, opts.line_width))
        canvas = _composite(_glow(layer, opts.glow_strength * 0.6), canvas)
    return canvas


def _particle(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    w, h = opts.size
    canvas = _base_canvas(opts)
    draw = ImageDraw.Draw(canvas)
    n = max(16, opts.bar_count)
    lv = _ensure_levels(levels, n)
    rng = np.random.default_rng(int(np.clip(lv.sum() * 1000, 0, 1_000_000)))
    for i, v in enumerate(lv):
        col = _gradient_color(i / max(1, n - 1), opts)
        cx_band = (i + 0.5) * (w / n)
        count = int(v * 14) + 1
        for _ in range(count):
            dx = rng.normal(0, w / (n * 1.5))
            dy = rng.normal(0, h * 0.25 * v)
            x = cx_band + dx
            y = h - 12 - abs(dy)
            r = max(1, int(2 + v * 4))
            draw.ellipse([x - r, y - r, x + r, y + r], fill=col)
    if opts.glow:
        canvas = _composite(_glow(canvas, opts.glow_strength), canvas)
    return canvas


def _glow_waveform(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    """Soft, neon waveform centered vertically."""
    w, h = opts.size
    canvas = _base_canvas(opts)
    n = max(64, opts.bar_count * 2)
    lv = _ensure_levels(levels, n)
    center = h / 2.0
    amp = (h / 2.0) - 6
    top: List[Tuple[float, float]] = []
    bot: List[Tuple[float, float]] = []
    for i, v in enumerate(lv):
        x = i * (w / (n - 1))
        top.append((x, center - v * amp))
        bot.append((x, center + v * amp))

    line_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(line_layer)
    ld.line(top, fill=opts.color, width=max(2, opts.line_width))
    ld.line(bot, fill=_gradient_color(0.7, opts), width=max(2, opts.line_width))

    canvas = _composite(canvas, line_layer)
    if opts.glow:
        canvas = _composite(_glow(line_layer, opts.glow_strength * 1.4), canvas)
    return canvas


def _mirror_bars(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    w, h = opts.size
    canvas = _base_canvas(opts)
    draw = ImageDraw.Draw(canvas)
    n = max(2, opts.bar_count)
    lv = _ensure_levels(levels, n)
    gap = max(2, w // (n * 8))
    bar_w = max(2, (w - gap * (n + 1)) // n)
    center = h / 2.0
    half = (h / 2.0) - 4
    for i, v in enumerate(lv):
        bar_h = int(v * half)
        x0 = gap + i * (bar_w + gap)
        col_top = _gradient_color(i / max(1, n - 1), opts)
        col_bot = _with_alpha(col_top, 200)
        draw.rounded_rectangle(
            [x0, center - bar_h, x0 + bar_w, center], radius=min(bar_w // 2, 10), fill=col_top,
        )
        draw.rounded_rectangle(
            [x0, center, x0 + bar_w, center + bar_h], radius=min(bar_w // 2, 10), fill=col_bot,
        )
    if opts.glow:
        canvas = _composite(_glow(canvas, opts.glow_strength), canvas)
    return canvas


def _center_pulse(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    """Symmetric pulse expanding from the center."""
    w, h = opts.size
    canvas = _base_canvas(opts)
    draw = ImageDraw.Draw(canvas)
    n = max(2, opts.bar_count)
    lv = _ensure_levels(levels, n)
    half = n // 2
    gap = max(2, w // (n * 8))
    bar_w = max(2, (w - gap * (n + 1)) // n)
    cx = w / 2.0
    for k in range(half):
        v = lv[k]
        bar_h = int(v * (h - 6))
        col = _gradient_color(k / max(1, half - 1), opts)
        # Right side
        xr = cx + gap / 2 + k * (bar_w + gap)
        draw.rounded_rectangle(
            [xr, h - bar_h, xr + bar_w, h], radius=min(bar_w // 2, 10), fill=col,
        )
        # Left side mirror
        xl = cx - gap / 2 - (k + 1) * (bar_w + gap) + gap
        draw.rounded_rectangle(
            [xl, h - bar_h, xl + bar_w, h], radius=min(bar_w // 2, 10), fill=col,
        )
    if opts.glow:
        canvas = _composite(_glow(canvas, opts.glow_strength), canvas)
    return canvas


def _dual_ribbon(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    """Bonus modern style: two interleaved ribbons."""
    w, h = opts.size
    canvas = _base_canvas(opts)
    n = max(16, opts.bar_count)
    lv = _ensure_levels(levels, n)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    pts_top: List[Tuple[float, float]] = []
    pts_bot: List[Tuple[float, float]] = []
    for i, v in enumerate(lv):
        x = i * (w / (n - 1))
        wobble = math.sin((i / n) * 2 * math.pi + v * 6) * h * 0.05
        pts_top.append((x, h * 0.45 - v * h * 0.35 + wobble))
        pts_bot.append((x, h * 0.55 + v * h * 0.35 - wobble))
    ld.line(pts_top, fill=opts.color, width=max(2, opts.line_width))
    ld.line(pts_bot, fill=_gradient_color(0.8, opts), width=max(2, opts.line_width))
    canvas = _composite(canvas, layer)
    if opts.glow:
        canvas = _composite(_glow(layer, opts.glow_strength), canvas)
    return canvas


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

StyleFunc = Callable[[np.ndarray, SpectrumStyleOptions], Image.Image]

_STYLES: Dict[str, StyleFunc] = {
    "Modern Bars":          _modern_bars,
    "Smooth Wave":          _smooth_wave,
    "Circular Spectrum":    _circular,
    "Radial Pulse":         _radial_pulse,
    "Neon Equalizer":       _neon_equalizer,
    "Minimal Line Spectrum": _minimal_line,
    "Particle Spectrum":    _particle,
    "Glow Waveform":        _glow_waveform,
    "Mirror Bars":          _mirror_bars,
    "Center Pulse Spectrum": _center_pulse,
    "Dual Ribbon":          _dual_ribbon,
}


def available_styles() -> List[str]:
    return list(_STYLES.keys())


def render_style(levels: np.ndarray, opts: SpectrumStyleOptions) -> Image.Image:
    """Render a single frame of the chosen spectrum style."""
    fn = _STYLES.get(opts.style)
    if fn is None:
        fn = _modern_bars
    return fn(np.asarray(levels, dtype=np.float32), opts)


def preset_color(name: str) -> Tuple[RGBA, RGBA]:
    """Return ``(primary, secondary)`` colour for a named preset."""
    presets = {
        "Aqua Magenta": ((90, 200, 255, 255), (255, 90, 200, 255)),
        "Sunset":       ((255, 138, 80, 255), (255, 60, 120, 255)),
        "Forest":       ((110, 220, 140, 255), (40, 160, 120, 255)),
        "Royal":        ((130, 90, 255, 255), (60, 200, 255, 255)),
        "Monochrome":   ((240, 240, 240, 255), (200, 200, 200, 255)),
        "Inferno":      ((255, 200, 60, 255), (255, 60, 60, 255)),
    }
    return presets.get(name, presets["Aqua Magenta"])


def hsv_to_rgba(h: float, s: float, v: float, a: int = 255) -> RGBA:
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255), a)
