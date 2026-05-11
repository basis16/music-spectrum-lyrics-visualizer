"""Settings page (FFmpeg, theme, low-spec mode, etc)."""
from __future__ import annotations

import threading
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.ffmpeg_manager import FFmpegManager, get_default_manager
from app.core.settings_manager import AppSettings, SettingsManager
from app.ui.widgets._common import PathPicker
from app.utils.logger import get_logger

log = get_logger("ui.settings")


class SettingsPage(QWidget):
    """Application-wide settings (FFmpeg, theme, performance)."""

    settings_changed = Signal()

    def __init__(self, settings: SettingsManager,
                  parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = settings
        self.ffmpeg: FFmpegManager = get_default_manager()
        self.ffmpeg.set_custom_path(settings.settings.ffmpeg_path)

        # --- FFmpeg ---
        self.ffmpeg_path = PathPicker(
            dialog="file", filter="FFmpeg (ffmpeg* *)", caption="Pick ffmpeg(.exe)",
        )
        self.ffmpeg_status = QLabel("Checking FFmpeg...")
        self.ffmpeg_status.setWordWrap(True)
        self.ffmpeg_status.setStyleSheet("QLabel { color: #4a5468; }")

        self.btn_recheck = QPushButton("Recheck FFmpeg")
        self.btn_recheck.setProperty("role", "secondary")
        self.btn_install = QPushButton("Install FFmpeg Online")
        self.btn_install.setToolTip(
            "Downloads the latest release from gyan.dev and stores it in "
            "app/assets/ffmpeg/."
        )

        self.install_progress = QProgressBar()
        self.install_progress.setRange(0, 100)
        self.install_progress.setValue(0)
        self.install_progress.setVisible(False)

        ffm_form = QFormLayout()
        ffm_form.addRow("FFmpeg path", self.ffmpeg_path)
        ffm_form.addRow("", self.ffmpeg_status)
        ffm_btn = QHBoxLayout()
        ffm_btn.addWidget(self.btn_recheck)
        ffm_btn.addWidget(self.btn_install)
        ffm_btn.addStretch(1)
        ffm_box = QVBoxLayout()
        ffm_box.addLayout(ffm_form)
        ffm_box.addLayout(ffm_btn)
        ffm_box.addWidget(self.install_progress)
        ffm_card = QGroupBox("FFmpeg")
        ffm_card.setLayout(ffm_box)

        # --- Theme + low spec ---
        self.theme = QComboBox()
        self.theme.addItems(["auto", "light", "dark"])

        self.low_spec = QCheckBox("Low-Spec Mode")
        self.low_spec.setToolTip(
            "Lighter preview, no glow, FFmpeg veryfast preset."
        )

        self.output_folder = PathPicker(
            dialog="folder", caption="Pick output folder",
        )
        self.encoder = QComboBox()
        self.encoder.addItems(["auto", "nvenc", "qsv", "amf", "cpu"])

        gen_form = QFormLayout()
        gen_form.addRow("Theme", self.theme)
        gen_form.addRow("Default output", self.output_folder)
        gen_form.addRow("Encoder", self.encoder)
        gen_form.addRow("", self.low_spec)
        gen_card = QGroupBox("Application")
        gen_card.setLayout(gen_form)

        # --- Encoder availability info ---
        self.hw_info = QLabel("Hardware acceleration: (run recheck)")
        self.hw_info.setWordWrap(True)
        hw_card = QGroupBox("Hardware acceleration")
        hwl = QVBoxLayout(); hwl.addWidget(self.hw_info)
        hw_card.setLayout(hwl)

        self.btn_save = QPushButton("Save settings")
        self.btn_reset = QPushButton("Reset to defaults")
        self.btn_reset.setProperty("role", "secondary")
        actions = QHBoxLayout()
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_reset)
        actions.addStretch(1)

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.addWidget(ffm_card)
        root.addWidget(gen_card)
        root.addWidget(hw_card)
        root.addLayout(actions)
        root.addStretch(1)

        # Wire
        self.btn_recheck.clicked.connect(self._recheck_ffmpeg)
        self.btn_install.clicked.connect(self._install_ffmpeg)
        self.btn_save.clicked.connect(self._save)
        self.btn_reset.clicked.connect(self._reset)
        self.ffmpeg_path.edit.textChanged.connect(self._on_path_changed)

        self.load_settings()
        self._recheck_ffmpeg()

    # ------------------------------------------------------------------
    def load_settings(self) -> None:
        s = self.settings.settings
        self.ffmpeg_path.set_value(s.ffmpeg_path or "")
        self.theme.setCurrentText(s.theme)
        self.encoder.setCurrentText(s.encoder_preference)
        self.low_spec.setChecked(s.low_spec_mode)
        self.output_folder.set_value(s.output_folder)

    def save_to_settings(self) -> AppSettings:
        s = self.settings.settings
        s.ffmpeg_path = self.ffmpeg_path.value() or None
        s.theme = self.theme.currentText()
        s.encoder_preference = self.encoder.currentText()
        s.low_spec_mode = self.low_spec.isChecked()
        if self.output_folder.value():
            s.output_folder = self.output_folder.value()
        self.settings.save()
        self.settings_changed.emit()
        return s

    # ------------------------------------------------------------------
    def _on_path_changed(self, text: str) -> None:
        self.ffmpeg.set_custom_path(text or None)

    def _recheck_ffmpeg(self) -> None:
        info = self.ffmpeg.detect(force=True)
        if info.available:
            self.ffmpeg_status.setText(
                f"<b>FFmpeg detected:</b> {info.ffmpeg_path}<br>"
                f"<span style='color:#4a5468'>{info.version or ''}</span>"
            )
            if info.hwaccels:
                self.hw_info.setText(
                    "Available encoders: " + ", ".join(info.hwaccels) +
                    " (auto-picked by Encoder = auto)"
                )
            else:
                self.hw_info.setText(
                    "No hardware encoders detected. Render will use the CPU (libx264)."
                )
        else:
            self.ffmpeg_status.setText(
                "<b style='color:#c83232'>FFmpeg not detected.</b> "
                "Use 'Install FFmpeg Online' or set a custom path above."
            )
            self.hw_info.setText("FFmpeg is required to probe hardware encoders.")

    def _install_ffmpeg(self) -> None:
        if hasattr(self, "_install_thread") and getattr(self, "_install_thread").is_alive():
            return
        self.install_progress.setVisible(True)
        self.install_progress.setValue(0)
        self.btn_install.setEnabled(False)

        def progress(downloaded: int, total: int) -> None:
            if total and total > 0:
                pct = int(min(100, downloaded * 100 / total))
            else:
                pct = min(95, downloaded // 100_000)
            try:
                self.install_progress.setValue(pct)
            except RuntimeError:
                pass

        def status(msg: str) -> None:
            self.ffmpeg_status.setText(msg)
            log.info("FFmpeg install: %s", msg)

        def runner():
            try:
                info = self.ffmpeg.install_online(on_progress=progress, on_status=status)
            except Exception as e:  # noqa: BLE001
                status(f"Install failed: {e}")
                info = None
            try:
                self.btn_install.setEnabled(True)
                self.install_progress.setVisible(False)
            except RuntimeError:
                pass
            if info and info.available:
                self._recheck_ffmpeg()

        t = threading.Thread(target=runner, daemon=True, name="ffmpeg-install")
        self._install_thread = t
        t.start()

    def _save(self) -> None:
        self.save_to_settings()
        QMessageBox.information(self, "Saved", "Settings saved.")

    def _reset(self) -> None:
        ok = QMessageBox.question(
            self, "Reset settings?",
            "Reset all settings to their defaults?",
        )
        if ok == QMessageBox.StandardButton.Yes:
            self.settings.reset()
            self.load_settings()
            self.settings_changed.emit()
