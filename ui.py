"""PySide6 main window: dark mode, modern, organised into tabs.

Layout:
    +-----------------------------------------------------------+
    |   File picker   |  Background | Lyrics | Logo | CTA | ... |
    +-----------------+-----------------------+-------------------+
    |  Preview thumbnail (QMediaPlayer)  |  Style controls       |
    +------------------------------------+-----------------------+
    |  Progress bar  +  Render controls                          |
    +------------------------------------------------------------+
    |  Live log panel                                             |
    +-----------------------------------------------------------+

All long-running work (analysis, rendering, lyric generation) is dispatched to
QThread workers so the UI never freezes.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QObject, QThread, QUrl, Qt, Signal, Slot,
)
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPalette, QTextCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import audio_analyzer
import ffmpeg_manager
import lyric_generator
import performance_manager
from logger_manager import LogBus, get_logger
from settings import (
    BAR_PRESETS,
    BackgroundConfig,
    BackgroundType,
    CTAAnim,
    CTATiming,
    LogoAnim,
    LogoPos,
    LyricMode,
    PerfMode,
    ProjectSettings,
    SpectrumStyle,
)
from video_renderer import VideoRenderer

log = get_logger(__name__)

AUDIO_FILTER = "Audio Files (*.mp3 *.wav *.m4a *.flac);;All Files (*)"
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)"
VIDEO_FILTER = "Videos (*.mp4 *.mov *.mkv *.avi *.webm);;All Files (*)"


# ---------------------------------------------------------------------------
# Worker objects (run on QThreads)
# ---------------------------------------------------------------------------
class _RenderWorker(QObject):
    progress = Signal(int, int)     # current_frame, total
    status = Signal(str)
    finished = Signal(object)       # RenderResult

    def __init__(self, renderer: VideoRenderer, output: str,
                 max_seconds: Optional[float] = None) -> None:
        super().__init__()
        self.renderer = renderer
        self.output = output
        self.max_seconds = max_seconds

    @Slot()
    def run(self) -> None:
        result = self.renderer.render(
            self.output,
            progress=lambda c, t: self.progress.emit(c, t),
            status=lambda msg: self.status.emit(msg),
            max_seconds=self.max_seconds,
        )
        self.finished.emit(result)


class _LyricsWorker(QObject):
    status = Signal(str)
    finished = Signal(object)       # LyricsTrack

    def __init__(self, audio_path: str) -> None:
        super().__init__()
        self.audio_path = audio_path

    @Slot()
    def run(self) -> None:
        track = lyric_generator.generate(
            self.audio_path,
            progress=lambda msg: self.status.emit(msg),
        )
        self.finished.emit(track)


class _AnalysisWorker(QObject):
    status = Signal(str)
    finished = Signal(object)       # SpectrumFrames or Exception

    def __init__(self, audio_path: str, fps: int, bar_count: int,
                 sensitivity: float, bass: float, treble: float,
                 smoothing: float) -> None:
        super().__init__()
        self.kwargs = dict(
            fps=fps, bar_count=bar_count, sensitivity=sensitivity,
            bass_boost=bass, treble_boost=treble, smoothing=smoothing,
        )
        self.audio_path = audio_path

    @Slot()
    def run(self) -> None:
        try:
            self.status.emit("Menganalisis audio (librosa)...")
            data = audio_analyzer.analyze(self.audio_path, **self.kwargs)
            self.finished.emit(data)
        except Exception as exc:  # noqa: BLE001
            log.exception("Audio analysis failed")
            self.finished.emit(exc)


# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------
class _ColorButton(QToolButton):
    color_changed = Signal(tuple)  # RGB tuple 0-255

    def __init__(self, initial: tuple[int, int, int], parent=None) -> None:
        super().__init__(parent)
        self._color = initial
        self.setMinimumWidth(80)
        self.clicked.connect(self._pick)
        self._refresh()

    def _refresh(self) -> None:
        r, g, b = self._color
        self.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #555; border-radius: 4px;"
        )
        self.setText("")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(*self._color), self)
        if c.isValid():
            self._color = (c.red(), c.green(), c.blue())
            self._refresh()
            self.color_changed.emit(self._color)

    def color(self) -> tuple[int, int, int]:
        return self._color

    def set_color(self, c: tuple[int, int, int]) -> None:
        self._color = c
        self._refresh()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Music Spectrum Lyrics Visualizer")
        self.resize(1280, 820)
        self.settings = ProjectSettings()
        self.spectrum_data = None       # cached audio_analyzer.SpectrumFrames
        self.lyrics_track = None        # cached LyricsTrack
        self._render_thread: Optional[QThread] = None
        self._render_worker: Optional[_RenderWorker] = None
        self._render_renderer: Optional[VideoRenderer] = None
        self._analysis_thread: Optional[QThread] = None
        self._lyrics_thread: Optional[QThread] = None

        # Apply system info to defaults.
        sysinfo = performance_manager.detect()
        self.settings.apply_perf_mode(performance_manager.recommended_mode(sysinfo))

        self._build_ui()
        self._wire_log_bus()
        self._refresh_ffmpeg_status()
        warning = performance_manager.low_spec_warning(sysinfo)
        if warning:
            self.statusBar().showMessage(warning, 10_000)
            log.warning(warning)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        root.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._build_main_area())
        splitter.addWidget(self._build_log_panel())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

    def _build_header(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)

        # Music chooser
        music_group = QGroupBox("Music")
        ml = QHBoxLayout(music_group)
        self.music_path = QLineEdit()
        self.music_path.setPlaceholderText("Pilih file MP3 / WAV / M4A / FLAC...")
        self.music_path.setReadOnly(True)
        btn_music = QPushButton("Browse…")
        btn_music.clicked.connect(self._pick_music)
        ml.addWidget(self.music_path, 1)
        ml.addWidget(btn_music)

        # FFmpeg
        ffmpeg_group = QGroupBox("FFmpeg")
        fl = QHBoxLayout(ffmpeg_group)
        self.ffmpeg_status = QLabel("checking...")
        btn_install = QPushButton("Install FFmpeg Online")
        btn_install.clicked.connect(self._install_ffmpeg)
        fl.addWidget(self.ffmpeg_status, 1)
        fl.addWidget(btn_install)
        self.btn_install_ffmpeg = btn_install

        # Performance mode
        perf_group = QGroupBox("Mode")
        pl = QHBoxLayout(perf_group)
        self.perf_combo = QComboBox()
        for m in PerfMode:
            self.perf_combo.addItem(m.value, m)
        self.perf_combo.setCurrentText(self.settings.render.perf_mode.value)
        self.perf_combo.currentTextChanged.connect(self._on_perf_changed)
        pl.addWidget(self.perf_combo, 1)

        layout.addWidget(music_group, 3)
        layout.addWidget(ffmpeg_group, 2)
        layout.addWidget(perf_group, 1)
        return bar

    def _build_main_area(self) -> QWidget:
        area = QSplitter(Qt.Orientation.Horizontal)
        area.addWidget(self._build_preview_panel())
        area.addWidget(self._build_settings_tabs())
        area.setStretchFactor(0, 3)
        area.setStretchFactor(1, 4)
        return area

    def _build_preview_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Preview")
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        layout.addWidget(title)

        self.preview_widget = QVideoWidget()
        self.preview_widget.setMinimumHeight(280)
        self.preview_widget.setStyleSheet("background: #111;")
        layout.addWidget(self.preview_widget, 1)

        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.preview_widget)

        # Preview controls
        ctl = QHBoxLayout()
        self.preview_seconds = QSpinBox()
        self.preview_seconds.setRange(5, 30)
        self.preview_seconds.setValue(15)
        self.preview_seconds.setSuffix(" s")
        self.btn_preview = QPushButton("Generate Preview")
        self.btn_preview.clicked.connect(self._do_preview)
        self.btn_play = QPushButton("Play")
        self.btn_play.clicked.connect(self._toggle_play)
        ctl.addWidget(QLabel("Preview length:"))
        ctl.addWidget(self.preview_seconds)
        ctl.addStretch(1)
        ctl.addWidget(self.btn_preview)
        ctl.addWidget(self.btn_play)
        layout.addLayout(ctl)

        # Render bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        render_row = QHBoxLayout()
        self.btn_render = QPushButton("Start Render")
        self.btn_render.clicked.connect(self._do_render)
        self.btn_cancel = QPushButton("Cancel Render")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_render)
        self.btn_clear_log = QPushButton("Clear Log")
        self.btn_clear_log.clicked.connect(lambda: self.log_view.clear())
        render_row.addWidget(self.btn_render)
        render_row.addWidget(self.btn_cancel)
        render_row.addStretch(1)
        render_row.addWidget(self.btn_clear_log)
        layout.addLayout(render_row)

        return panel

    def _build_settings_tabs(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._tab_background(), "Background")
        tabs.addTab(self._tab_spectrum(), "Spectrum")
        tabs.addTab(self._tab_lyrics(), "Lyrics")
        tabs.addTab(self._tab_logo(), "Logo")
        tabs.addTab(self._tab_cta(), "CTA")
        tabs.addTab(self._tab_render(), "Render")
        return tabs

    # -- Tab: Background -----------------------------------------------
    def _tab_background(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self.bg_combo = QComboBox()
        for k in BackgroundType:
            self.bg_combo.addItem(k.value, k)
        self.bg_combo.setCurrentText(self.settings.background.kind.value)
        self.bg_combo.currentIndexChanged.connect(self._on_bg_changed)

        self.bg_path = QLineEdit()
        self.bg_path.setReadOnly(True)
        self.bg_path.setPlaceholderText("Pilih gambar atau video...")
        bg_browse = QPushButton("Browse…")
        bg_browse.clicked.connect(self._pick_background)
        bg_row = QHBoxLayout()
        bg_row.addWidget(self.bg_path, 1)
        bg_row.addWidget(bg_browse)
        bg_row_w = QWidget(); bg_row_w.setLayout(bg_row)

        self.bg_color = _ColorButton(self.settings.background.solid_color)
        self.bg_color.color_changed.connect(self._on_bg_color)

        layout.addRow("Type:", self.bg_combo)
        layout.addRow("File:", bg_row_w)
        layout.addRow("Solid color:", self.bg_color)
        return w

    # -- Tab: Spectrum -------------------------------------------------
    def _tab_spectrum(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self.spec_style = QComboBox()
        for s in SpectrumStyle:
            self.spec_style.addItem(s.value, s)
        self.spec_style.setCurrentText(self.settings.spectrum.style.value)
        self.spec_style.currentIndexChanged.connect(self._on_spec_changed)

        self.spec_preset = QComboBox()
        self.spec_preset.addItems(list(BAR_PRESETS.keys()))
        self.spec_preset.setCurrentText(self.settings.spectrum.preset)
        self.spec_preset.currentTextChanged.connect(self._apply_preset)

        self.spec_bars = QSpinBox(); self.spec_bars.setRange(16, 192)
        self.spec_bars.setValue(self.settings.spectrum.bar_count)
        self.spec_bars.valueChanged.connect(lambda v: self._set_spec("bar_count", int(v)))

        self.spec_sens = QDoubleSpinBox()
        self.spec_sens.setRange(0.1, 5.0); self.spec_sens.setSingleStep(0.1)
        self.spec_sens.setValue(self.settings.spectrum.sensitivity)
        self.spec_sens.valueChanged.connect(lambda v: self._set_spec("sensitivity", float(v)))

        self.spec_bass = QDoubleSpinBox()
        self.spec_bass.setRange(0.5, 4.0); self.spec_bass.setSingleStep(0.05)
        self.spec_bass.setValue(self.settings.spectrum.bass_boost)
        self.spec_bass.valueChanged.connect(lambda v: self._set_spec("bass_boost", float(v)))

        self.spec_treble = QDoubleSpinBox()
        self.spec_treble.setRange(0.5, 4.0); self.spec_treble.setSingleStep(0.05)
        self.spec_treble.setValue(self.settings.spectrum.treble_boost)
        self.spec_treble.valueChanged.connect(lambda v: self._set_spec("treble_boost", float(v)))

        self.spec_smooth = QDoubleSpinBox()
        self.spec_smooth.setRange(0.0, 0.95); self.spec_smooth.setSingleStep(0.05)
        self.spec_smooth.setValue(self.settings.spectrum.smoothing)
        self.spec_smooth.valueChanged.connect(lambda v: self._set_spec("smoothing", float(v)))

        self.spec_glow = QCheckBox("Glow")
        self.spec_glow.setChecked(self.settings.spectrum.glow)
        self.spec_glow.toggled.connect(lambda v: self._set_spec("glow", bool(v)))
        self.spec_refl = QCheckBox("Reflection")
        self.spec_refl.setChecked(self.settings.spectrum.reflection)
        self.spec_refl.toggled.connect(lambda v: self._set_spec("reflection", bool(v)))
        self.spec_rainbow = QCheckBox("Rainbow")
        self.spec_rainbow.setChecked(self.settings.spectrum.rainbow)
        self.spec_rainbow.toggled.connect(lambda v: self._set_spec("rainbow", bool(v)))
        self.spec_rounded = QCheckBox("Rounded bars")
        self.spec_rounded.setChecked(self.settings.spectrum.rounded)
        self.spec_rounded.toggled.connect(lambda v: self._set_spec("rounded", bool(v)))

        flags = QHBoxLayout()
        for cb in [self.spec_glow, self.spec_refl, self.spec_rainbow, self.spec_rounded]:
            flags.addWidget(cb)
        flags_w = QWidget(); flags_w.setLayout(flags)

        layout.addRow("Style:", self.spec_style)
        layout.addRow("Preset:", self.spec_preset)
        layout.addRow("Bar count:", self.spec_bars)
        layout.addRow("Sensitivity:", self.spec_sens)
        layout.addRow("Bass boost:", self.spec_bass)
        layout.addRow("Treble boost:", self.spec_treble)
        layout.addRow("Smoothing:", self.spec_smooth)
        layout.addRow("Effects:", flags_w)
        return w

    # -- Tab: Lyrics ---------------------------------------------------
    def _tab_lyrics(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self.lyric_mode = QComboBox()
        for m in LyricMode:
            self.lyric_mode.addItem(m.value, m)
        self.lyric_mode.setCurrentText(self.settings.lyrics.mode.value)
        self.lyric_mode.currentIndexChanged.connect(self._on_lyric_mode)

        self.lyric_size = QSpinBox(); self.lyric_size.setRange(16, 200)
        self.lyric_size.setValue(self.settings.lyrics.font_size)
        self.lyric_size.valueChanged.connect(lambda v: self._set_lyric("font_size", int(v)))

        self.lyric_color = _ColorButton(self.settings.lyrics.color_normal)
        self.lyric_color.color_changed.connect(lambda c: self._set_lyric("color_normal", c))

        self.lyric_hl = _ColorButton(self.settings.lyrics.color_highlight)
        self.lyric_hl.color_changed.connect(lambda c: self._set_lyric("color_highlight", c))

        self.lyric_outline = QSpinBox(); self.lyric_outline.setRange(0, 10)
        self.lyric_outline.setValue(self.settings.lyrics.outline)
        self.lyric_outline.valueChanged.connect(lambda v: self._set_lyric("outline", int(v)))

        self.lyric_y = QDoubleSpinBox()
        self.lyric_y.setRange(0.05, 0.95); self.lyric_y.setSingleStep(0.02)
        self.lyric_y.setValue(self.settings.lyrics.y_ratio)
        self.lyric_y.valueChanged.connect(lambda v: self._set_lyric("y_ratio", float(v)))

        gen_row = QHBoxLayout()
        self.btn_lyrics = QPushButton("Auto-generate (Whisper)")
        self.btn_lyrics.clicked.connect(self._generate_lyrics)
        self.btn_lyrics_load = QPushButton("Load .lrc / .srt")
        self.btn_lyrics_load.clicked.connect(self._load_lyrics_file)
        gen_row.addWidget(self.btn_lyrics)
        gen_row.addWidget(self.btn_lyrics_load)
        gen_row_w = QWidget(); gen_row_w.setLayout(gen_row)

        self.lyric_status = QLabel("No lyrics loaded.")

        layout.addRow("Mode:", self.lyric_mode)
        layout.addRow("Font size:", self.lyric_size)
        layout.addRow("Normal color:", self.lyric_color)
        layout.addRow("Highlight color:", self.lyric_hl)
        layout.addRow("Outline:", self.lyric_outline)
        layout.addRow("Y position (0..1):", self.lyric_y)
        layout.addRow("Generate:", gen_row_w)
        layout.addRow("Status:", self.lyric_status)
        return w

    # -- Tab: Logo -----------------------------------------------------
    def _tab_logo(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self.logo_enabled = QCheckBox("Enable logo / watermark")
        self.logo_enabled.setChecked(self.settings.logo.enabled)
        self.logo_enabled.toggled.connect(lambda v: self._set_logo("enabled", bool(v)))

        self.logo_path = QLineEdit(); self.logo_path.setReadOnly(True)
        self.logo_path.setPlaceholderText("Pilih PNG transparan / JPG...")
        b = QPushButton("Browse…"); b.clicked.connect(self._pick_logo)
        row = QHBoxLayout(); row.addWidget(self.logo_path, 1); row.addWidget(b)
        rw = QWidget(); rw.setLayout(row)

        self.logo_pos = QComboBox()
        for p in LogoPos:
            self.logo_pos.addItem(p.value, p)
        self.logo_pos.setCurrentText(self.settings.logo.position.value)
        self.logo_pos.currentIndexChanged.connect(
            lambda _: self._set_logo("position", self.logo_pos.currentData()))

        self.logo_anim = QComboBox()
        for a in LogoAnim:
            self.logo_anim.addItem(a.value, a)
        self.logo_anim.setCurrentText(self.settings.logo.animation.value)
        self.logo_anim.currentIndexChanged.connect(
            lambda _: self._set_logo("animation", self.logo_anim.currentData()))

        self.logo_size = QDoubleSpinBox()
        self.logo_size.setRange(0.02, 0.8); self.logo_size.setSingleStep(0.01)
        self.logo_size.setValue(self.settings.logo.size_ratio)
        self.logo_size.valueChanged.connect(lambda v: self._set_logo("size_ratio", float(v)))

        self.logo_opacity = QDoubleSpinBox()
        self.logo_opacity.setRange(0.0, 1.0); self.logo_opacity.setSingleStep(0.05)
        self.logo_opacity.setValue(self.settings.logo.opacity)
        self.logo_opacity.valueChanged.connect(lambda v: self._set_logo("opacity", float(v)))

        self.logo_margin = QSpinBox(); self.logo_margin.setRange(0, 200)
        self.logo_margin.setValue(self.settings.logo.margin)
        self.logo_margin.valueChanged.connect(lambda v: self._set_logo("margin", int(v)))

        layout.addRow(self.logo_enabled)
        layout.addRow("File:", rw)
        layout.addRow("Position:", self.logo_pos)
        layout.addRow("Animation:", self.logo_anim)
        layout.addRow("Size ratio:", self.logo_size)
        layout.addRow("Opacity:", self.logo_opacity)
        layout.addRow("Margin (px):", self.logo_margin)
        return w

    # -- Tab: CTA ------------------------------------------------------
    def _tab_cta(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self.cta_enabled = QCheckBox("Enable CTA animation")
        self.cta_enabled.setChecked(self.settings.cta.enabled)
        self.cta_enabled.toggled.connect(lambda v: self._set_cta("enabled", bool(v)))

        self.cta_text = QLineEdit(self.settings.cta.text)
        self.cta_text.textChanged.connect(lambda v: self._set_cta("text", v))

        self.cta_anim = QComboBox()
        for a in CTAAnim:
            self.cta_anim.addItem(a.value, a)
        self.cta_anim.setCurrentText(self.settings.cta.animation.value)
        self.cta_anim.currentIndexChanged.connect(
            lambda _: self._set_cta("animation", self.cta_anim.currentData()))

        self.cta_timing = QComboBox()
        for tname in CTATiming:
            self.cta_timing.addItem(tname.value, tname)
        self.cta_timing.setCurrentText(self.settings.cta.timing.value)
        self.cta_timing.currentIndexChanged.connect(self._on_cta_timing)

        self.cta_custom = QDoubleSpinBox()
        self.cta_custom.setRange(0.0, 9999.0); self.cta_custom.setSingleStep(0.5); self.cta_custom.setSuffix(" s")
        self.cta_custom.setValue(self.settings.cta.custom_time)
        self.cta_custom.setEnabled(self.settings.cta.timing == CTATiming.CUSTOM)
        self.cta_custom.valueChanged.connect(lambda v: self._set_cta("custom_time", float(v)))

        self.cta_duration = QDoubleSpinBox()
        self.cta_duration.setRange(0.5, 30.0); self.cta_duration.setSingleStep(0.5); self.cta_duration.setSuffix(" s")
        self.cta_duration.setValue(self.settings.cta.duration)
        self.cta_duration.valueChanged.connect(lambda v: self._set_cta("duration", float(v)))

        self.cta_text_color = _ColorButton(self.settings.cta.color_text)
        self.cta_text_color.color_changed.connect(lambda c: self._set_cta("color_text", c))
        self.cta_btn_color = _ColorButton(self.settings.cta.color_button)
        self.cta_btn_color.color_changed.connect(lambda c: self._set_cta("color_button", c))

        self.cta_size = QDoubleSpinBox()
        self.cta_size.setRange(0.05, 0.6); self.cta_size.setSingleStep(0.01)
        self.cta_size.setValue(self.settings.cta.size_ratio)
        self.cta_size.valueChanged.connect(lambda v: self._set_cta("size_ratio", float(v)))

        layout.addRow(self.cta_enabled)
        layout.addRow("Text:", self.cta_text)
        layout.addRow("Animation:", self.cta_anim)
        layout.addRow("Timing:", self.cta_timing)
        layout.addRow("Custom time:", self.cta_custom)
        layout.addRow("Duration:", self.cta_duration)
        layout.addRow("Text color:", self.cta_text_color)
        layout.addRow("Button color:", self.cta_btn_color)
        layout.addRow("Size ratio:", self.cta_size)
        return w

    # -- Tab: Render ---------------------------------------------------
    def _tab_render(self) -> QWidget:
        w = QWidget()
        layout = QFormLayout(w)
        self.render_w = QSpinBox(); self.render_w.setRange(360, 4096)
        self.render_w.setValue(self.settings.render.width)
        self.render_w.valueChanged.connect(lambda v: self._set_render("width", int(v)))
        self.render_h = QSpinBox(); self.render_h.setRange(240, 2160)
        self.render_h.setValue(self.settings.render.height)
        self.render_h.valueChanged.connect(lambda v: self._set_render("height", int(v)))

        res_row = QHBoxLayout()
        for label, (rw, rh) in [("480p", (854, 480)), ("720p", (1280, 720)),
                                ("1080p", (1920, 1080))]:
            btn = QPushButton(label); btn.clicked.connect(
                lambda _=False, w_=rw, h_=rh: (self.render_w.setValue(w_),
                                               self.render_h.setValue(h_)))
            res_row.addWidget(btn)
        res_w = QWidget(); res_w.setLayout(res_row)

        self.render_fps = QComboBox()
        for v in (24, 30, 60):
            self.render_fps.addItem(str(v), v)
        self.render_fps.setCurrentText(str(self.settings.render.fps))
        self.render_fps.currentIndexChanged.connect(
            lambda _: self._set_render("fps", int(self.render_fps.currentData())))

        self.render_preset = QComboBox()
        for v in ("ultrafast", "veryfast", "fast", "medium", "slow"):
            self.render_preset.addItem(v)
        self.render_preset.setCurrentText(self.settings.render.ffmpeg_preset)
        self.render_preset.currentTextChanged.connect(
            lambda v: self._set_render("ffmpeg_preset", v))

        self.render_crf = QSpinBox(); self.render_crf.setRange(12, 32)
        self.render_crf.setValue(self.settings.render.crf)
        self.render_crf.valueChanged.connect(lambda v: self._set_render("crf", int(v)))

        self.render_bitrate = QLineEdit(self.settings.render.bitrate or "")
        self.render_bitrate.setPlaceholderText("Auto (CRF). Contoh: 6M, 4500k")
        self.render_bitrate.editingFinished.connect(
            lambda: self._set_render("bitrate", self.render_bitrate.text().strip() or None))

        self.render_outdir = QLineEdit(self.settings.output_dir)
        b = QPushButton("…"); b.setFixedWidth(28); b.clicked.connect(self._pick_outdir)
        out_row = QHBoxLayout(); out_row.addWidget(self.render_outdir, 1); out_row.addWidget(b)
        out_w = QWidget(); out_w.setLayout(out_row)

        layout.addRow("Width:", self.render_w)
        layout.addRow("Height:", self.render_h)
        layout.addRow("Quick:", res_w)
        layout.addRow("FPS:", self.render_fps)
        layout.addRow("FFmpeg preset:", self.render_preset)
        layout.addRow("CRF:", self.render_crf)
        layout.addRow("Bitrate:", self.render_bitrate)
        layout.addRow("Output dir:", out_w)
        return w

    def _build_log_panel(self) -> QWidget:
        box = QGroupBox("Log")
        layout = QVBoxLayout(box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_view.setFont(font)
        layout.addWidget(self.log_view)
        return box

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def _wire_log_bus(self) -> None:
        bus = LogBus.instance()
        bus.log_emitted.connect(self._append_log)

    @Slot(str, str)
    def _append_log(self, level: str, msg: str) -> None:
        color_map = {
            "DEBUG": "#888",
            "INFO": "#dcdcdc",
            "WARNING": "#f0c674",
            "ERROR": "#e06c75",
            "CRITICAL": "#ff5555",
        }
        color = color_map.get(level, "#dcdcdc")
        self.log_view.appendHtml(
            f'<span style="color:{color};">{msg.replace("<", "&lt;")}</span>'
        )
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    # ------------------------------------------------------------------
    # File pickers
    # ------------------------------------------------------------------
    def _pick_music(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Pilih file musik", "", AUDIO_FILTER)
        if path:
            self.music_path.setText(path)
            self.settings.audio_path = path
            self.spectrum_data = None     # invalidate cached analysis
            self.lyrics_track = None
            self.lyric_status.setText("No lyrics loaded.")
            log.info("Audio dipilih: %s", path)

    def _pick_background(self) -> None:
        kind = self.bg_combo.currentData()
        flt = IMAGE_FILTER if kind == BackgroundType.IMAGE else VIDEO_FILTER
        path, _ = QFileDialog.getOpenFileName(self, "Pilih background", "", flt)
        if path:
            self.bg_path.setText(path)
            self.settings.background.path = path

    def _pick_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Pilih logo", "", IMAGE_FILTER)
        if path:
            self.logo_path.setText(path)
            self.settings.logo.path = path

    def _pick_outdir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Pilih output folder",
                                                self.settings.output_dir)
        if path:
            self.render_outdir.setText(path)
            self.settings.output_dir = path

    # ------------------------------------------------------------------
    # State setters
    # ------------------------------------------------------------------
    def _set_spec(self, attr: str, value) -> None:
        setattr(self.settings.spectrum, attr, value)
        # Re-running analysis on every change is expensive; invalidate so the
        # next preview/render rebuilds it.
        self.spectrum_data = None

    def _set_lyric(self, attr: str, value) -> None:
        setattr(self.settings.lyrics, attr, value)

    def _set_logo(self, attr: str, value) -> None:
        setattr(self.settings.logo, attr, value)

    def _set_cta(self, attr: str, value) -> None:
        setattr(self.settings.cta, attr, value)

    def _set_render(self, attr: str, value) -> None:
        setattr(self.settings.render, attr, value)
        self.spectrum_data = None

    # ------------------------------------------------------------------
    # Preset / mode handlers
    # ------------------------------------------------------------------
    def _apply_preset(self, name: str) -> None:
        preset = BAR_PRESETS.get(name)
        if not preset:
            return
        for key, value in preset.items():
            setattr(self.settings.spectrum, key, value)
        self.settings.spectrum.preset = name
        self.spec_glow.setChecked(self.settings.spectrum.glow)
        self.spec_rainbow.setChecked(self.settings.spectrum.rainbow)
        log.info("Preset spectrum: %s", name)

    def _on_perf_changed(self, value: str) -> None:
        for m in PerfMode:
            if m.value == value:
                self.settings.apply_perf_mode(m)
                self.render_w.setValue(self.settings.render.width)
                self.render_h.setValue(self.settings.render.height)
                self.render_fps.setCurrentText(str(self.settings.render.fps))
                self.render_preset.setCurrentText(self.settings.render.ffmpeg_preset)
                self.render_crf.setValue(self.settings.render.crf)
                self.spec_bars.setValue(self.settings.spectrum.bar_count)
                self.spec_glow.setChecked(self.settings.spectrum.glow)
                self.spec_refl.setChecked(self.settings.spectrum.reflection)
                log.info("Mode performa: %s", m.value)
                return

    def _on_bg_changed(self) -> None:
        kind = self.bg_combo.currentData()
        self.settings.background.kind = kind
        log.info("Background type: %s", kind.value)

    def _on_bg_color(self, color: tuple[int, int, int]) -> None:
        self.settings.background.solid_color = color

    def _on_spec_changed(self) -> None:
        s = self.spec_style.currentData()
        self.settings.spectrum.style = s
        log.info("Spectrum style: %s", s.value)

    def _on_lyric_mode(self) -> None:
        self.settings.lyrics.mode = self.lyric_mode.currentData()
        log.info("Lyric mode: %s", self.settings.lyrics.mode.value)

    def _on_cta_timing(self) -> None:
        timing = self.cta_timing.currentData()
        self.settings.cta.timing = timing
        self.cta_custom.setEnabled(timing == CTATiming.CUSTOM)

    # ------------------------------------------------------------------
    # FFmpeg
    # ------------------------------------------------------------------
    def _refresh_ffmpeg_status(self) -> None:
        version = ffmpeg_manager.get_version()
        if version:
            self.ffmpeg_status.setText(f"OK · {version}")
            self.ffmpeg_status.setStyleSheet("color: #6cc36c;")
            self.btn_install_ffmpeg.setText("Re-check FFmpeg")
            self.btn_install_ffmpeg.clicked.disconnect()
            self.btn_install_ffmpeg.clicked.connect(self._refresh_ffmpeg_status)
        else:
            self.ffmpeg_status.setText("FFmpeg belum terinstall")
            self.ffmpeg_status.setStyleSheet("color: #e06c75;")

    def _install_ffmpeg(self) -> None:
        self.statusBar().showMessage("Menginstall FFmpeg via imageio-ffmpeg...", 3000)
        ok = ffmpeg_manager.install_online()
        QMessageBox.information(self, "FFmpeg",
                                "FFmpeg berhasil dipasang." if ok else
                                "Gagal install FFmpeg. Silakan install manual.")
        self._refresh_ffmpeg_status()

    # ------------------------------------------------------------------
    # Lyrics generation
    # ------------------------------------------------------------------
    def _generate_lyrics(self) -> None:
        if not self.settings.audio_path:
            QMessageBox.warning(self, "Lyrics", "Pilih file musik terlebih dulu.")
            return
        if self._lyrics_thread is not None:
            return
        thread = QThread(self)
        worker = _LyricsWorker(self.settings.audio_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.status.connect(lambda msg: self.statusBar().showMessage(msg, 5000))
        worker.finished.connect(self._on_lyrics_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._lyrics_thread_done)
        self._lyrics_thread = thread
        thread.start()
        self.btn_lyrics.setEnabled(False)
        self.lyric_status.setText("Generating lyrics...")

    def _lyrics_thread_done(self) -> None:
        self._lyrics_thread = None
        self.btn_lyrics.setEnabled(True)

    @Slot(object)
    def _on_lyrics_finished(self, track) -> None:
        if not track or not getattr(track, "lines", None):
            self.lyric_status.setText("Tidak berhasil. Install whisper / whisperx.")
            QMessageBox.warning(
                self, "Lyrics",
                "Tidak ada backend Whisper yang tersedia.\n"
                "Install salah satu:\n"
                "  pip install openai-whisper\n"
                "  pip install whisperx\n"
                "atau muat file .lrc / .srt secara manual.")
            return
        self.lyrics_track = track
        self.lyric_status.setText(
            f"Loaded {len(track.lines)} lines (source={track.source}).")

    def _load_lyrics_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load lyrics", "",
            "Lyric files (*.lrc *.srt);;All Files (*)")
        if not path:
            return
        try:
            track = lyric_generator.load_manual(path)
        except Exception as exc:
            QMessageBox.critical(self, "Lyrics", f"Gagal memuat: {exc}")
            return
        self.lyrics_track = track
        self.lyric_status.setText(f"Loaded {len(track.lines)} lines from file.")

    # ------------------------------------------------------------------
    # Render / preview
    # ------------------------------------------------------------------
    def _validate_render(self) -> bool:
        if not self.settings.audio_path:
            QMessageBox.warning(self, "Render", "Pilih file musik dulu.")
            return False
        if not ffmpeg_manager.find_ffmpeg():
            QMessageBox.warning(self, "Render",
                                "FFmpeg belum tersedia. Klik 'Install FFmpeg Online'.")
            return False
        return True

    def _output_path(self, suffix: str = "") -> str:
        out_dir = self.render_outdir.text() or self.settings.output_dir
        os.makedirs(out_dir, exist_ok=True)
        stem = Path(self.settings.audio_path).stem
        return os.path.join(out_dir, f"{stem}{suffix}.mp4")

    def _do_preview(self) -> None:
        if not self._validate_render():
            return
        out = os.path.join(self.settings.output_dir, "_preview.mp4")
        self._start_render(out, max_seconds=float(self.preview_seconds.value()),
                           is_preview=True)

    def _do_render(self) -> None:
        if not self._validate_render():
            return
        out = self._output_path()
        if os.path.exists(out):
            ans = QMessageBox.question(
                self, "Overwrite?",
                f"{os.path.basename(out)} sudah ada. Timpa?")
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._start_render(out, max_seconds=None, is_preview=False)

    def _start_render(self, out: str, max_seconds: Optional[float],
                      is_preview: bool) -> None:
        if self._render_thread is not None:
            QMessageBox.information(self, "Render", "Render sedang berjalan.")
            return
        renderer = VideoRenderer(self.settings,
                                 spectrum_data=self.spectrum_data,
                                 lyrics=self.lyrics_track)
        self._render_renderer = renderer

        thread = QThread(self)
        worker = _RenderWorker(renderer, out, max_seconds=max_seconds)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_render_progress)
        worker.status.connect(lambda msg: self.statusBar().showMessage(msg, 4000))
        worker.finished.connect(lambda res: self._on_render_finished(res, is_preview))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._render_thread_done)
        self._render_thread = thread
        self._render_worker = worker

        self.btn_render.setEnabled(False)
        self.btn_preview.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(0)
        thread.start()

    def _render_thread_done(self) -> None:
        self._render_thread = None
        self._render_worker = None
        self._render_renderer = None
        self.btn_render.setEnabled(True)
        self.btn_preview.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def _cancel_render(self) -> None:
        if self._render_renderer is not None:
            log.info("User cancelled render.")
            self._render_renderer.cancel()

    @Slot(int, int)
    def _on_render_progress(self, current: int, total: int) -> None:
        if total <= 0:
            return
        pct = int(round(current * 100 / total))
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"Rendering: {pct}%  ({current}/{total})")

    @Slot(object, bool)
    def _on_render_finished(self, result, is_preview: bool) -> None:
        if result.cancelled:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Render dibatalkan")
            return
        if result.error:
            self.progress_bar.setFormat(f"Error: {result.error}")
            QMessageBox.critical(self, "Render", f"Render gagal:\n{result.error}")
            return
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat(("Preview siap" if is_preview else "Render selesai")
                                    + f": {result.output_path}")
        if is_preview:
            self.media_player.setSource(QUrl.fromLocalFile(result.output_path))
            self.media_player.play()
        else:
            QMessageBox.information(self, "Render",
                                    f"Render selesai!\n{result.output_path}")

    def _toggle_play(self) -> None:
        from PySide6.QtMultimedia import QMediaPlayer as MP
        state = self.media_player.playbackState()
        if state == MP.PlaybackState.PlayingState:
            self.media_player.pause()
            self.btn_play.setText("Play")
        else:
            self.media_player.play()
            self.btn_play.setText("Pause")

    # ------------------------------------------------------------------
    # Window close
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        if self._render_renderer is not None:
            self._render_renderer.cancel()
        return super().closeEvent(event)


# ---------------------------------------------------------------------------
# Dark palette
# ---------------------------------------------------------------------------
def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    bg = QColor(28, 30, 38)
    base = QColor(36, 38, 48)
    alt = QColor(45, 47, 58)
    text = QColor(230, 230, 235)
    accent = QColor(255, 110, 196)
    palette.setColor(QPalette.ColorRole.Window, bg)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, alt)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, base)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, accent)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.ToolTipBase, alt)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    app.setPalette(palette)
    app.setStyleSheet("""
        QGroupBox {
            border: 1px solid #444; border-radius: 6px;
            margin-top: 14px; padding: 10px 8px 8px 8px;
        }
        QGroupBox::title { subcontrol-origin: margin; left: 10px;
            padding: 0 6px; color: #f0a8ff; }
        QPushButton { padding: 6px 12px; border-radius: 6px; background: #353748; }
        QPushButton:hover { background: #45485f; }
        QPushButton:pressed { background: #2a2c39; }
        QPushButton:disabled { color: #777; background: #2a2c39; }
        QTabBar::tab { padding: 8px 14px; }
        QTabBar::tab:selected { background: #353748; }
        QProgressBar { border: 1px solid #444; border-radius: 6px; text-align: center; }
        QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #ff6ec4, stop:1 #7873f5); border-radius: 5px; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
            background: #2c2e3a; border: 1px solid #444; border-radius: 4px;
            padding: 4px 6px;
        }
        QPlainTextEdit { font-family: Consolas, monospace; }
    """)
