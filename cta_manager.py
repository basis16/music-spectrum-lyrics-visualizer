"""CTA (Call-To-Action) overlay.

Renders a Subscribe-style button in the centre of the frame for a window of
time. Multiple animation presets are supported:

- POP / BOUNCE / YOUTUBE: scale-based pop-up
- SLIDE: horizontal slide-in
- BELL: pop-up + bell jiggle
- LIKE_SUB: shows two stacked buttons (like + subscribe)
- MINIMAL: clean fade
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from logger_manager import get_logger
from settings import CTAAnim, CTAConfig, CTATiming

log = get_logger(__name__)


class CTAOverlay:
    def __init__(self, cfg: CTAConfig, frame_w: int, frame_h: int,
                 video_duration: float, font_path: Optional[str] = None) -> None:
        self.cfg = cfg
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.duration = video_duration
        self.font_path = font_path
        self.start, self.end = self._compute_window()
        log.info("CTA window: %.2fs .. %.2fs (animation=%s)",
                 self.start, self.end, cfg.animation.value if cfg.enabled else "off")

    def _compute_window(self) -> tuple[float, float]:
        cfg = self.cfg
        d = max(0.5, float(cfg.duration))
        if not cfg.enabled or self.duration <= 0:
            return -1.0, -1.0
        if cfg.timing == CTATiming.START:
            start = max(0.5, 1.0)
        elif cfg.timing == CTATiming.END:
            start = max(0.0, self.duration - d - 1.0)
        elif cfg.timing == CTATiming.CUSTOM:
            start = float(cfg.custom_time)
        else:  # MIDDLE
            start = max(0.0, self.duration / 2.0 - d / 2.0)
        return float(start), float(start + d)

    # -- timing ---------------------------------------------------------
    def is_active(self, t: float) -> bool:
        return self.start <= t <= self.end

    def progress(self, t: float) -> float:
        if not self.is_active(t) or self.end <= self.start:
            return 0.0
        return (t - self.start) / (self.end - self.start)

    # -- public draw ----------------------------------------------------
    def draw_on(self, frame_bgr: np.ndarray, t: float) -> np.ndarray:
        """Composite the CTA onto a BGR frame in-place."""
        if not self.is_active(t):
            return frame_bgr
        rgba = self._render(t)
        if rgba is None:
            return frame_bgr
        x = (self.frame_w - rgba.shape[1]) // 2
        y = (self.frame_h - rgba.shape[0]) // 2
        # logo_manager has the blit helper; avoid circular import by inlining a shim.
        _alpha_blit_bgr(frame_bgr, rgba, x, y, opacity=1.0)
        return frame_bgr

    # ------------------------------------------------------------------
    # Internal rendering
    # ------------------------------------------------------------------
    def _easing(self, p: float) -> tuple[float, float, float]:
        """Return (alpha, scale, x_offset_ratio) for normalized progress p in [0,1]."""
        cfg = self.cfg
        # In/out 15% of duration each by default.
        in_p = min(1.0, p / 0.18)
        out_p = min(1.0, max(0.0, (1.0 - p) / 0.18))
        alpha = min(in_p, out_p)
        scale = 1.0
        x_off = 0.0

        anim = cfg.animation
        if anim == CTAAnim.POP or anim == CTAAnim.YOUTUBE:
            # ease-out-back on intro
            scale = 0.6 + 0.4 * (1 - (1 - in_p) ** 3)
        elif anim == CTAAnim.BOUNCE:
            scale = 0.6 + 0.4 * (1 - (1 - in_p) ** 3)
            if 0.18 < p < 0.45:
                scale += 0.05 * math.sin((p - 0.18) * 25.0)
        elif anim == CTAAnim.SLIDE:
            x_off = -1.0 + in_p
        elif anim == CTAAnim.BELL:
            scale = 0.6 + 0.4 * (1 - (1 - in_p) ** 3)
            # bell jiggle in middle
            if 0.25 < p < 0.55:
                x_off = 0.02 * math.sin((p - 0.25) * 40.0)
        elif anim == CTAAnim.MINIMAL:
            scale = 1.0  # fade only
        else:  # LIKE_SUB
            scale = 0.7 + 0.3 * (1 - (1 - in_p) ** 3)

        return float(alpha) * float(cfg.opacity), float(scale), float(x_off)

    def _render(self, t: float) -> Optional[np.ndarray]:
        cfg = self.cfg
        p = self.progress(t)
        alpha, scale, x_off = self._easing(p)
        if alpha <= 0.01:
            return None

        # Base button size.
        btn_w = max(120, int(self.frame_w * cfg.size_ratio))
        btn_h = max(48, int(btn_w * 0.32))

        text = cfg.text
        if cfg.animation == CTAAnim.LIKE_SUB:
            # render two stacked buttons: LIKE + SUBSCRIBE
            like_img = self._draw_button(btn_w, btn_h, "LIKE",
                                         (50, 130, 240), cfg.color_text, glow=cfg.glow)
            sub_img = self._draw_button(btn_w, btn_h, "SUBSCRIBE",
                                        cfg.color_button, cfg.color_text, glow=cfg.glow)
            gap = 16
            canvas_h = like_img.height + sub_img.height + gap
            canvas = Image.new("RGBA", (btn_w, canvas_h), (0, 0, 0, 0))
            canvas.paste(like_img, (0, 0), like_img)
            canvas.paste(sub_img, (0, like_img.height + gap), sub_img)
        elif cfg.animation == CTAAnim.BELL:
            sub_img = self._draw_button(btn_w, btn_h, text,
                                        cfg.color_button, cfg.color_text, glow=cfg.glow)
            bell = self._draw_bell(btn_h)
            canvas = Image.new("RGBA", (btn_w + bell.width + 12, btn_h), (0, 0, 0, 0))
            canvas.paste(sub_img, (0, 0), sub_img)
            canvas.paste(bell, (btn_w + 12, 0), bell)
        else:
            canvas = self._draw_button(btn_w, btn_h, text,
                                       cfg.color_button, cfg.color_text, glow=cfg.glow)

        # Apply scale + alpha.
        if abs(scale - 1.0) > 1e-3:
            new_w = max(2, int(canvas.width * scale))
            new_h = max(2, int(canvas.height * scale))
            canvas = canvas.resize((new_w, new_h), Image.LANCZOS)

        if alpha < 0.999:
            arr = np.array(canvas)
            arr[..., 3] = (arr[..., 3].astype(np.float32) * alpha).astype(np.uint8)
            canvas = Image.fromarray(arr, mode="RGBA")

        # x offset (for slide / bell jiggle): translate by adding transparent margin.
        if abs(x_off) > 1e-3:
            shift = int(x_off * self.frame_w)
            arr = np.array(canvas)
            new = np.zeros_like(arr)
            if shift >= 0:
                shift = min(shift, arr.shape[1] - 1)
                new[:, shift:] = arr[:, :arr.shape[1] - shift]
            else:
                shift = max(shift, -(arr.shape[1] - 1))
                new[:, :arr.shape[1] + shift] = arr[:, -shift:]
            canvas = Image.fromarray(new, mode="RGBA")

        return np.array(canvas)

    # -- primitive drawers ---------------------------------------------
    def _font(self, size: int) -> ImageFont.FreeTypeFont:
        try:
            if self.font_path:
                return ImageFont.truetype(self.font_path, size)
            return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
        except Exception:
            return ImageFont.load_default()

    def _draw_button(self, w: int, h: int, text: str,
                     color_button: tuple[int, int, int],
                     color_text: tuple[int, int, int],
                     glow: bool = True) -> Image.Image:
        # Pad for glow.
        pad = max(8, h // 4) if glow else 6
        img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        radius = h // 2
        rect = (pad, pad, pad + w, pad + h)
        draw.rounded_rectangle(rect, radius=radius, fill=color_button + (255,))

        # Text
        font = self._font(max(14, int(h * 0.5)))
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = font.getsize(text)
        tx = pad + (w - tw) // 2 - bbox[0]
        ty = pad + (h - th) // 2 - bbox[1]
        if self.cfg.shadow:
            draw.text((tx + 2, ty + 2), text, font=font, fill=(0, 0, 0, 180))
        draw.text((tx, ty), text, font=font, fill=color_text + (255,))

        if glow:
            glow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow_layer).rounded_rectangle(
                rect, radius=radius, fill=color_button + (220,))
            glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=pad * 0.6))
            return Image.alpha_composite(glow_layer, img)
        return img

    def _draw_bell(self, h: int) -> Image.Image:
        size = h
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # Bell body
        d.rounded_rectangle((size * 0.18, size * 0.18, size * 0.82, size * 0.7),
                            radius=int(size * 0.18), fill=(255, 215, 0, 255))
        d.ellipse((size * 0.40, size * 0.7, size * 0.6, size * 0.92),
                  fill=(255, 215, 0, 255))
        return img


# --------------------------------------------------------------------------
# Local copy of logo_manager._alpha_blit_bgr to avoid a circular import.
# --------------------------------------------------------------------------
def _alpha_blit_bgr(frame_bgr: np.ndarray, rgba: np.ndarray,
                    x: int, y: int, opacity: float = 1.0) -> None:
    if rgba.size == 0 or opacity <= 0:
        return
    fh, fw = frame_bgr.shape[:2]
    h, w = rgba.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(fw, x + w), min(fh, y + h)
    if x0 >= x1 or y0 >= y1:
        return
    src_x0, src_y0 = x0 - x, y0 - y
    src_x1, src_y1 = src_x0 + (x1 - x0), src_y0 + (y1 - y0)
    src = rgba[src_y0:src_y1, src_x0:src_x1]
    dst = frame_bgr[y0:y1, x0:x1]
    src_rgb = src[..., :3][..., ::-1].astype(np.float32)
    src_a = (src[..., 3:4].astype(np.float32) / 255.0) * float(opacity)
    dst_f = dst.astype(np.float32)
    out = src_rgb * src_a + dst_f * (1.0 - src_a)
    dst[...] = np.clip(out, 0, 255).astype(np.uint8)
