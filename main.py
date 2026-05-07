"""Entry point for the Music Spectrum Lyrics Visualizer GUI app."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure CWD is the project root so relative paths to assets/, output/, temp/ work.
ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

import logger_manager  # noqa: E402  (import order required: setup first)
logger_manager.setup_logging("temp")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui import MainWindow, apply_dark_theme  # noqa: E402


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Music Spectrum Lyrics Visualizer")
    app.setOrganizationName("basis16")
    apply_dark_theme(app)

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
