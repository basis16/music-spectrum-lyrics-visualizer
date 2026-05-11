"""Batch render page (folder in, folder out)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.batch_manager import BatchItem, BatchOptions, ItemStatus
from app.core.ffmpeg_manager import FFmpegManager, get_default_manager
from app.core.renderer import (
    LogoOptions,
    LyricOptions,
    RenderConfig,
    Renderer,
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
from app.ui.widgets.render_worker import BatchRenderController
from app.utils.logger import get_logger

log = get_logger("ui.batch")


_STATUS_COLOR = {
    ItemStatus.PENDING: "#4a5468",
    ItemStatus.RUNNING: "#2a55ff",
    ItemStatus.DONE: "#1d8a3a",
    ItemStatus.FAILED: "#c83232",
    ItemStatus.SKIPPED: "#a06400",
}


class BatchRenderPage(QWidget):
    settings_changed = Signal()

    def __init__(self, settings: SettingsManager,
                  renderer: Optional[Renderer] = None,
                  parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = settings
        self.ffmpeg: FFmpegManager = get_default_manager()
        self.ffmpeg.set_custom_path(settings.settings.ffmpeg_path)
        self.renderer = renderer or Renderer(self.ffmpeg)
        self.controller = BatchRenderController(self.renderer, self)
        self.controller.item_changed.connect(self._on_item_changed)
        self.controller.item_progress.connect(self._on_item_progress)
        self.controller.finished.connect(self._on_finished)

        self.audio_folder = PathPicker(dialog="folder", caption="Pick music folder")
        self.bg_folder = PathPicker(dialog="folder", caption="Pick background folder")
        self.output_folder = PathPicker(dialog="folder", caption="Pick output folder")

        self.bg_mode = QComboBox()
        self.bg_mode.addItems(["sequence", "match", "random"])

        files_form = QFormLayout()
        files_form.addRow("Music folder", self.audio_folder)
        files_form.addRow("Background folder", self.bg_folder)
        files_form.addRow("Background mode", self.bg_mode)
        files_form.addRow("Output folder", self.output_folder)
        files_card = QGroupBox("Folders")
        files_card.setLayout(files_form)

        # Reuse the same config groups as Single Render so defaults stay consistent.
        self.spectrum_group = SpectrumConfigGroup()
        self.logo_group = LogoConfigGroup()
        self.lyric_group = LyricsConfigGroup()
        self.output_group = OutputConfigGroup()

        left = QVBoxLayout()
        left.addWidget(files_card)
        left.addWidget(self.spectrum_group)
        left.addWidget(self.logo_group)
        left.addWidget(self.lyric_group)
        left.addWidget(self.output_group)
        left.addStretch(1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        inner = QWidget(); inner.setLayout(left)
        left_scroll.setWidget(inner)

        # Right side: queue
        self.queue = QTableWidget(0, 4)
        self.queue.setHorizontalHeaderLabels(["Song", "Background", "Status", "Message"])
        self.queue.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.queue.verticalHeader().setVisible(False)
        self.queue.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.status_label = QPushButton("Idle")
        self.status_label.setEnabled(False)
        self.status_label.setProperty("role", "secondary")

        self.btn_preview = QPushButton("Refresh Queue")
        self.btn_preview.setProperty("role", "secondary")
        self.btn_start = QPushButton("Start Batch")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setProperty("role", "danger")
        self.btn_cancel.setEnabled(False)

        actions = QHBoxLayout()
        actions.addWidget(self.btn_preview)
        actions.addWidget(self.btn_start)
        actions.addWidget(self.btn_cancel)
        actions.addStretch(1)
        actions.addWidget(self.status_label)

        right_col = QVBoxLayout()
        right_col.addWidget(self.queue, 1)
        right_col.addWidget(self.progress)
        right_col.addLayout(actions)
        right_w = QWidget(); right_w.setLayout(right_col)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_scroll)
        splitter.addWidget(right_w)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([520, 720])

        root = QVBoxLayout(self)
        root.addWidget(splitter, 1)

        self.btn_preview.clicked.connect(self._refresh_queue)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_cancel.clicked.connect(self._on_cancel)
        for picker in (self.audio_folder, self.bg_folder, self.output_folder):
            picker.edit.textChanged.connect(self._refresh_queue)
        self.bg_mode.currentIndexChanged.connect(self._refresh_queue)

        self._items: List[BatchItem] = []

        self.load_settings()

    # ------------------------------------------------------------------
    def load_settings(self) -> None:
        s = self.settings.settings
        self.spectrum_group.load(s)
        self.logo_group.load(s)
        self.lyric_group.load(s)
        self.output_group.load(s)
        if s.last_audio_folder:
            self.audio_folder.set_value(s.last_audio_folder)
        if s.last_background_folder:
            self.bg_folder.set_value(s.last_background_folder)
        self.output_folder.set_value(s.last_output_folder or s.output_folder)
        self.bg_mode.setCurrentText(s.background_mode)

    def save_settings(self) -> AppSettings:
        s = self.settings.settings
        self.spectrum_group.save(s)
        self.logo_group.save(s)
        self.lyric_group.save(s)
        self.output_group.save(s)
        s.last_audio_folder = self.audio_folder.value() or None
        s.last_background_folder = self.bg_folder.value() or None
        s.last_output_folder = self.output_folder.value() or s.output_folder
        s.background_mode = self.bg_mode.currentText()
        self.settings.save()
        self.settings_changed.emit()
        return s

    # ------------------------------------------------------------------
    def _build_base_config(self) -> Optional[RenderConfig]:
        s = self.settings.settings
        self.spectrum_group.save(s)
        self.logo_group.save(s)
        self.lyric_group.save(s)
        self.output_group.save(s)

        width, height = resolve_resolution(s.resolution, s.custom_resolution)
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
            path=s.logo_path, circle=s.logo_circle, size_ratio=s.logo_size,
            position=s.logo_position, opacity=s.logo_opacity,
            shadow=s.logo_shadow, border=s.logo_border, glow=s.logo_glow,
        )
        lyric_opts = LyricOptions(
            font_family=s.lyric_font_family, font_size=s.lyric_font_size,
            bold=s.lyric_bold, italic=s.lyric_italic,
            color=hex_to_rgba(s.lyric_color), stroke=s.lyric_stroke,
            stroke_color=hex_to_rgba(s.lyric_stroke_color),
            stroke_width=s.lyric_stroke_width, shadow=s.lyric_shadow,
            position=s.lyric_position, align=s.lyric_align,
            max_lines=s.lyric_max_lines, animation=s.lyric_animation,
            preset=s.lyric_preset,
        )
        return RenderConfig(
            audio_path="",  # filled per-item
            output_path="",
            background_path=None,
            background_fit=s.background_fit,
            width=width, height=height, fps=s.fps,
            encoder=encoder, quality_preset=qp["preset"],
            crf=qp["crf"], bitrate=qp["bitrate"],
            low_spec=s.low_spec_mode,
            spectrum=spec_opts, logo=logo_opts, lyrics=lyric_opts,
        )

    def _build_options(self) -> Optional[BatchOptions]:
        af = self.audio_folder.value()
        out = self.output_folder.value()
        if not af or not Path(af).is_dir():
            return None
        if not out:
            return None
        return BatchOptions(
            audio_folder=af,
            output_folder=out,
            background_folder=self.bg_folder.value() or None,
            background_mode=self.bg_mode.currentText(),
            recursive=True,
        )

    # ------------------------------------------------------------------
    def _refresh_queue(self) -> None:
        opts = self._build_options()
        cfg = self._build_base_config()
        if opts is None or cfg is None:
            self.queue.setRowCount(0)
            self._items = []
            return
        items = self.controller.preview_items(cfg, opts)
        self._items = items
        self.queue.setRowCount(len(items))
        for i, item in enumerate(items):
            self._render_row(i, item)

    def _render_row(self, idx: int, item: BatchItem) -> None:
        for col, value in enumerate([
            item.audio_path.name,
            item.background_path.name if item.background_path else "(none)",
            item.status.value,
            item.message or "",
        ]):
            qi = QTableWidgetItem(str(value))
            if col == 2:
                qi.setForeground(Qt.GlobalColor.darkBlue)
                color = _STATUS_COLOR.get(item.status, "#4a5468")
                qi.setToolTip(color)
            self.queue.setItem(idx, col, qi)

    # ------------------------------------------------------------------
    def _on_start(self) -> None:
        opts = self._build_options()
        if opts is None:
            QMessageBox.warning(
                self, "Missing folders",
                "Please pick an audio folder and an output folder.",
            )
            return
        cfg = self._build_base_config()
        if cfg is None:
            return
        info = self.ffmpeg.detect(force=True)
        if not info.available:
            QMessageBox.warning(
                self, "FFmpeg missing",
                "FFmpeg is not detected. Open Settings to install it.",
            )
            return
        items = self.controller.preview_items(cfg, opts)
        if not items:
            QMessageBox.information(
                self, "Nothing to render",
                "No audio files found in the chosen folder.",
            )
            return
        self.save_settings()
        self._items = items
        self.queue.setRowCount(len(items))
        for i, item in enumerate(items):
            self._render_row(i, item)
        self.controller.start(cfg, opts, items)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.status_label.setText(f"Rendering {len(items)} files...")

    def _on_cancel(self) -> None:
        self.controller.cancel()
        self.status_label.setText("Cancelling batch...")

    def _on_item_changed(self, idx: int, item: BatchItem) -> None:
        if idx >= self.queue.rowCount():
            return
        self._render_row(idx, item)

    def _on_item_progress(self, idx: int, pct: float, msg: str) -> None:
        total = max(1, len(self._items))
        overall = (idx + pct) / total
        self.progress.setValue(int(overall * 1000))
        self.status_label.setText(f"{idx + 1}/{total}: {msg}")

    def _on_finished(self, result) -> None:
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.progress.setValue(1000)
        self.status_label.setText(
            f"Batch done. {result.succeeded} ok / {result.failed} failed."
        )
        log.info("Batch finished: %s ok / %s failed",
                  result.succeeded, result.failed)
