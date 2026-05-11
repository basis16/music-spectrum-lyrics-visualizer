"""Theme loader. Reads QSS files and detects the OS preference on Windows."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

ThemeName = Literal["light", "dark", "auto"]

_HERE = Path(__file__).parent


def load_qss(theme: ThemeName) -> str:
    name = _resolve(theme)
    p = _HERE / f"{name}.qss"
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _resolve(theme: ThemeName) -> str:
    if theme in ("light", "dark"):
        return theme
    return detect_windows_theme()


def detect_windows_theme() -> str:
    """Return ``'light'`` or ``'dark'`` based on the OS, defaulting to light."""
    try:
        import sys
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if int(value) == 1 else "dark"
    except Exception:
        pass
    return "light"
