"""Application entrypoint.

Run via ``run.bat`` on Windows, or directly with ``python -m app.main``.
"""
from __future__ import annotations

import os
import sys
import traceback

from app.utils.logger import get_logger

log = get_logger("app")


def _excepthook(exc_type, exc, tb) -> None:
    """Last-resort excepthook so crashes are written to the log file."""
    log.error("Unhandled exception:\n%s",
              "".join(traceback.format_exception(exc_type, exc, tb)))


def main() -> int:
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow

    sys.excepthook = _excepthook
    log.info("Starting Music Spectrum Lyric Video Maker")

    # High-DPI handling.
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

    app = QApplication(sys.argv)
    app.setApplicationName("Music Spectrum Lyric Video Maker")
    app.setOrganizationName("MSLVM")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
