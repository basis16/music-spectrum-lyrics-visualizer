"""Video renderer.

Pipeline (single pass, low memory):

1. Pre-compute ``SpectrumFrames`` from the audio.
2. Open / loop the background as a frame iterator.
3. For each video frame:
     a. Get background BGR pixels.
     b. Draw the chosen spectrum style on top.
     c. Layer karaoke / lyrics on top of that.
     d. Layer the logo and (if active) the CTA.
4. Pipe raw BGR frames into FFmpeg via stdin; FFmpeg muxes the audio.

Because we control the frame loop, we can emit progress callbacks at every
single frame and cancel cleanly mid-render (just kill the FFmpeg subprocess
and stop yielding frames).
"""
from __future__ import annotations

import math
import os
import shutil
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import cv2
import numpy as np

import audio_analyzer
import ffmpeg_manager
from cta_manager import CTAOverlay
from karaoke_manager import KaraokeOverlay
from logger_manager import get_logger
from logo_manager import LogoOverlay
from lyric_generator import LyricsTrack
from settings import (
    BackgroundType,
    LyricMode,
    ProjectSettings,
    SpectrumStyle,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Background reader
# ---------------------------------------------------------------------------
class _BackgroundReader:
    """Yields a BGR frame on demand from an image, video or solid colour."""

    def __init__(self, settings: ProjectSettings, w: int, h: int,
                 total_frames: int, fps: int) -> None:
        self.w = w
        self.h = h
        self.total_frames = total_frames
        self.fps = fps
        self.kind = settings.background.kind
        self.path = settings.background.path
        self.solid = settings.background.solid_color
        self._cap: Optional[cv2.VideoCapture] = None
        self._image_frame: Optional[np.ndarray] = None
        self._video_n_frames = 0
        self._video_fps = float(fps)

        if self.kind == BackgroundType.IMAGE and self.path:
            img = cv2.imread(self.path, cv2.IMREAD_COLOR)
            if img is None:
                # Pillow fallback (handles webp etc).
                from PIL import Image
                pil = Image.open(self.path).convert("RGB")
                img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            self._image_frame = _fit_cover(img, w, h)
        elif self.kind == BackgroundType.VIDEO and self.path:
            self._cap = cv2.VideoCapture(self.path)
            if not self._cap.isOpened():
                log.warning("Video background failed to open, using solid colour.")
                self._cap = None
                self.kind = BackgroundType.SOLID
            else:
                self._video_n_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
                self._video_fps = float(self._cap.get(cv2.CAP_PROP_FPS) or fps)

    def read(self, frame_idx: int) -> np.ndarray:
        if self.kind == BackgroundType.IMAGE and self._image_frame is not None:
            return self._image_frame.copy()
        if self.kind == BackgroundType.VIDEO and self._cap is not None:
            return self._read_video_frame(frame_idx)
        # solid
        bgr = (self.solid[2], self.solid[1], self.solid[0])  # RGB->BGR
        canvas = np.full((self.h, self.w, 3), bgr, dtype=np.uint8)
        return canvas

    def _read_video_frame(self, frame_idx: int) -> np.ndarray:
        # Map the output video time (frame_idx / fps) onto the source video.
        # If shorter, loop. If longer, just trim.
        t = frame_idx / float(self.fps)
        src_idx = 0
        if self._video_fps > 0:
            src_idx = int((t * self._video_fps) % max(1, self._video_n_frames))
        cap = self._cap
        assert cap is not None
        cur = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if src_idx != cur:
            cap.set(cv2.CAP_PROP_POS_FRAMES, src_idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
            if not ok or frame is None:
                return np.zeros((self.h, self.w, 3), dtype=np.uint8)
        return _fit_cover(frame, self.w, self.h)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


def _fit_cover(img: np.ndarray, w: int, h: int) -> np.ndarray:
    """Resize ``img`` to cover (w,h) while preserving aspect ratio, then crop."""
    ih, iw = img.shape[:2]
    if iw == 0 or ih == 0:
        return np.zeros((h, w, 3), dtype=np.uint8)
    scale = max(w / iw, h / ih)
    new_w = max(1, int(round(iw * scale)))
    new_h = max(1, int(round(ih * scale)))
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    x = (new_w - w) // 2
    y = (new_h - h) // 2
    return resized[y:y + h, x:x + w]


# ---------------------------------------------------------------------------
# Spectrum drawing
# ---------------------------------------------------------------------------
class _SpectrumPainter:
    """Draws the active spectrum style on a frame in-place."""

    def __init__(self, settings: ProjectSettings, w: int, h: int) -> None:
        self.cfg = settings.spectrum
        self.w = w
        self.h = h
        # Pre-compute bar positions for the BAR style, as drawing a filled
        # rectangle thousands of times is the hot loop.
        self.style = self.cfg.style
        self.bar_count = max(8, int(self.cfg.bar_count))

    # -- public ---------------------------------------------------------
    def draw(self, frame: np.ndarray, levels: np.ndarray,
             beat: float, t: float) -> np.ndarray:
        if self.style == SpectrumStyle.BAR:
            return self._draw_bars(frame, levels, beat)
        if self.style == SpectrumStyle.NEON:
            return self._draw_bars(frame, levels, beat, neon=True)
        if self.style == SpectrumStyle.MODERN:
            return self._draw_bars(frame, levels, beat, modern=True)
        if self.style == SpectrumStyle.SMOOTH:
            return self._draw_bars(frame, levels, beat, smooth_curve=True)
        if self.style == SpectrumStyle.CIRCULAR:
            return self._draw_circular(frame, levels, beat, t)
        if self.style == SpectrumStyle.WAVEFORM:
            return self._draw_waveform(frame, levels, beat)
        return self._draw_bars(frame, levels, beat)

    # -- bars (base implementation used by several styles) -------------
    def _draw_bars(self, frame: np.ndarray, levels: np.ndarray, beat: float,
                   *, neon: bool = False, modern: bool = False,
                   smooth_curve: bool = False) -> np.ndarray:
        cfg = self.cfg
        w, h = self.w, self.h
        n = self.bar_count
        max_h = int(h * cfg.max_height_ratio)
        slot_w = w / n
        bar_w = max(2, int(slot_w * cfg.bar_width_ratio))

        beat_kick = 1.0 + 0.10 * float(beat)
        max_h = int(max_h * beat_kick)

        # Optional glow pass: draw bars on a separate canvas, blur, then add.
        glow_canvas: Optional[np.ndarray] = None
        if cfg.glow:
            glow_canvas = np.zeros((h, w, 3), dtype=np.uint8)

        # Drawing loop.
        for i in range(n):
            level = float(levels[i]) if i < len(levels) else 0.0
            bar_h = int(max_h * level)
            if bar_h <= 1:
                continue
            x_center = int(slot_w * (i + 0.5))
            x0 = x_center - bar_w // 2
            x1 = x0 + bar_w
            y1 = h - 8       # leave a tiny margin at the bottom
            y0 = y1 - bar_h

            color = self._bar_color(i, n, level)
            # When drawing on the main frame, use a soft top-down gradient by
            # painting two halves with a blend.
            if smooth_curve:
                # rounded bar via filled rounded rectangle.
                _rounded_rect(frame, (x0, y0), (x1, y1), color, radius=bar_w // 2)
            else:
                _gradient_bar(frame, x0, y0, x1, y1, color,
                              cfg.gradient_bottom, rounded=cfg.rounded)

            if neon or modern:
                # subtle inner-highlight
                hl = (min(255, color[0] + 60), min(255, color[1] + 60), min(255, color[2] + 60))
                cv2.line(frame, (x0 + 1, y0), (x1 - 1, y0), hl, 1)

            if glow_canvas is not None:
                cv2.rectangle(glow_canvas, (x0, y0), (x1, y1), color, thickness=-1)

            if cfg.reflection:
                # Horizontal mirror, half-opacity, below the baseline if room exists.
                refl_h = int(bar_h * 0.4)
                if refl_h > 1 and y1 + refl_h < h:
                    refl = (color[0] // 3, color[1] // 3, color[2] // 3)
                    cv2.rectangle(frame, (x0, y1 + 2), (x1, y1 + refl_h),
                                  refl, thickness=-1)

        # Apply glow.
        if glow_canvas is not None:
            blurred = cv2.GaussianBlur(glow_canvas, (0, 0), sigmaX=14, sigmaY=14)
            frame[:] = cv2.addWeighted(frame, 1.0, blurred, 0.6, 0)
        return frame

    def _bar_color(self, i: int, n: int, level: float) -> tuple[int, int, int]:
        """Pick a BGR color for bar ``i`` (left-to-right rainbow when enabled)."""
        cfg = self.cfg
        if cfg.rainbow:
            hue = int(180 * (i / max(1, n - 1)))   # OpenCV hue: 0..179
            sat = 220
            val = int(200 + 55 * level)
            hsv = np.uint8([[[hue, sat, min(255, val)]]])
            bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
            return int(bgr[0]), int(bgr[1]), int(bgr[2])
        # gradient_top RGB -> BGR
        r, g, b = cfg.gradient_top
        return int(b), int(g), int(r)

    # -- circular -------------------------------------------------------
    def _draw_circular(self, frame: np.ndarray, levels: np.ndarray,
                       beat: float, t: float) -> np.ndarray:
        cfg = self.cfg
        w, h = self.w, self.h
        cx, cy = w // 2, h // 2 + int(h * 0.05)
        radius = int(min(w, h) * 0.18 * (1 + 0.04 * beat))
        n = len(levels)
        if n == 0:
            return frame
        for i in range(n):
            level = float(levels[i])
            length = int(min(w, h) * 0.18 * level) + 4
            ang = 2 * math.pi * (i / n) - math.pi / 2 + t * 0.05
            x0 = int(cx + math.cos(ang) * radius)
            y0 = int(cy + math.sin(ang) * radius)
            x1 = int(cx + math.cos(ang) * (radius + length))
            y1 = int(cy + math.sin(ang) * (radius + length))
            color = self._bar_color(i, n, level)
            cv2.line(frame, (x0, y0), (x1, y1), color, thickness=4, lineType=cv2.LINE_AA)
        if cfg.glow:
            blurred = cv2.GaussianBlur(frame, (0, 0), 6)
            frame[:] = cv2.addWeighted(frame, 1.0, blurred, 0.25, 0)
        return frame

    # -- waveform -------------------------------------------------------
    def _draw_waveform(self, frame: np.ndarray, levels: np.ndarray, beat: float) -> np.ndarray:
        cfg = self.cfg
        w, h = self.w, self.h
        n = len(levels)
        if n < 2:
            return frame
        max_h = int(h * cfg.max_height_ratio * (1.0 + 0.12 * beat))
        center_y = int(h * 0.78)
        pts = []
        for i in range(n):
            x = int(w * (i / (n - 1)))
            y = int(center_y - max_h * float(levels[i]))
            pts.append((x, y))
        # Mirror below the centre.
        pts_below = [(x, 2 * center_y - y) for x, y in pts]
        # Smooth Catmull-Rom-ish via OpenCV polylines.
        arr_top = np.array(pts, dtype=np.int32)
        arr_bot = np.array(pts_below, dtype=np.int32)
        color = self._bar_color(n // 2, n, 1.0)
        cv2.polylines(frame, [arr_top], False, color, 3, cv2.LINE_AA)
        cv2.polylines(frame, [arr_bot], False, color, 3, cv2.LINE_AA)
        if cfg.glow:
            blurred = cv2.GaussianBlur(frame, (0, 0), 8)
            frame[:] = cv2.addWeighted(frame, 1.0, blurred, 0.35, 0)
        return frame


def _rounded_rect(img: np.ndarray, p0: tuple[int, int], p1: tuple[int, int],
                  color: tuple[int, int, int], radius: int = 6) -> None:
    """Filled rounded rectangle on ``img`` in-place."""
    x0, y0 = p0
    x1, y1 = p1
    if x1 <= x0 or y1 <= y0:
        return
    radius = max(0, min(radius, (x1 - x0) // 2, (y1 - y0) // 2))
    cv2.rectangle(img, (x0 + radius, y0), (x1 - radius, y1), color, thickness=-1)
    cv2.rectangle(img, (x0, y0 + radius), (x1, y1 - radius), color, thickness=-1)
    if radius > 0:
        cv2.circle(img, (x0 + radius, y0 + radius), radius, color, -1, cv2.LINE_AA)
        cv2.circle(img, (x1 - radius, y0 + radius), radius, color, -1, cv2.LINE_AA)
        cv2.circle(img, (x0 + radius, y1 - radius), radius, color, -1, cv2.LINE_AA)
        cv2.circle(img, (x1 - radius, y1 - radius), radius, color, -1, cv2.LINE_AA)


def _gradient_bar(img: np.ndarray, x0: int, y0: int, x1: int, y1: int,
                  top_bgr: tuple[int, int, int],
                  bot_rgb: tuple[int, int, int],
                  rounded: bool) -> None:
    """Draw a vertical-gradient bar with optional rounded top into ``img``."""
    if x1 <= x0 or y1 <= y0:
        return
    bot_bgr = (int(bot_rgb[2]), int(bot_rgb[1]), int(bot_rgb[0]))
    h = y1 - y0
    # Build a small column gradient and blit.
    grad = np.linspace(0.0, 1.0, h, dtype=np.float32)
    col = (np.array(top_bgr, dtype=np.float32)[None, :] * (1 - grad)[:, None]
           + np.array(bot_bgr, dtype=np.float32)[None, :] * grad[:, None])
    col = col.astype(np.uint8)
    bar = np.repeat(col[:, None, :], x1 - x0, axis=1)
    img[y0:y1, x0:x1] = bar
    if rounded:
        # Soft rounded top: paint a small dark wedge corner removed by
        # drawing an antialiased filled circle at the bar top centre.
        radius = max(2, (x1 - x0) // 2)
        cv2.circle(img, ((x0 + x1) // 2, y0 + radius - 1), radius,
                   (int(top_bgr[0]), int(top_bgr[1]), int(top_bgr[2])),
                   -1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# FFmpeg writer
# ---------------------------------------------------------------------------
class _FFmpegWriter:
    """Pipes raw BGR24 frames into FFmpeg, multiplexed with the audio file."""

    def __init__(self, ffmpeg: str, audio_path: str, output: str,
                 width: int, height: int, fps: int,
                 preset: str, crf: int, bitrate: Optional[str]) -> None:
        # We attach -shortest so the muxer stops with whichever of audio/video
        # ends first - this guarantees no extra silent video frames if the
        # video is one or two frames longer than the audio.
        cmd: list[str] = [
            ffmpeg, "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{width}x{height}",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "-",
            "-i", audio_path,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", preset,
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest",
        ]
        if bitrate:
            cmd += ["-b:v", bitrate]
        else:
            cmd += ["-crf", str(crf)]
        cmd += [output]

        log.info("FFmpeg: %s", " ".join(cmd))
        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=creation_flags,
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        """Pump ffmpeg's stderr to the log so we capture any errors."""
        if self.proc.stderr is None:
            return
        try:
            for line in iter(self.proc.stderr.readline, b""):
                if not line:
                    break
                txt = line.decode(errors="replace").rstrip()
                if txt:
                    log.debug("ffmpeg: %s", txt)
        except Exception:
            pass

    def write(self, frame_bgr: np.ndarray) -> None:
        if self.proc.stdin is None:
            raise RuntimeError("FFmpeg stdin is not available")
        try:
            self.proc.stdin.write(frame_bgr.tobytes())
        except BrokenPipeError as exc:
            raise RuntimeError(f"FFmpeg closed the pipe: {exc}") from exc

    def cancel(self) -> None:
        try:
            if self.proc.poll() is None:
                if os.name == "nt":
                    self.proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
                else:
                    self.proc.terminate()
                try:
                    self.proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except Exception as exc:
            log.warning("FFmpeg cancel error: %s", exc)

    def close(self) -> int:
        try:
            if self.proc.stdin is not None:
                self.proc.stdin.close()
        except Exception:
            pass
        return self.proc.wait()


# ---------------------------------------------------------------------------
# Public renderer
# ---------------------------------------------------------------------------
@dataclass
class RenderResult:
    output_path: str
    duration: float
    frames_written: int
    cancelled: bool = False
    error: Optional[str] = None


class VideoRenderer:
    """Stateless-ish helper. Create one per render."""

    def __init__(self, settings: ProjectSettings,
                 spectrum_data: Optional[audio_analyzer.SpectrumFrames] = None,
                 lyrics: Optional[LyricsTrack] = None) -> None:
        self.settings = settings
        self.spectrum_data = spectrum_data
        self.lyrics = lyrics or LyricsTrack(lines=[])
        self._cancel = threading.Event()
        self._writer: Optional[_FFmpegWriter] = None

    # ------------------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()
        if self._writer is not None:
            self._writer.cancel()

    # ------------------------------------------------------------------
    def render(self, output_path: str,
               *,
               progress: Optional[Callable[[int, int], None]] = None,
               status: Optional[Callable[[str], None]] = None,
               max_seconds: Optional[float] = None) -> RenderResult:
        s = self.settings
        if not s.audio_path:
            return RenderResult(output_path=output_path, duration=0, frames_written=0,
                                error="No audio file selected")
        ffmpeg = ffmpeg_manager.find_ffmpeg()
        if not ffmpeg:
            return RenderResult(output_path=output_path, duration=0, frames_written=0,
                                error="FFmpeg is not installed")

        # 1. Audio analysis (cached on caller side ideally).
        if status:
            status("Menganalisis spectrum audio...")
        if self.spectrum_data is None:
            self.spectrum_data = audio_analyzer.analyze(
                s.audio_path,
                fps=s.render.fps,
                bar_count=s.spectrum.bar_count,
                sensitivity=s.spectrum.sensitivity,
                bass_boost=s.spectrum.bass_boost,
                treble_boost=s.spectrum.treble_boost,
                smoothing=s.spectrum.smoothing,
            )
        sd = self.spectrum_data
        full_duration = sd.duration
        if max_seconds is not None:
            full_duration = min(full_duration, float(max_seconds))
        total_frames = int(math.floor(full_duration * sd.fps))
        if total_frames <= 0:
            return RenderResult(output_path=output_path, duration=0, frames_written=0,
                                error="Audio too short")

        if status:
            status(f"Memuat background ({s.background.kind.value})...")
        bg = _BackgroundReader(s, s.render.width, s.render.height, total_frames, s.render.fps)

        if status:
            status("Mempersiapkan logo & CTA...")
        logo = LogoOverlay(s.logo, s.render.width, s.render.height)
        cta = CTAOverlay(s.cta, s.render.width, s.render.height,
                         video_duration=full_duration, font_path=s.lyrics.font_path)

        if status:
            status(f"Mempersiapkan lirik ({s.lyrics.mode.value})...")
        karaoke: Optional[KaraokeOverlay] = None
        if s.lyrics.mode != LyricMode.NONE and self.lyrics:
            karaoke = KaraokeOverlay(s.lyrics, self.lyrics, s.render.width, s.render.height)

        spectrum = _SpectrumPainter(s, s.render.width, s.render.height)

        # 2. Prepare FFmpeg writer; for previews we trim by passing only N frames
        #    in (FFmpeg consumes audio until -shortest), so we explicitly pass
        #    -t to limit the audio side as well.
        audio_for_render = s.audio_path
        # When rendering a preview, ask ffmpeg to only consume the first N seconds.
        bitrate = s.render.bitrate
        crf = s.render.crf
        preset = s.render.ffmpeg_preset

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        if status:
            status("Memulai FFmpeg...")
        # We construct the writer manually so we can also tack on -t for preview.
        writer = _FFmpegWriter(
            ffmpeg=ffmpeg,
            audio_path=audio_for_render,
            output=output_path,
            width=s.render.width,
            height=s.render.height,
            fps=s.render.fps,
            preset=preset,
            crf=crf,
            bitrate=bitrate,
        )
        self._writer = writer

        # 3. Frame loop.
        cancelled = False
        frames_written = 0
        duration_total = total_frames / float(s.render.fps)
        try:
            for i in range(total_frames):
                if self._cancel.is_set():
                    cancelled = True
                    break
                t = i / float(s.render.fps)
                frame = bg.read(i)
                if frame.shape[0] != s.render.height or frame.shape[1] != s.render.width:
                    frame = cv2.resize(frame, (s.render.width, s.render.height))

                # Pull spectrum data with bounds-check.
                idx = min(i, sd.frames.shape[0] - 1)
                levels = sd.frames[idx]
                beat = float(sd.beat[idx])

                spectrum.draw(frame, levels, beat, t)
                if karaoke is not None:
                    karaoke.draw_on(frame, t)
                logo.draw_on(frame, t, duration_total)
                cta.draw_on(frame, t)

                writer.write(frame)
                frames_written += 1
                if progress and (i % 4 == 0 or i == total_frames - 1):
                    progress(i + 1, total_frames)
        except RuntimeError as exc:
            log.error("Render failed: %s", exc)
            writer.cancel()
            bg.close()
            self._writer = None
            return RenderResult(output_path=output_path, duration=duration_total,
                                frames_written=frames_written, error=str(exc))
        finally:
            bg.close()

        if cancelled:
            writer.cancel()
            self._writer = None
            # Best-effort cleanup of partial output.
            try:
                if os.path.exists(output_path):
                    os.remove(output_path)
            except Exception:
                pass
            return RenderResult(output_path=output_path, duration=duration_total,
                                frames_written=frames_written, cancelled=True)

        if status:
            status("Finalising MP4 (FFmpeg muxing)...")
        rc = writer.close()
        self._writer = None
        if rc != 0:
            return RenderResult(output_path=output_path, duration=duration_total,
                                frames_written=frames_written,
                                error=f"FFmpeg exited with code {rc}")
        return RenderResult(output_path=output_path, duration=duration_total,
                            frames_written=frames_written)
