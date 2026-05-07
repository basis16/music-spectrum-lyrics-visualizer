"""Logo / watermark overlay.

The :class:`LogoOverlay` is constructed once (loads + resizes the image, builds
animation curves) and then queried each frame via :meth:`draw_on`.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import numpy as np

from logger_manager import get_logger
from settings import LogoAnim, LogoConfig, LogoPos

log = get_logger(__name__)


class LogoOverlay:
    """Composes a PNG/JPG logo onto each video frame."""

    def __init__(self, cfg: LogoConfig, frame_w: int, frame_h: int) -> None:
        self.cfg = cfg
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.rgba: Optional[np.ndarray] = None
        if not cfg.enabled or not cfg.path:
            return
        self.rgba = self._load(cfg.path, frame_w, cfg.size_ratio)

    @staticmethod
    def _load(path: str, frame_w: int, size_ratio: float) -> Optional[np.ndarray]:
        from PIL import Image

        try:
            img = Image.open(path).convert("RGBA")
        except Exception as exc:
            log.warning("Failed to load logo %s: %s", path, exc)
            return None
        target_w = max(8, int(frame_w * float(size_ratio)))
        ratio = target_w / img.width
        target_h = max(8, int(img.height * ratio))
        img = img.resize((target_w, target_h), Image.LANCZOS)
        return np.array(img)

    def position(self) -> tuple[int, int]:
        if self.rgba is None:
            return 0, 0
        h, w = self.rgba.shape[:2]
        m = self.cfg.margin
        if self.cfg.position == LogoPos.TOP_LEFT:
            return m, m
        if self.cfg.position == LogoPos.TOP_RIGHT:
            return self.frame_w - w - m, m
        if self.cfg.position == LogoPos.BOTTOM_LEFT:
            return m, self.frame_h - h - m
        if self.cfg.position == LogoPos.BOTTOM_RIGHT:
            return self.frame_w - w - m, self.frame_h - h - m
        # CENTER
        return (self.frame_w - w) // 2, (self.frame_h - h) // 2

    def _anim_factor(self, t: float, duration: float) -> tuple[float, float]:
        """Return (opacity_factor, scale_factor) for the current time."""
        if self.cfg.animation == LogoAnim.NONE:
            return 1.0, 1.0
        if self.cfg.animation == LogoAnim.FADE_IN:
            # 0..1.5s ease-in.
            f = min(1.0, max(0.0, t / 1.5))
            return f, 1.0
        if self.cfg.animation == LogoAnim.FADE_OUT:
            # last 1.5s ease-out.
            remain = duration - t
            f = min(1.0, max(0.0, remain / 1.5))
            return f, 1.0
        if self.cfg.animation == LogoAnim.PULSE:
            # subtle 0.95..1.05 sine, period 2s.
            return 1.0, 1.0 + 0.05 * math.sin(t * math.pi)
        if self.cfg.animation == LogoAnim.ZOOM:
            # 0.85 -> 1.0 over first 1s, then steady.
            f = min(1.0, t / 1.0)
            return 1.0, 0.85 + 0.15 * f
        return 1.0, 1.0

    def draw_on(self, frame: np.ndarray, t: float, duration: float) -> np.ndarray:
        """Alpha-composite the logo onto a BGR frame in-place. Returns the frame."""
        if self.rgba is None:
            return frame
        opacity_f, scale_f = self._anim_factor(t, duration)
        rgba = self.rgba
        if abs(scale_f - 1.0) > 1e-3:
            from PIL import Image

            h, w = rgba.shape[:2]
            new_w = max(2, int(w * scale_f))
            new_h = max(2, int(h * scale_f))
            rgba = np.array(Image.fromarray(rgba).resize((new_w, new_h), Image.LANCZOS))

        x, y = self.position()
        # When scaling, recentre around the original anchor.
        h, w = rgba.shape[:2]
        x = int(x + (self.rgba.shape[1] - w) // 2)
        y = int(y + (self.rgba.shape[0] - h) // 2)

        _alpha_blit_bgr(frame, rgba, x, y,
                        opacity=float(self.cfg.opacity) * opacity_f)
        return frame


def _alpha_blit_bgr(frame_bgr: np.ndarray, rgba: np.ndarray,
                    x: int, y: int, opacity: float = 1.0) -> None:
    """Alpha-blend an RGBA image onto a BGR frame at (x, y), in-place."""
    if rgba.size == 0 or opacity <= 0:
        return
    fh, fw = frame_bgr.shape[:2]
    h, w = rgba.shape[:2]
    # Clip rectangle to frame bounds.
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fw, x + w), min(fh, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    src_x0, src_y0 = x0 - x, y0 - y
    src_x1, src_y1 = src_x0 + (x1 - x0), src_y0 + (y1 - y0)
    src = rgba[src_y0:src_y1, src_x0:src_x1]
    dst = frame_bgr[y0:y1, x0:x1]

    # RGBA -> BGRA component reorder, then blend.
    src_rgb = src[..., :3][..., ::-1].astype(np.float32)
    src_a = (src[..., 3:4].astype(np.float32) / 255.0) * float(opacity)
    dst_f = dst.astype(np.float32)
    out = src_rgb * src_a + dst_f * (1.0 - src_a)
    dst[...] = np.clip(out, 0, 255).astype(np.uint8)
