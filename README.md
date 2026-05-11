# Music Spectrum Lyric Video Maker

A lightweight, modern Windows desktop application for generating professional
music spectrum videos with automatic lyrics from song metadata. Designed for
low-spec laptops/PCs, with batch rendering, multiple spectrum styles,
backgrounds, logo overlays and FFmpeg-based hardware-accelerated encoding.

## Features at a Glance

- **Single & Batch render** with one click per song or per folder
- **10+ modern spectrum styles** (Modern Bars, Smooth Wave, Circular,
  Radial Pulse, Neon Equalizer, Minimal Line, Particle, Glow Waveform,
  Mirror Bars, Center Pulse)
- **Auto lyrics from metadata** (synced LRC/SYLT preferred, USLT/lyrics
  tags as fallback). Square/round brackets are cleaned, timestamps preserved.
- **Backgrounds**: image or video, per-song or per-folder. Modes:
  Sequence, Match-by-name, Random. Cover / Fit-blur / Stretch.
- **Logo overlay**: PNG/JPG/WEBP, circle mask, size, opacity, shadow,
  border, glow.
- **Lyrics styling**: Windows fonts, presets, color, stroke, shadow,
  alignment, smooth fade animation.
- **Preview** with play/pause/stop/seek and 10-second preview.
- **Render**: 720p / 1080p / 1440p / 4K / custom, 24/30/60 fps,
  Fast / Balanced / High Quality presets.
- **Hardware acceleration**: NVENC, QuickSync (QSV), AMF, CPU fallback.
  Auto-detects what's available.
- **FFmpeg integration**: detects FFmpeg, can download it from the
  trusted gyan.dev build, or use a manually chosen `ffmpeg.exe`.
- **Application log panel** with file logging.
- **Low-Spec Mode** for older machines.
- **Light theme** by default, auto-following Windows light/dark.

## Install

### Quick start (Windows)

1. Install Python 3.10 or newer from <https://www.python.org/downloads/>.
   When installing, tick **"Add Python to PATH"**.
2. Double-click `setup.bat`. This will:
   - Verify Python is on PATH
   - Create a `.venv` virtual environment
   - Install dependencies from `requirements.txt`
   - Check FFmpeg
3. Once setup finishes, double-click `run.bat` to launch the app.

If anything fails, `setup.bat` will pause so you can read the error.

### FFmpeg

The app can detect FFmpeg in three ways:

- on `PATH` (system-wide install)
- bundled at `app/assets/ffmpeg/ffmpeg.exe`
- a custom path you select in **Settings → FFmpeg location**

If FFmpeg is not detected, open **Settings** in the app and click
**Install FFmpeg Online**. The app will download the latest gyan.dev
"essentials" build and place `ffmpeg.exe` / `ffprobe.exe` under
`app/assets/ffmpeg/`. After install, FFmpeg is rechecked automatically.

You can also install FFmpeg yourself from
<https://www.gyan.dev/ffmpeg/builds/> and either add it to `PATH` or
point the app at it via Settings.

## Usage

### Single Render

1. Open **Single Render**.
2. Pick an audio file (MP3 / WAV / FLAC / M4A).
3. Pick a background image or video (optional).
4. Pick a logo (optional).
5. Pick a spectrum style and tweak color, smoothness, sensitivity, bars.
6. Pick lyric font/style/position.
7. Use the **Preview** panel to scrub through the timeline (the preview
   is intentionally low-quality so it's smooth on weak hardware).
8. Pick resolution / FPS / quality / encoder, then click **Render**.

### Batch Render

1. Open **Batch Render**.
2. Pick a **music folder** (recursive scan of supported files).
3. Optionally pick a **background folder** and a mode:
   - **Sequence** – use backgrounds in folder order
   - **Match by name** – use the background whose filename matches the
     song filename (basename match, ignoring extension)
   - **Random** – pick a random background per song
4. Pick an **output folder**.
5. Click **Start Batch**. Progress, ETA and errors appear in the queue
   and in the log panel.

If a song has no background match (in Match mode), the app falls back
to a generated background and warns in the log. If a song has no
lyrics, the song still renders — the lyric area stays empty.

### Background modes

- **Cover**: fill the frame and crop edges (no distortion).
- **Fit (blur)**: fit the background centered, fill the gaps with a
  blurred copy.
- **Stretch**: stretch to fill (may distort, opt-in).

### Performance / Low-Spec Mode

In **Settings**, enable **Low-Spec Mode** to:

- lower preview resolution and FPS
- disable heavy glow effects
- use the FFmpeg `veryfast` preset for render

The renderer always pipes raw frames into FFmpeg and never writes
intermediate PNGs to disk, so disk wear and temp usage stay low.

## Project Structure

```
music-spectrum-app/
├── app/
│   ├── main.py
│   ├── ui/
│   │   ├── main_window.py
│   │   ├── widgets/
│   │   │   ├── preview_widget.py
│   │   │   ├── single_render_page.py
│   │   │   ├── batch_render_page.py
│   │   │   ├── settings_page.py
│   │   │   └── log_panel.py
│   │   └── themes/
│   │       ├── light.qss
│   │       └── dark.qss
│   ├── core/
│   │   ├── audio_analyzer.py
│   │   ├── lyrics_extractor.py
│   │   ├── lyrics_cleaner.py
│   │   ├── spectrum_styles.py
│   │   ├── renderer.py
│   │   ├── ffmpeg_manager.py
│   │   ├── batch_manager.py
│   │   └── settings_manager.py
│   ├── assets/
│   │   ├── icons/
│   │   ├── fonts/
│   │   └── default_backgrounds/
│   └── utils/
│       ├── logger.py
│       └── file_utils.py
├── output/
├── logs/
├── requirements.txt
├── setup.bat
├── run.bat
└── README.md
```

Every major feature is its own module so it can be extended without
touching the rest of the app.

## Troubleshooting

| Problem | Fix |
|---|---|
| `setup.bat` says Python not found | Reinstall Python 3.10+ and tick "Add Python to PATH". |
| `pip install` fails on PySide6 | Make sure Python is 64-bit and ≥ 3.10. |
| App says FFmpeg not detected | Click **Settings → Install FFmpeg Online**, or set a custom path. |
| Render is very slow | In **Settings**, choose a hardware encoder (NVENC / QSV / AMF) and the **Fast** quality preset. |
| Lyrics don't appear | The song probably has no synced lyrics. You can add `.lrc` next to the audio file with the same filename, and the app will pick it up. |
| Lyrics show before the song starts | The app refuses to invent timestamps. If only unsynced lyrics are present, they're treated as a static block from the first available timestamp; otherwise nothing is shown. |
| Preview stutters | Enable **Low-Spec Mode** in Settings. |
| Background looks distorted | Switch background mode from **Stretch** to **Cover** or **Fit (blur)**. |

## Notes

- Audio for the final render is taken from the original file via FFmpeg,
  so quality is not re-encoded unnecessarily.
- Spectrum computation is cached per audio file by content hash and FPS
  in `.cache/`, so re-rendering with different visual settings is fast.
- Temporary files are cleaned on render completion (success or failure).

## License

MIT.
