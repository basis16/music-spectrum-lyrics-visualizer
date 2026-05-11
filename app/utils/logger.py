"""Centralised application logger.

The logger writes both to the console (stderr) and to a rotating file under
``logs/``. UI panels can attach a :class:`QtLogHandler` to mirror messages
into a Qt widget without blocking the GUI thread.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path
from typing import Callable, Optional

_LOGGER_NAME = "music_spectrum_app"
_DEFAULT_FORMAT = "%(asctime)s  %(levelname)-7s  %(name)s: %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _project_root() -> Path:
    # app/utils/logger.py -> project root is two parents up.
    return Path(__file__).resolve().parents[2]


def _logs_dir() -> Path:
    p = _project_root() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return the shared application logger (or a child logger)."""
    base = logging.getLogger(_LOGGER_NAME)
    if not base.handlers:
        _configure(base)
    if name and name != _LOGGER_NAME:
        return base.getChild(name)
    return base


def _configure(logger: logging.Logger) -> None:
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    fmt = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DEFAULT_DATEFMT)

    # Console handler (info+ to avoid flooding terminal)
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # Rotating file handler (5 MB x 5 files)
    log_file = _logs_dir() / f"app_{time.strftime('%Y%m%d')}.log"
    try:
        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        # Disk full / read-only filesystem - degrade gracefully.
        pass


class CallbackHandler(logging.Handler):
    """Logging handler that forwards records to a Python callback.

    UI widgets use this to receive log lines without taking a hard
    dependency on the Qt event loop inside ``app/utils``.
    """

    def __init__(self, callback: Callable[[str, str], None], level: int = logging.INFO):
        super().__init__(level=level)
        self._callback = callback
        self.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                              datefmt="%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._callback(record.levelname, msg)
        except Exception:
            # Never let a logging error crash the app.
            pass


def save_log_to_file(target_path: str | os.PathLike[str]) -> Path:
    """Concatenate today's log file into ``target_path`` and return the path."""
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    log_file = _logs_dir() / f"app_{time.strftime('%Y%m%d')}.log"
    if log_file.exists():
        target.write_bytes(log_file.read_bytes())
    else:
        target.write_text("(no log entries yet)\n", encoding="utf-8")
    return target
