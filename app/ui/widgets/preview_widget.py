"""Lightweight video preview widget.

The widget is purely a *frame display + transport controls*. The page that
hosts it is responsible for asking the renderer to produce frames; the
widget asks via the :pyattr:`request_frame` signal.

Frames are rendered at a small resolution so even slow laptops keep up.
Optional audio playback uses ``QMediaPlayer`` from ``QtMultimedia`` when
available; if it isn't, the preview becomes a silent slideshow.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # type: ignore
    _HAS_MEDIA = True
except ImportError:  # noqa: F401
    QAudioOutput = None  # type: ignore
    QMediaPlayer = None  # type: ignore
    _HAS_MEDIA = False


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    """Convert a PIL RGBA/RGB image to a Qt QPixmap."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


class PreviewWidget(QWidget):
    """Displays preview frames and exposes play/pause/seek controls."""

    request_frame = Signal(float)   # time in seconds
    play_state_changed = Signal(bool)
    time_changed = Signal(float)    # current play head time (s)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(420, 280)

        self.frame = QLabel(self)
        self.frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame.setStyleSheet("QLabel { background-color: #000; border-radius: 12px; }")
        self.frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.frame.setMinimumSize(360, 200)

        self.time_label = QLabel("00:00 / 00:00", self)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_play = QPushButton("Play")
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setProperty("role", "secondary")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setProperty("role", "secondary")
        self.btn_preview10 = QPushButton("Preview 10s")
        self.btn_preview10.setProperty("role", "secondary")

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 1000)
        self.slider.setSingleStep(1)

        controls = QHBoxLayout()
        controls.addWidget(self.btn_play)
        controls.addWidget(self.btn_pause)
        controls.addWidget(self.btn_stop)
        controls.addWidget(self.btn_preview10)
        controls.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.frame, 1)
        layout.addWidget(self.time_label)
        layout.addWidget(self.slider)
        layout.addLayout(controls)

        # State
        self._duration: float = 0.0
        self._current: float = 0.0
        self._playing: bool = False
        self._preview_fps: int = 18
        self._preview_end: Optional[float] = None
        self._media_path: Optional[str] = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

        if _HAS_MEDIA:
            self._media = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self._media.setAudioOutput(self._audio_out)
        else:
            self._media = None
            self._audio_out = None

        self.btn_play.clicked.connect(self.play)
        self.btn_pause.clicked.connect(self.pause)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_preview10.clicked.connect(self.preview_10s)
        self.slider.sliderMoved.connect(self._on_slider_moved)

    # ------------------------------------------------------------------
    def set_media(self, audio_path: Optional[str]) -> None:
        self._media_path = audio_path
        if self._media is not None and audio_path:
            self._media.setSource(QUrl.fromLocalFile(str(Path(audio_path).resolve())))

    def set_duration(self, seconds: float) -> None:
        self._duration = max(0.0, float(seconds))
        self.slider.setEnabled(self._duration > 0)
        self._update_time_label()

    def set_frame(self, img: Optional[Image.Image]) -> None:
        if img is None:
            self.frame.clear()
            return
        pm = pil_to_qpixmap(img)
        scaled = pm.scaled(
            self.frame.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.frame.setPixmap(scaled)

    def current_time(self) -> float:
        return self._current

    # ------------------------------------------------------------------
    def play(self) -> None:
        if self._duration <= 0:
            return
        self._playing = True
        self._preview_end = None
        self._timer.start(max(20, int(1000 / self._preview_fps)))
        if self._media is not None and self._media_path:
            self._media.setPosition(int(self._current * 1000))
            self._media.play()
        self.play_state_changed.emit(True)

    def pause(self) -> None:
        self._playing = False
        self._timer.stop()
        if self._media is not None:
            self._media.pause()
        self.play_state_changed.emit(False)

    def stop(self) -> None:
        self.pause()
        self.seek(0.0)

    def preview_10s(self) -> None:
        if self._duration <= 0:
            return
        self._preview_end = min(self._duration, self._current + 10.0)
        self.play()

    def seek(self, seconds: float) -> None:
        self._current = max(0.0, min(self._duration, float(seconds)))
        if self._duration > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(int(self._current / self._duration * 1000))
            self.slider.blockSignals(False)
        self._update_time_label()
        self.request_frame.emit(self._current)
        self.time_changed.emit(self._current)
        if self._media is not None and self._media_path:
            self._media.setPosition(int(self._current * 1000))

    # ------------------------------------------------------------------
    def _on_slider_moved(self, val: int) -> None:
        if self._duration <= 0:
            return
        target = val / 1000.0 * self._duration
        # Treat slider as a seek (pause-by-drag).
        self.pause()
        self.seek(target)

    def _on_tick(self) -> None:
        if not self._playing:
            return
        dt = 1.0 / max(1, self._preview_fps)
        new_t = self._current + dt
        if new_t >= self._duration:
            new_t = self._duration
            self.pause()
        if self._preview_end is not None and new_t >= self._preview_end:
            self.pause()
            new_t = self._preview_end
        self._current = new_t
        if self._duration > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(int(self._current / self._duration * 1000))
            self.slider.blockSignals(False)
        self._update_time_label()
        self.request_frame.emit(self._current)
        self.time_changed.emit(self._current)

    def _update_time_label(self) -> None:
        def fmt(s: float) -> str:
            s = max(0.0, s)
            m = int(s // 60)
            sec = int(s % 60)
            return f"{m:02d}:{sec:02d}"
        self.time_label.setText(f"{fmt(self._current)} / {fmt(self._duration)}")
