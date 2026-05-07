"""Logger manager.

Provides:
- a process-wide ``logging`` setup that writes to a rotating log file in ``temp/``.
- a Qt-safe :class:`LogBus` singleton that emits log lines as a Qt signal so the
  UI panel can subscribe to live log output without race conditions.

Modules across the app should call::

    from logger_manager import get_logger
    log = get_logger(__name__)
    log.info("Loading audio...")

The UI listens via ``LogBus.instance().log_emitted``.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal


# ---------------------------------------------------------------------------
# Qt log bus
# ---------------------------------------------------------------------------
class LogBus(QObject):
    """Singleton bus that re-emits log records as Qt signals.

    UI widgets connect to :attr:`log_emitted` to display real-time log output.
    """

    log_emitted = Signal(str, str)  # (level_name, formatted_message)

    _instance: "Optional[LogBus]" = None

    @classmethod
    def instance(cls) -> "LogBus":
        if cls._instance is None:
            cls._instance = LogBus()
        return cls._instance


class _QtSignalHandler(logging.Handler):
    """Logging handler that pushes formatted records onto the LogBus signal."""

    def __init__(self) -> None:
        super().__init__()
        self.bus = LogBus.instance()

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            msg = self.format(record)
            self.bus.log_emitted.emit(record.levelname, msg)
        except Exception:  # pragma: no cover - never let logging crash the app
            self.handleError(record)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
_INITIALIZED = False
_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def setup_logging(temp_dir: str | os.PathLike[str] = "temp",
                  level: int = logging.INFO) -> Path:
    """Configure logging once for the whole process.

    Returns the path to the log file.
    """
    global _INITIALIZED
    log_dir = Path(temp_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    if _INITIALIZED:
        return log_file

    root = logging.getLogger()
    root.setLevel(level)
    # Wipe any existing handlers (e.g. when called twice in a notebook context).
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)

    # Rotating file handler so logs don't grow forever.
    file_h = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_h.setFormatter(fmt)
    root.addHandler(file_h)

    # Stream to stderr too (useful during development / when launched from .bat).
    stream_h = logging.StreamHandler(sys.stderr)
    stream_h.setFormatter(fmt)
    root.addHandler(stream_h)

    # Qt signal handler for the UI log panel.
    qt_h = _QtSignalHandler()
    qt_h.setFormatter(fmt)
    root.addHandler(qt_h)

    _INITIALIZED = True
    logging.getLogger(__name__).info("Logging initialised -> %s", log_file)
    return log_file


def get_logger(name: str) -> logging.Logger:
    """Return a child logger; auto-initialises root logger on first call."""
    if not _INITIALIZED:
        setup_logging()
    return logging.getLogger(name)
