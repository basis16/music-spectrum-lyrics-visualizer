"""Single-file render page."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from PIL import Image
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.core.ffmpeg_manager import FFmpegManager, get_default_manager
from app.core.lyrics_extractor import extract_basic_metadata, extract_lyrics
from app.core.renderer import (
    LogoOptions,
    LyricOptions,
    RenderConfig,
    Renderer,
    default_output_path,
)
from app.core.settings_manager import (
    AppSettings,
    SettingsManager,
    quality_preset,
    resolve_resolution,
)
from app.core.spectrum_styles import SpectrumStyleOptions
from app.ui.widgets._common import PathPicker, hex_to_rgba
from app.ui.widgets.config_groups import (
    LogoConfigGroup,
    LyricsConfigGroup,
    OutputConfigGroup,
    SpectrumConfigGroup,
)
from app.ui.widgets.preview_widget import PreviewWidget
from app.ui.widgets.render_worker import SingleRenderController
from app.utils.logger import get_logger

log = get_logger("ui.single")


class SingleRenderPage(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: SettingsManager,
                  renderer: Optional[Renderer] = None,
                  parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = settings
        self.ffmpeg: FFmpegManager = get_default_manager()
        self.ffmpeg.set_custom_path(settings.settings.ffmpeg_path)
        self.renderer = renderer or Renderer(self.ffmpeg)
        self.controller = SingleRenderController(self.renderer, self)
        self.controller.progress.connect(self._on_progress)
        self.controller.finished.connect(self._on_finished)

        # --- File pickers ----
        self.audio_picker = PathPicker(
            dialog="file",
            filter="Audio (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus)",
            caption="Pick an audio file",
        )
        self.background_picker = PathPicker(
            dialog="file",
            filter=("Backgrounds (*.jpg *.jpeg *.png *.webp *.bmp "
                     "*.mp4 *.mov *.mkv *.webm)"),
            caption="Pick a background",
        )
        self.output_picker = PathPicker(
            dialog="save",
            filter="MP4 video (*.mp4)",
            caption="Pick output file",
        )

        files_form = QFormLayout()
        files_form.addRow("Audio file", self.audio_picker)
        files_form.addRow("Background", self.background_picker)
        files_form.addRow("Output file", self.output_picker)
        files_card = QGroupBox("Files")
        files_card.setLayout(files_form)

        self.meta_label = QLabel("No audio selected.")
        self.meta_label.setWordWrap(True)
        self.meta_label.setProperty("role", "muted")

        meta_layout = QVBoxLayout()
        meta_layout.addWidget(self.meta_label)
        meta_card = QGroupBox("Audio info")
        meta_card.setLayout(meta_layout)

        # --- Config groups ---
        self.spectrum_group = SpectrumConfigGroup()
        self.logo_group = LogoConfigGroup()
        self.lyric_group = LyricsConfigGroup()
        self.output_group = OutputConfigGroup()

        config_col = QVBoxLayout()
        config_col.addWidget(files_card)
        config_col.addWidget(meta_card)
        config_col.addWidget(self.spectrum_group)
        config_col.addWidget(self.logo_group)
        config_col.addWidget(self.lyric_group)
        config_col.addWidget(self.output_group)
        config_col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget(); inner.setLayout(config_col)
        scroll.setWidget(inner)

        # --- Preview side ---
        self.preview = PreviewWidget()
        self.preview.request_frame.connect(self._render_preview_at)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.status = QLabel("Ready.")
        self.status.setProperty("role", "muted")

        self.btn_render = QPushButton("Render")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setProperty("role", "danger")
        self.btn_cancel.setEnabled(False)

        actions = QHBoxLayout()
        actions.addWidget(self.btn_render)
        actions.addWidget(self.btn_cancel)
        actions.addStretch(1)

        right_col = QVBoxLayout()
        right_col.addWidget(self.preview, 1)
        right_col.addWidget(self.progress)
        right_col.addWidget(self.status)
        right_col.addLayout(actions)
        right_widget = QWidget(); right_widget.setLayout(right_col)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(scroll)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 700])

        root = QVBoxLayout(self)
        root.addWidget(splitter, 1)

        # Wire signals
        self.audio_picker.edit.textChanged.connect(self._on_audio_changed)
        for g in (self.spectrum_group, self.logo_group, self.lyric_group,
                    self.output_group):
            g.changed.connect(self._refresh_preview)
        self.background_picker.edit.textChanged.connect(self._refresh_preview)
        self.btn_render.clicked.connect(self._on_render)
        self.btn_cancel.clicked.connect(self._on_cancel)

        # Debounce preview rendering so dragging sliders isn't choppy.
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._render_preview_now)

        self.load_settings()

    # ------------------------------------------------------------------
    def load_settings(self) -> None:
        s = self.settings.settings
        self.spectrum_group.load(s)
        self.logo_group.load(s)
        self.lyric_group.load(s)
        self.output_group.load(s)
        if s.last_audio:
            self.audio_picker.set_value(s.last_audio)
        if s.last_background:
            self.background_picker.set_value(s.last_background)

    def save_settings(self) -> AppSettings:
        s = self.settings.settings
        self.spectrum_group.save(s)
        self.logo_group.save(s)
        self.lyric_group.save(s)
        self.output_group.save(s)
        s.last_audio = self.audio_picker.value() or None
        s.last_background = self.background_picker.value() or None
        self.settings.save()
        self.settings_changed.emit()
        return s

    # ------------------------------------------------------------------
    def _on_audio_changed(self, _text: str) -> None:
        audio = self.audio_picker.value()
        if audio:
            # Suggest an output filename automatically.
            if not self.output_picker.value():
                out = default_output_path(
                    audio, self.settings.settings.output_folder)
                self.output_picker.set_value(str(out))
            self._update_meta_label(audio)
            duration = self._probe_duration(audio)
            self.preview.set_media(audio)
            self.preview.set_duration(duration or 0.0)
            self._refresh_preview()
        else:
            self.meta_label.setText("No audio selected.")
            self.preview.set_duration(0)

    def _probe_duration(self, audio: str) -> Optional[float]:
        # Try mutagen first (cheap), fall back to ffprobe.
        meta = extract_basic_metadata(audio)
        if meta.get("duration"):
            return float(meta["duration"])
        return self.ffmpeg.ffprobe_duration(audio)

    def _update_meta_label(self, audio: str) -> None:
        meta = extract_basic_metadata(audio)
        lyrics = extract_lyrics(audio)
        bits = []
        if meta.get("title"):
            bits.append(f"<b>{meta['title']}</b>")
        if meta.get("artist"):
            bits.append(meta["artist"])
        if meta.get("album"):
            bits.append(f"<i>{meta['album']}</i>")
        if meta.get("duration"):
            d = float(meta["duration"])
            bits.append(f"{int(d // 60):02d}:{int(d % 60):02d}")
        if lyrics.has_synced:
            bits.append(f"{len(lyrics.synced)} synced lyric lines ({lyrics.source})")
        elif lyrics.unsynced:
            bits.append(f"{len(lyrics.unsynced)} unsynced lines (no timestamps)")
        else:
            bits.append("no lyrics detected")
        text = "<br>".join(bits) if bits else f"Selected: {Path(audio).name}"
        self.meta_label.setText(text)

    # ------------------------------------------------------------------
    def _build_config(self, for_preview: bool) -> Optional[RenderConfig]:
        audio = self.audio_picker.value()
        if not audio or not Path(audio).exists():
            return None
        s = self.settings.settings
        # Use current widget values without persisting.
        self.spectrum_group.save(s)
        self.logo_group.save(s)
        self.lyric_group.save(s)
        self.output_group.save(s)

        width, height = resolve_resolution(s.resolution, s.custom_resolution)
        if for_preview:
            # Cap preview at 720p to stay snappy on weak hardware.
            scale = min(1.0, 720 / float(max(1, height)))
            width = int(width * scale)
            height = int(height * scale)

        qp = quality_preset(s.quality)
        encoder = self.ffmpeg.encoder_for(s.encoder_preference)

        spec_opts = SpectrumStyleOptions(
            style=s.spectrum_style,
            color=hex_to_rgba(s.spectrum_color),
            gradient=s.spectrum_gradient,
            gradient_color=hex_to_rgba(s.spectrum_color2),
            glow=s.spectrum_glow,
            glow_strength=s.spectrum_glow_strength,
            smoothness=s.spectrum_smoothness,
            sensitivity=s.spectrum_sensitivity,
            bar_count=s.spectrum_bar_count,
            position=s.spectrum_position,
        )
        logo_opts = LogoOptions(
            path=s.logo_path,
            circle=s.logo_circle,
            size_ratio=s.logo_size,
            position=s.logo_position,
            opacity=s.logo_opacity,
            shadow=s.logo_shadow,
            border=s.logo_border,
            glow=s.logo_glow,
        )
        lyric_opts = LyricOptions(
            font_family=s.lyric_font_family,
            font_size=s.lyric_font_size,
            bold=s.lyric_bold,
            italic=s.lyric_italic,
            color=hex_to_rgba(s.lyric_color),
            stroke=s.lyric_stroke,
            stroke_color=hex_to_rgba(s.lyric_stroke_color),
            stroke_width=s.lyric_stroke_width,
            shadow=s.lyric_shadow,
            position=s.lyric_position,
            align=s.lyric_align,
            max_lines=s.lyric_max_lines,
            animation=s.lyric_animation,
            preset=s.lyric_preset,
        )
        output_path = self.output_picker.value() or str(
            default_output_path(audio, s.output_folder)
        )
        return RenderConfig(
            audio_path=audio,
            output_path=output_path,
            background_path=self.background_picker.value() or None,
            background_fit=s.background_fit,
            width=width, height=height,
            fps=s.fps,
            encoder=encoder,
            quality_preset=qp["preset"],
            crf=qp["crf"],
            bitrate=qp["bitrate"],
            low_spec=s.low_spec_mode,
            spectrum=spec_opts,
            logo=logo_opts,
            lyrics=lyric_opts,
        )

    # ------------------------------------------------------------------
    def _refresh_preview(self) -> None:
        # Debounce
        self._preview_timer.start(120)

    def _render_preview_now(self) -> None:
        self._render_preview_at(self.preview.current_time())

    def _render_preview_at(self, t: float) -> None:
        cfg = self._build_config(for_preview=True)
        if cfg is None:
            self.preview.set_frame(None)
            return
        try:
            scale = 0.5 if not cfg.low_spec else 0.35
            img = self.renderer.render_preview_frame(cfg, t, preview_scale=scale)
            self.preview.set_frame(img)
        except Exception as e:  # noqa: BLE001
            log.debug("Preview render failed: %s", e)

    # ------------------------------------------------------------------
    def _on_render(self) -> None:
        cfg = self._build_config(for_preview=False)
        if cfg is None:
            QMessageBox.warning(self, "Missing audio",
                                  "Pick an audio file first.")
            return
        info = self.ffmpeg.detect(force=True)
        if not info.available:
            QMessageBox.warning(
                self, "FFmpeg missing",
                "FFmpeg is not detected. Open Settings and install or set a path.",
            )
            return
        # Persist the user's choices before kicking off.
        self.save_settings()
        self.btn_render.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.status.setText(f"Rendering {Path(cfg.audio_path).name}...")
        self.controller.start(cfg)

    def _on_cancel(self) -> None:
        self.controller.cancel()
        self.status.setText("Cancelling...")

    def _on_progress(self, pct: float, msg: str) -> None:
        self.progress.setValue(int(pct * 1000))
        self.status.setText(msg)

    def _on_finished(self, ok: bool, msg: str) -> None:
        self.btn_render.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setValue(1000 if ok else 0)
        if ok:
            self.status.setText(f"Done — {msg}")
            log.info("Render OK: %s", msg)
        else:
            self.status.setText(f"Failed — {msg}")
            QMessageBox.critical(self, "Render failed", msg)
