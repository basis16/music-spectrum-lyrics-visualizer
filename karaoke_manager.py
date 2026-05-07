"""Karaoke / lyric overlay rendering.

Composes the active lyric line onto the video frame above the bar spectrum.
Supports four display modes:

- ``NORMAL``         - solid colour text, no per-word effect
- ``KARAOKE_LINE``   - whole line flashes to highlight colour during its window
- ``KARAOKE_WORD``   - words turn highlight colour as their timestamp passes
- ``KARAOKE_SWEEP``  - smooth left-to-right horizontal wipe across the line
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from logger_manager import get_logger
from lyric_generator import LyricLine, LyricsTrack
from settings import LyricConfig, LyricMode

log = get_logger(__name__)


@dataclass
class _PreparedLine:
    line: LyricLine
    text_image: Image.Image            # base RGBA image of the text
    text_image_hl: Image.Image         # highlight-coloured copy
    word_boxes: List[Tuple[int, int]]  # (x_start, x_end) per word in text_image


class KaraokeOverlay:
    """Pre-computes per-line bitmaps to keep the render loop hot."""

    def __init__(self, cfg: LyricConfig, track: LyricsTrack,
                 frame_w: int, frame_h: int) -> None:
        self.cfg = cfg
        self.track = track
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.font = self._load_font()
        self._prepared: List[_PreparedLine] = []
        if cfg.mode != LyricMode.NONE and track and track.lines:
            self._prepare()

    # ------------------------------------------------------------------
    # Pre-computation
    # ------------------------------------------------------------------
    def _load_font(self) -> ImageFont.FreeTypeFont:
        try:
            if self.cfg.font_path:
                return ImageFont.truetype(self.cfg.font_path, int(self.cfg.font_size))
            # Try a few common fonts.
            for name in ("DejaVuSans-Bold.ttf", "Arial.ttf", "arial.ttf",
                         "LiberationSans-Bold.ttf"):
                try:
                    return ImageFont.truetype(name, int(self.cfg.font_size))
                except Exception:
                    continue
        except Exception:
            pass
        return ImageFont.load_default()

    def _prepare(self) -> None:
        for line in self.track.lines:
            normal = self._render_line(line.text, self.cfg.color_normal)
            highlight = self._render_line(line.text, self.cfg.color_highlight)
            boxes = self._word_boxes(line)
            self._prepared.append(_PreparedLine(
                line=line, text_image=normal, text_image_hl=highlight,
                word_boxes=boxes,
            ))
        log.info("Prepared %d karaoke lines.", len(self._prepared))

    def _render_line(self, text: str, color: tuple[int, int, int]) -> Image.Image:
        """Render text with outline + optional shadow + glow into an RGBA image."""
        cfg = self.cfg
        font = self.font
        # Measure
        tmp = Image.new("RGBA", (10, 10))
        d = ImageDraw.Draw(tmp)
        try:
            bbox = d.textbbox((0, 0), text, font=font, stroke_width=cfg.outline)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            x_off = -bbox[0]
            y_off = -bbox[1]
        except Exception:  # very old Pillow / default font
            tw, th = font.getsize(text)
            x_off = y_off = 0

        pad = max(20, cfg.outline * 4 + (12 if cfg.glow else 0))
        img = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        x, y = pad + x_off, pad + y_off

        if cfg.shadow:
            draw.text((x + 2, y + 3), text, font=font,
                      fill=(0, 0, 0, 200))

        draw.text((x, y), text, font=font,
                  fill=color + (int(255 * cfg.opacity),),
                  stroke_width=int(cfg.outline),
                  stroke_fill=cfg.outline_color + (255,))

        if cfg.glow:
            glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).text((x, y), text, font=font,
                                      fill=color + (200,))
            glow = glow.filter(ImageFilter.GaussianBlur(radius=6))
            img = Image.alpha_composite(glow, img)
        return img

    def _word_boxes(self, line: LyricLine) -> List[Tuple[int, int]]:
        """Compute (x_start, x_end) of each word inside the rendered line image."""
        if not line.words:
            return []
        cfg = self.cfg
        font = self.font
        tmp = Image.new("RGBA", (10, 10))
        d = ImageDraw.Draw(tmp)
        # Reproduce padding from _render_line.
        try:
            bbox = d.textbbox((0, 0), line.text, font=font, stroke_width=cfg.outline)
            x_off = -bbox[0]
        except Exception:
            x_off = 0
        pad = max(20, cfg.outline * 4 + (12 if cfg.glow else 0))
        cursor = pad + x_off

        boxes: List[Tuple[int, int]] = []
        # Walk the word list in original order; insert spaces between them.
        accumulated = ""
        for i, w in enumerate(line.words):
            prefix = "" if i == 0 else " "
            accumulated_prev = accumulated + prefix
            try:
                bbox_a = d.textbbox((0, 0), accumulated_prev, font=font,
                                    stroke_width=cfg.outline)
                bbox_b = d.textbbox((0, 0), accumulated_prev + w.text, font=font,
                                    stroke_width=cfg.outline)
                start = pad + x_off + (bbox_a[2] - bbox_a[0]) - x_off
                end = pad + x_off + (bbox_b[2] - bbox_b[0]) - x_off
            except Exception:
                start = cursor
                end = cursor + len(w.text) * 12
            boxes.append((int(start), int(end)))
            accumulated = accumulated_prev + w.text
            cursor = end
        return boxes

    # ------------------------------------------------------------------
    # Frame composition
    # ------------------------------------------------------------------
    def _active(self, t: float) -> Optional[_PreparedLine]:
        for pl in self._prepared:
            if pl.line.start <= t <= pl.line.end + 0.05:
                return pl
        # Show a line a little before it starts (smoother visual).
        for pl in self._prepared:
            if pl.line.start - 0.4 <= t < pl.line.start:
                return pl
        return None

    def draw_on(self, frame_bgr: np.ndarray, t: float) -> np.ndarray:
        if self.cfg.mode == LyricMode.NONE or not self._prepared:
            return frame_bgr
        pl = self._active(t)
        if pl is None:
            return frame_bgr

        text_img = self._compose_for_time(pl, t)
        if text_img is None:
            return frame_bgr

        x = (self.frame_w - text_img.shape[1]) // 2
        y = int(self.frame_h * self.cfg.y_ratio - text_img.shape[0] // 2)
        # Clamp into frame.
        y = max(8, min(self.frame_h - text_img.shape[0] - 8, y))
        _alpha_blit_bgr(frame_bgr, text_img, x, y, opacity=1.0)
        return frame_bgr

    def _compose_for_time(self, pl: _PreparedLine, t: float) -> Optional[np.ndarray]:
        cfg = self.cfg
        normal = pl.text_image
        highlight = pl.text_image_hl
        line = pl.line

        if cfg.mode == LyricMode.NORMAL:
            return np.array(normal)

        if cfg.mode == LyricMode.KARAOKE_LINE:
            # Flash whole line during its window.
            if line.start <= t <= line.end:
                return np.array(highlight)
            return np.array(normal)

        if cfg.mode == LyricMode.KARAOKE_SWEEP:
            # Linearly sweep highlight from left -> right within the line window.
            if line.end <= line.start:
                return np.array(normal)
            p = (t - line.start) / (line.end - line.start)
            p = max(0.0, min(1.0, p))
            return _composite_sweep(normal, highlight, p)

        # KARAOKE_WORD: highlight only words whose timestamp has passed.
        if not pl.word_boxes or not line.words:
            return np.array(normal)
        active_idx = -1
        for i, w in enumerate(line.words):
            if w.start <= t:
                active_idx = i
            if w.end < t:
                continue
            else:
                break
        if active_idx < 0:
            return np.array(normal)
        # Find pixel x at the end of the active word.
        cutoff = pl.word_boxes[min(active_idx, len(pl.word_boxes) - 1)][1]
        # Within the active word, partial fill based on progress through the word.
        word = line.words[min(active_idx, len(line.words) - 1)]
        if word.end > word.start:
            frac = max(0.0, min(1.0, (t - word.start) / (word.end - word.start)))
            box = pl.word_boxes[min(active_idx, len(pl.word_boxes) - 1)]
            cutoff = int(box[0] + (box[1] - box[0]) * frac)
        return _composite_split(normal, highlight, cutoff)


# ---------------------------------------------------------------------------
# Pixel composition helpers
# ---------------------------------------------------------------------------
def _composite_sweep(normal: Image.Image, highlight: Image.Image,
                     progress: float) -> np.ndarray:
    """Soft-edge horizontal wipe between normal and highlight."""
    w, h = normal.size
    cutoff = int(w * progress)
    feather = max(8, w // 80)

    # Build a horizontal mask.
    xs = np.arange(w, dtype=np.float32)
    mask = np.clip((cutoff - xs) / feather + 0.5, 0.0, 1.0)
    mask_img = Image.fromarray((mask * 255).astype(np.uint8))
    mask_img = mask_img.resize((w, h))
    out = Image.composite(highlight, normal, mask_img)
    return np.array(out)


def _composite_split(normal: Image.Image, highlight: Image.Image,
                     cutoff_x: int) -> np.ndarray:
    """Hard split: highlight to the left of ``cutoff_x``, normal to the right."""
    w, h = normal.size
    cutoff_x = max(0, min(w, cutoff_x))
    arr_norm = np.array(normal)
    arr_hl = np.array(highlight)
    arr_norm[:, :cutoff_x] = arr_hl[:, :cutoff_x]
    return arr_norm


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
