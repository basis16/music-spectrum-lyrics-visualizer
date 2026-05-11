"""Main application window: sidebar + stacked pages + log dock."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from app.core.ffmpeg_manager import FFmpegManager, get_default_manager
from app.core.renderer import Renderer
from app.core.settings_manager import SettingsManager, get_settings_manager
from app.ui.themes import load_qss
from app.ui.widgets.batch_render_page import BatchRenderPage
from app.ui.widgets.log_panel import LogPanel
from app.ui.widgets.settings_page import SettingsPage
from app.ui.widgets.single_render_page import SingleRenderPage
from app.utils.logger import get_logger

log = get_logger("ui.main")

PAGE_LABELS = ["Single Render", "Batch Render", "Settings", "Logs"]


class MainWindow(QMainWindow):
    def __init__(self, settings: Optional[SettingsManager] = None):
        super().__init__()
        self.setWindowTitle("Music Spectrum Lyric Video Maker")
        self.setMinimumSize(1200, 760)

        self.settings: SettingsManager = settings or get_settings_manager()
        self.ffmpeg: FFmpegManager = get_default_manager()
        self.ffmpeg.set_custom_path(self.settings.settings.ffmpeg_path)
        self.renderer = Renderer(self.ffmpeg)

        # Sidebar
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(220)
        self.sidebar.setIconSize(QSize(20, 20))
        for label in PAGE_LABELS:
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(0, 44))
            self.sidebar.addItem(item)
        self.sidebar.currentRowChanged.connect(self._on_nav)

        # Pages
        self.stack = QStackedWidget()
        self.single_page = SingleRenderPage(self.settings, self.renderer)
        self.batch_page = BatchRenderPage(self.settings, self.renderer)
        self.settings_page = SettingsPage(self.settings)

        # Log panel (also used as a dock + a top-level page).
        self.log_panel = LogPanel()
        self.log_dock = QDockWidget("Logs", self)
        self.log_dock.setObjectName("LogDock")
        self.log_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea
                                       | Qt.DockWidgetArea.TopDockWidgetArea)
        # Use a separate LogPanel instance for the dock so closing one
        # doesn't kill the other; we wire them up to share the same logger.
        self.dock_log_panel = LogPanel()
        self.log_dock.setWidget(self.dock_log_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.setFloating(False)
        self.log_dock.setMinimumHeight(140)

        self.stack.addWidget(self.single_page)
        self.stack.addWidget(self.batch_page)
        self.stack.addWidget(self.settings_page)
        self.stack.addWidget(self.log_panel)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self.sidebar)
        body_layout.addWidget(self.stack, 1)
        self.setCentralWidget(body)

        # Status bar
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Ready.")

        # Apply theme.
        self.apply_theme()
        self.settings_page.settings_changed.connect(self.apply_theme)
        self.single_page.settings_changed.connect(self.apply_theme)
        self.batch_page.settings_changed.connect(self.apply_theme)

        # FFmpeg status check
        info = self.ffmpeg.detect()
        if info.available:
            self.statusBar().showMessage(f"FFmpeg: {info.version or info.ffmpeg_path}")
        else:
            self.statusBar().showMessage(
                "FFmpeg not detected — open Settings to install or set a path."
            )

        self.sidebar.setCurrentRow(0)

    # ------------------------------------------------------------------
    def apply_theme(self) -> None:
        theme = self.settings.settings.theme or "auto"
        qss = load_qss(theme)
        QGuiApplication.instance().setStyleSheet(qss)

    def _on_nav(self, idx: int) -> None:
        if 0 <= idx < self.stack.count():
            self.stack.setCurrentIndex(idx)
