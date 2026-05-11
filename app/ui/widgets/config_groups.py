"""Reusable configuration groups used by the render pages.

Each group exposes ``apply_to_settings`` / ``load_from_settings`` style
helpers and emits a ``changed`` signal whenever any field updates so the
preview can re-render.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.settings_manager import AppSettings
from app.core.spectrum_styles import available_styles
from app.ui.widgets._common import (
    ColorSwatch,
    PathPicker,
    system_font_families,
)

LYRIC_PRESETS = [
    "Modern Clean",
    "Bold Subtitle",
    "Karaoke Glow",
    "Minimal White",
    "Shadow Text",
    "Neon Lyric",
]


def _label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("QLabel { color: #4a5468; font-weight: 500; }")
    return lbl


def _slider(minimum: int, maximum: int, value: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(minimum, maximum)
    s.setValue(value)
    return s


# ---------------------------------------------------------------------------
# Spectrum
# ---------------------------------------------------------------------------

class SpectrumConfigGroup(QGroupBox):
    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Spectrum", parent)
        form = QFormLayout(self)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.style = QComboBox()
        self.style.addItems(available_styles())

        self.color = ColorSwatch("#5AC8FF")
        self.color2 = ColorSwatch("#FF5AC8")

        col_row = QHBoxLayout()
        col_row.addWidget(self.color)
        col_row.addWidget(_label("→"))
        col_row.addWidget(self.color2)
        col_row.addStretch(1)
        col_widget = QWidget()
        col_widget.setLayout(col_row)

        self.gradient = QCheckBox("Gradient")
        self.gradient.setChecked(True)
        self.glow = QCheckBox("Glow")
        self.glow.setChecked(True)

        self.glow_strength = _slider(0, 200, 100)
        self.smoothness = _slider(0, 95, 35)
        self.sensitivity = _slider(50, 300, 115)
        self.bar_count = QSpinBox()
        self.bar_count.setRange(8, 256)
        self.bar_count.setValue(64)

        self.position = QComboBox()
        self.position.addItems(["bottom", "top", "center", "left", "right"])

        toggle_row = QHBoxLayout()
        toggle_row.addWidget(self.gradient)
        toggle_row.addWidget(self.glow)
        toggle_row.addStretch(1)
        tog_widget = QWidget(); tog_widget.setLayout(toggle_row)

        form.addRow(_label("Style"), self.style)
        form.addRow(_label("Colors"), col_widget)
        form.addRow("", tog_widget)
        form.addRow(_label("Glow strength"), self.glow_strength)
        form.addRow(_label("Smoothness"), self.smoothness)
        form.addRow(_label("Sensitivity"), self.sensitivity)
        form.addRow(_label("Bar count"), self.bar_count)
        form.addRow(_label("Position"), self.position)

        # Tooltips
        self.style.setToolTip("Pick one of the built-in spectrum styles.")
        self.glow_strength.setToolTip(
            "Glow halo strength. Disable glow for the lightest render."
        )
        self.smoothness.setToolTip("How much each frame blends with the previous one.")
        self.sensitivity.setToolTip("Amplify quiet bands so the spectrum stays lively.")

        # Wire up change signals
        for w in (self.style, self.position):
            w.currentIndexChanged.connect(self._emit)
        for chk in (self.gradient, self.glow):
            chk.toggled.connect(self._emit)
        for sl in (self.glow_strength, self.smoothness, self.sensitivity):
            sl.valueChanged.connect(self._emit)
        self.bar_count.valueChanged.connect(self._emit)
        self.color.clicked.connect(self._emit)
        self.color2.clicked.connect(self._emit)

    def _emit(self) -> None:
        self.changed.emit()

    # ------------------------------------------------------------------
    def load(self, s: AppSettings) -> None:
        if s.spectrum_style in [self.style.itemText(i) for i in range(self.style.count())]:
            self.style.setCurrentText(s.spectrum_style)
        self.color.set_color_hex(s.spectrum_color)
        self.color2.set_color_hex(s.spectrum_color2)
        self.gradient.setChecked(s.spectrum_gradient)
        self.glow.setChecked(s.spectrum_glow)
        self.glow_strength.setValue(int(s.spectrum_glow_strength * 100))
        self.smoothness.setValue(int(s.spectrum_smoothness * 100))
        self.sensitivity.setValue(int(s.spectrum_sensitivity * 100))
        self.bar_count.setValue(s.spectrum_bar_count)
        if s.spectrum_position in [self.position.itemText(i) for i in range(self.position.count())]:
            self.position.setCurrentText(s.spectrum_position)

    def save(self, s: AppSettings) -> None:
        s.spectrum_style = self.style.currentText()
        s.spectrum_color = self.color.color_hex()
        s.spectrum_color2 = self.color2.color_hex()
        s.spectrum_gradient = self.gradient.isChecked()
        s.spectrum_glow = self.glow.isChecked()
        s.spectrum_glow_strength = self.glow_strength.value() / 100.0
        s.spectrum_smoothness = self.smoothness.value() / 100.0
        s.spectrum_sensitivity = self.sensitivity.value() / 100.0
        s.spectrum_bar_count = self.bar_count.value()
        s.spectrum_position = self.position.currentText()


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------

class LogoConfigGroup(QGroupBox):
    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Logo", parent)
        form = QFormLayout(self)
        self.path = PathPicker(
            dialog="file",
            filter="Images (*.png *.jpg *.jpeg *.webp)",
            caption="Pick a logo",
        )
        self.size = _slider(2, 40, 12)
        self.opacity = _slider(0, 255, 230)
        self.position = QComboBox()
        self.position.addItems(["top-left", "top-right", "bottom-left",
                                "bottom-right", "center"])
        self.circle = QCheckBox("Circle mask")
        self.shadow = QCheckBox("Shadow")
        self.border = QCheckBox("Border")
        self.glow = QCheckBox("Glow")

        toggles = QHBoxLayout()
        for w in (self.circle, self.shadow, self.border, self.glow):
            toggles.addWidget(w)
        toggles.addStretch(1)
        tog_widget = QWidget(); tog_widget.setLayout(toggles)

        form.addRow(_label("File"), self.path)
        form.addRow(_label("Size (%)"), self.size)
        form.addRow(_label("Opacity"), self.opacity)
        form.addRow(_label("Position"), self.position)
        form.addRow("", tog_widget)

        self.path.edit.textChanged.connect(self._emit)
        for w in (self.size, self.opacity):
            w.valueChanged.connect(self._emit)
        for chk in (self.circle, self.shadow, self.border, self.glow):
            chk.toggled.connect(self._emit)
        self.position.currentIndexChanged.connect(self._emit)

    def _emit(self) -> None:
        self.changed.emit()

    def load(self, s: AppSettings) -> None:
        self.path.set_value(s.logo_path or "")
        self.size.setValue(int(s.logo_size * 100))
        self.opacity.setValue(int(s.logo_opacity))
        if s.logo_position in [self.position.itemText(i)
                                 for i in range(self.position.count())]:
            self.position.setCurrentText(s.logo_position)
        self.circle.setChecked(s.logo_circle)
        self.shadow.setChecked(s.logo_shadow)
        self.border.setChecked(s.logo_border)
        self.glow.setChecked(s.logo_glow)

    def save(self, s: AppSettings) -> None:
        s.logo_path = self.path.value() or None
        s.logo_size = self.size.value() / 100.0
        s.logo_opacity = self.opacity.value()
        s.logo_position = self.position.currentText()
        s.logo_circle = self.circle.isChecked()
        s.logo_shadow = self.shadow.isChecked()
        s.logo_border = self.border.isChecked()
        s.logo_glow = self.glow.isChecked()


# ---------------------------------------------------------------------------
# Lyrics
# ---------------------------------------------------------------------------

class LyricsConfigGroup(QGroupBox):
    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Lyrics", parent)
        form = QFormLayout(self)

        self.font_family = QComboBox()
        families = system_font_families()
        if not families:
            families = ["Arial"]
        self.font_family.addItems(families)
        if "Arial" in families:
            self.font_family.setCurrentText("Arial")

        self.preset = QComboBox()
        self.preset.addItems(LYRIC_PRESETS)

        self.font_size = QSpinBox()
        self.font_size.setRange(12, 200)
        self.font_size.setValue(56)

        self.bold = QCheckBox("Bold")
        self.bold.setChecked(True)
        self.italic = QCheckBox("Italic")

        self.color = ColorSwatch("#FFFFFF")
        self.stroke_color = ColorSwatch("#000000")
        self.stroke = QCheckBox("Stroke")
        self.stroke.setChecked(True)
        self.stroke_width = QSpinBox()
        self.stroke_width.setRange(0, 12)
        self.stroke_width.setValue(3)
        self.shadow = QCheckBox("Shadow")
        self.shadow.setChecked(True)

        self.position = QComboBox()
        self.position.addItems(["top", "center", "bottom"])
        self.position.setCurrentText("center")

        self.align = QComboBox()
        self.align.addItems(["left", "center", "right"])
        self.align.setCurrentText("center")

        self.max_lines = QSpinBox()
        self.max_lines.setRange(1, 5)
        self.max_lines.setValue(2)

        self.animation = QCheckBox("Fade animation")
        self.animation.setChecked(True)

        toggles = QHBoxLayout()
        for w in (self.bold, self.italic, self.stroke, self.shadow, self.animation):
            toggles.addWidget(w)
        toggles.addStretch(1)
        tog_widget = QWidget(); tog_widget.setLayout(toggles)

        colors = QHBoxLayout()
        colors.addWidget(_label("Text"))
        colors.addWidget(self.color)
        colors.addSpacing(20)
        colors.addWidget(_label("Stroke"))
        colors.addWidget(self.stroke_color)
        colors.addWidget(_label("Stroke W"))
        colors.addWidget(self.stroke_width)
        colors.addStretch(1)
        col_widget = QWidget(); col_widget.setLayout(colors)

        form.addRow(_label("Preset"), self.preset)
        form.addRow(_label("Font family"), self.font_family)
        form.addRow(_label("Font size"), self.font_size)
        form.addRow(_label("Colors"), col_widget)
        form.addRow(_label("Position"), self.position)
        form.addRow(_label("Align"), self.align)
        form.addRow(_label("Max lines"), self.max_lines)
        form.addRow("", tog_widget)

        # Apply preset when picked.
        self.preset.currentTextChanged.connect(self._apply_preset)

        # Change signals
        for w in (self.font_family, self.preset, self.position, self.align):
            w.currentIndexChanged.connect(self._emit)
        for sp in (self.font_size, self.stroke_width, self.max_lines):
            sp.valueChanged.connect(self._emit)
        for chk in (self.bold, self.italic, self.stroke, self.shadow, self.animation):
            chk.toggled.connect(self._emit)
        self.color.clicked.connect(self._emit)
        self.stroke_color.clicked.connect(self._emit)

    def _emit(self) -> None:
        self.changed.emit()

    def _apply_preset(self, name: str) -> None:
        if name == "Modern Clean":
            self.bold.setChecked(True); self.italic.setChecked(False)
            self.color.set_color_hex("#FFFFFF"); self.stroke.setChecked(True)
            self.stroke_color.set_color_hex("#000000"); self.stroke_width.setValue(3)
            self.shadow.setChecked(True); self.position.setCurrentText("center")
        elif name == "Bold Subtitle":
            self.bold.setChecked(True); self.italic.setChecked(False)
            self.color.set_color_hex("#FFFFFF"); self.stroke.setChecked(True)
            self.stroke_color.set_color_hex("#000000"); self.stroke_width.setValue(5)
            self.shadow.setChecked(True); self.position.setCurrentText("bottom")
        elif name == "Karaoke Glow":
            self.bold.setChecked(True); self.color.set_color_hex("#FFE36E")
            self.stroke.setChecked(True); self.stroke_color.set_color_hex("#552600")
            self.stroke_width.setValue(4); self.shadow.setChecked(True)
        elif name == "Minimal White":
            self.bold.setChecked(False); self.color.set_color_hex("#FFFFFF")
            self.stroke.setChecked(False); self.shadow.setChecked(False)
        elif name == "Shadow Text":
            self.color.set_color_hex("#FFFFFF"); self.stroke.setChecked(False)
            self.shadow.setChecked(True); self.bold.setChecked(False)
        elif name == "Neon Lyric":
            self.color.set_color_hex("#5AF0FF"); self.stroke.setChecked(True)
            self.stroke_color.set_color_hex("#003344"); self.stroke_width.setValue(2)
            self.shadow.setChecked(True); self.bold.setChecked(True)
        self._emit()

    def load(self, s: AppSettings) -> None:
        if s.lyric_font_family in [self.font_family.itemText(i)
                                     for i in range(self.font_family.count())]:
            self.font_family.setCurrentText(s.lyric_font_family)
        self.font_size.setValue(s.lyric_font_size)
        self.bold.setChecked(s.lyric_bold)
        self.italic.setChecked(s.lyric_italic)
        self.color.set_color_hex(s.lyric_color)
        self.stroke.setChecked(s.lyric_stroke)
        self.stroke_color.set_color_hex(s.lyric_stroke_color)
        self.stroke_width.setValue(s.lyric_stroke_width)
        self.shadow.setChecked(s.lyric_shadow)
        if s.lyric_position in [self.position.itemText(i) for i in range(self.position.count())]:
            self.position.setCurrentText(s.lyric_position)
        if s.lyric_align in [self.align.itemText(i) for i in range(self.align.count())]:
            self.align.setCurrentText(s.lyric_align)
        self.max_lines.setValue(s.lyric_max_lines)
        self.animation.setChecked(s.lyric_animation)
        if s.lyric_preset in LYRIC_PRESETS:
            self.preset.setCurrentText(s.lyric_preset)

    def save(self, s: AppSettings) -> None:
        s.lyric_font_family = self.font_family.currentText()
        s.lyric_font_size = self.font_size.value()
        s.lyric_bold = self.bold.isChecked()
        s.lyric_italic = self.italic.isChecked()
        s.lyric_color = self.color.color_hex()
        s.lyric_stroke = self.stroke.isChecked()
        s.lyric_stroke_color = self.stroke_color.color_hex()
        s.lyric_stroke_width = self.stroke_width.value()
        s.lyric_shadow = self.shadow.isChecked()
        s.lyric_position = self.position.currentText()
        s.lyric_align = self.align.currentText()
        s.lyric_max_lines = self.max_lines.value()
        s.lyric_animation = self.animation.isChecked()
        s.lyric_preset = self.preset.currentText()


# ---------------------------------------------------------------------------
# Output (resolution / fps / quality / encoder)
# ---------------------------------------------------------------------------

class OutputConfigGroup(QGroupBox):
    changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Output", parent)
        form = QFormLayout(self)

        self.resolution = QComboBox()
        self.resolution.addItems(["720p", "1080p", "1440p", "4K", "custom"])
        self.custom_res = PathPicker(dialog="none", filter="")
        # We'll re-purpose the line edit; hide the browse button.
        self.custom_res.button.setVisible(False)
        self.custom_res.edit.setPlaceholderText("e.g. 1920x1080")

        self.fps = QComboBox()
        self.fps.addItems(["24", "30", "60"])
        self.fps.setCurrentText("30")

        self.quality = QComboBox()
        self.quality.addItems(["fast", "balanced", "high"])
        self.quality.setCurrentText("balanced")

        self.encoder = QComboBox()
        self.encoder.addItems(["auto", "nvenc", "qsv", "amf", "cpu"])

        self.bg_fit = QComboBox()
        self.bg_fit.addItems(["cover", "fit-blur", "stretch"])

        self.low_spec = QCheckBox("Low-Spec Mode")
        self.low_spec.setToolTip(
            "Disables heavy glow effects, lowers preview quality, "
            "and uses the FFmpeg veryfast preset."
        )

        form.addRow(_label("Resolution"), self.resolution)
        form.addRow(_label("Custom (WxH)"), self.custom_res)
        form.addRow(_label("FPS"), self.fps)
        form.addRow(_label("Quality"), self.quality)
        form.addRow(_label("Encoder"), self.encoder)
        form.addRow(_label("Background fit"), self.bg_fit)
        form.addRow("", self.low_spec)

        for w in (self.resolution, self.fps, self.quality, self.encoder, self.bg_fit):
            w.currentIndexChanged.connect(self._emit)
        self.custom_res.edit.textChanged.connect(self._emit)
        self.low_spec.toggled.connect(self._emit)

    def _emit(self) -> None:
        self.changed.emit()

    def load(self, s: AppSettings) -> None:
        if s.resolution in [self.resolution.itemText(i)
                              for i in range(self.resolution.count())]:
            self.resolution.setCurrentText(s.resolution)
        self.custom_res.set_value(s.custom_resolution)
        self.fps.setCurrentText(str(s.fps))
        self.quality.setCurrentText(s.quality)
        self.encoder.setCurrentText(s.encoder_preference)
        self.bg_fit.setCurrentText(s.background_fit)
        self.low_spec.setChecked(s.low_spec_mode)

    def save(self, s: AppSettings) -> None:
        s.resolution = self.resolution.currentText()
        s.custom_resolution = self.custom_res.value() or "1920x1080"
        s.fps = int(self.fps.currentText())
        s.quality = self.quality.currentText()
        s.encoder_preference = self.encoder.currentText()
        s.background_fit = self.bg_fit.currentText()
        s.low_spec_mode = self.low_spec.isChecked()
