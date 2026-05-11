"""UI helpers shared between the render pages."""
from __future__ import annotations

from typing import Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

RGBA = Tuple[int, int, int, int]


def hex_to_rgba(hex_color: str, alpha: int = 255) -> RGBA:
    h = (hex_color or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (0, 0, 0, alpha)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def rgba_to_hex(rgba: RGBA) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgba[:3])


def system_font_families() -> list[str]:
    """Return the list of system font families (cross-platform)."""
    try:
        # In PySide6 6.5+ this is a static method.
        return sorted(QFontDatabase.families())
    except TypeError:
        # Older versions need an instance.
        return sorted(QFontDatabase().families())


class PathPicker(QWidget):
    """A simple ``[ line edit ] [Browse]`` row used for many path fields."""

    def __init__(self, *, dialog: str = "file", filter: str = "All files (*)",
                  caption: str = "Select",
                  parent: QWidget | None = None):
        super().__init__(parent)
        self.dialog = dialog
        self.filter = filter
        self.caption = caption
        self.edit = QLineEdit(self)
        self.button = QPushButton("Browse...", self)
        self.button.setProperty("role", "secondary")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)
        self.button.clicked.connect(self._on_browse)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, v: str | None) -> None:
        self.edit.setText(v or "")

    def _on_browse(self) -> None:
        start = self.edit.text() or ""
        if self.dialog == "folder":
            path = QFileDialog.getExistingDirectory(self, self.caption, start)
        elif self.dialog == "save":
            path, _ = QFileDialog.getSaveFileName(self, self.caption, start, self.filter)
        else:
            path, _ = QFileDialog.getOpenFileName(self, self.caption, start, self.filter)
        if path:
            self.edit.setText(path)


class ColorSwatch(QPushButton):
    """A clickable swatch that opens ``QColorDialog``."""

    def __init__(self, hex_color: str = "#5AC8FF", parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(48, 28)
        self.setProperty("role", "secondary")
        self._hex = hex_color
        self._update_style()
        self.clicked.connect(self._on_click)

    def color_hex(self) -> str:
        return self._hex

    def set_color_hex(self, value: str) -> None:
        self._hex = value
        self._update_style()

    def _update_style(self) -> None:
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._hex}; border: 1px solid #d6dbe7;"
            f" border-radius: 6px; }}"
        )

    def _on_click(self) -> None:
        col = QColor(self._hex)
        new = QColorDialog.getColor(col, self, "Pick a color",
                                     QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if new.isValid():
            self.set_color_hex(new.name().upper())
            # Re-emit so listeners can react.
            self.clicked_color_changed()

    def clicked_color_changed(self) -> None:  # pragma: no cover - subclass hook
        pass


__all__ = ["PathPicker", "ColorSwatch", "hex_to_rgba", "rgba_to_hex",
            "system_font_families"]
