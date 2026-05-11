"""Application log panel widget."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.utils.logger import CallbackHandler, get_logger, save_log_to_file


class LogPanel(QWidget):
    """A read-only text view that mirrors the application logger."""

    log_emitted = Signal(str, str)  # level, message  (thread-safe bridge)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.view = QPlainTextEdit(self)
        self.view.setObjectName("LogPanel")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setProperty("role", "secondary")
        self.btn_clear.clicked.connect(self.view.clear)

        self.btn_save = QPushButton("Save log...")
        self.btn_save.setProperty("role", "secondary")
        self.btn_save.clicked.connect(self._on_save)

        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_clear)
        toolbar.addWidget(self.btn_save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view, 1)
        layout.addLayout(toolbar)

        # Bridge from logging thread to Qt thread via signal.
        self.log_emitted.connect(self._append, Qt.ConnectionType.QueuedConnection)
        self._handler = CallbackHandler(self._on_log, level=logging.INFO)
        get_logger().addHandler(self._handler)

        self._append("INFO", f"Log started at {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # ------------------------------------------------------------------
    def _on_log(self, level: str, msg: str) -> None:
        # Called from logging threads — forward to UI thread.
        try:
            self.log_emitted.emit(level, msg)
        except RuntimeError:
            # Widget destroyed.
            pass

    def _append(self, level: str, msg: str) -> None:
        self.view.appendPlainText(msg)
        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.view.setTextCursor(cursor)

    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save log", str(Path.home() / "music-spectrum-log.txt"),
            "Text files (*.txt)",
        )
        if path:
            save_log_to_file(path)
