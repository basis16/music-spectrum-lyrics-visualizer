# Music Spectrum Lyrics Visualizer

Aplikasi Python desktop untuk membuat **video musik dengan audio spectrum reaktif, lirik otomatis (karaoke style), logo branding, dan animasi CTA** — dengan preview real-time, rendering FFmpeg modern, dan mode khusus untuk PC kentang / low spec.

> Dibangun dengan PySide6, librosa, OpenCV, Pillow, FFmpeg, dan (opsional) Whisper / WhisperX.

---

## Fitur utama

- 🎵 **Input audio**: MP3, WAV, M4A, FLAC. Nama output otomatis sama dengan nama file musik.
- 🖼️ **Background**: gambar (auto-fit ke durasi musik) atau video (auto-loop / trim sesuai durasi). Bisa juga warna solid.
- 📊 **Spectrum modern, smooth, reaktif**:
  - Style: Bar / Circular / Waveform / Neon / Modern Visualizer / Smooth Reactive
  - Reaktif terhadap **bass, treble, beat**, time-smoothing untuk visual yang halus, tidak kaku
  - Preset: Neon Rainbow, Cyberpunk, Ocean Blue, Sunset Glow, Fire Beat, Purple Night, Minimal Clean, Colorful Pop
  - Knob: bar count, sensitivity, bass boost, treble boost, smoothing, glow, reflection, rainbow, rounded
  - **Bar Spectrum khusus**: selalu di bagian paling bawah video, lirik selalu berada **di atas** bar spectrum
- 🎤 **Lirik otomatis & karaoke**:
  - Auto-generate dengan Whisper/WhisperX (opsional, install terpisah — fallback ke `.lrc`/`.srt`)
  - Mode: Normal · Karaoke Line · Karaoke Word · Karaoke Smooth Sweep
  - Estimasi timestamp per kata bila hanya tersedia per baris
  - Font, ukuran, warna normal/highlight, outline, shadow, glow, opacity, posisi vertikal
- 🔖 **Logo / watermark**: PNG transparan / JPG, 5 posisi, 5 animasi (Fade In/Out, Pulse, Zoom, None), opacity & margin
- 📣 **Animasi CTA**: Subscribe Pop Up · Like and Subscribe · Bell Notification · Smooth Slide In · Bounce · Minimal · YouTube Style — timing Start / Middle / End / Custom
- ⚙️ **Mode performa**: **Low Spec** / Balanced / **High Quality** dengan auto-detect spek (CPU/RAM/disk/GPU)
- 🛠️ **Render FFmpeg langsung via pipe** (tidak pakai MoviePy berat) → progress 0–100% **real**, bukan fake loading
- 🔍 **Preview 5–30 detik** sebelum render penuh
- 📜 **Panel log realtime** + Clear Log + Cancel Render yang aman
- 🌑 UI dark mode profesional, tidak freeze saat render (semua heavy work di QThread)

---

## Quickstart (Windows)

```cmd
:: clone & masuk folder
git clone https://github.com/basis16/music-spectrum-lyrics-visualizer.git
cd music-spectrum-lyrics-visualizer

:: setup otomatis (cek Python, buat venv, install deps, cek FFmpeg)
setup.bat

:: jalankan
run.bat
```

`setup.bat` akan menanyakan apakah ingin meng-install:
- **Whisper** untuk fitur lirik otomatis
- **FFmpeg** via `winget install Gyan.FFmpeg` (jika winget tersedia)

Jika `winget` tidak ada, jalankan saja aplikasinya — lalu klik tombol **Install FFmpeg Online** di header. Itu akan memasang `imageio-ffmpeg` (sebuah binary FFmpeg portable) ke dalam venv tanpa perlu hak admin.

---

## Quickstart (Linux / macOS)

```bash
git clone https://github.com/basis16/music-spectrum-lyrics-visualizer.git
cd music-spectrum-lyrics-visualizer
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# (opsional) lirik otomatis
pip install openai-whisper
# atau yang lebih akurat (word-level forced alignment):
pip install whisperx

# pastikan ffmpeg terpasang
sudo apt install ffmpeg     # Debian/Ubuntu
brew install ffmpeg         # macOS

python main.py
```

---

## Alur penggunaan

1. **Pilih file musik** di header (MP3 / WAV / M4A / FLAC).
2. Aplikasi otomatis cek **FFmpeg** dan menampilkan status. Jika belum ada, klik *Install FFmpeg Online*.
3. Aplikasi otomatis mendeteksi **spek hardware** dan memilih mode performa (Low / Balanced / High).
4. Di tab **Background**, pilih gambar / video / warna solid.
5. Di tab **Spectrum**, pilih style + preset + atur knob.
6. Di tab **Lyrics**, klik **Auto-generate (Whisper)** atau **Load .lrc/.srt**. Pilih mode (Normal / Karaoke Line / Word / Sweep).
7. Di tab **Logo**, aktifkan + pilih file + posisi + animasi.
8. Di tab **CTA**, aktifkan + atur teks + timing + animasi.
9. Di tab **Render**, atur resolusi / fps / preset / CRF / output dir.
10. Klik **Generate Preview** untuk render 5–30 detik. Lihat hasilnya di pemutar built-in.
11. Klik **Start Render** untuk render full. Progress bar realtime + log live. Bisa **Cancel Render** kapan saja.
12. Output `.mp4` otomatis disimpan di `output/<nama-musik>.mp4`.

---

## Struktur project

```
music-spectrum-lyrics-visualizer/
├── main.py                  # entry point
├── ui.py                    # PySide6 GUI (dark mode, tabs, log panel)
├── audio_analyzer.py        # librosa STFT -> per-frame spectrum + beat envelope
├── lyric_generator.py       # Whisper / WhisperX + .lrc / .srt loader
├── karaoke_manager.py       # render lirik (Normal / Line / Word / Sweep)
├── video_renderer.py        # frame loop + spectrum drawing + FFmpeg pipe
├── ffmpeg_manager.py        # detect / install FFmpeg + ffprobe helpers
├── logger_manager.py        # logging + Qt signal log bus
├── logo_manager.py          # logo overlay + animasi
├── cta_manager.py           # CTA overlay + 7 animasi preset
├── performance_manager.py   # auto-detect spek + rekomendasi mode
├── settings.py              # dataclass + preset + enum config
├── requirements.txt
├── setup.bat                # Windows: cek Python + venv + deps + FFmpeg
├── run.bat                  # Windows: aktifkan venv + run main.py
├── assets/                  # font/logo/dll opsional milik user
├── output/                  # MP4 hasil render
└── temp/                    # cache analysis, log file, dll
```

---

## Tips Low Spec

Aplikasi otomatis mendeteksi RAM/CPU dan akan menyarankan mode **Low Spec** jika perangkat di bawah ~6 GB RAM atau <4 core. Mode Low Spec:

- Render default **720p / 24 fps**
- Preset FFmpeg `ultrafast`
- Bar count dikurangi (40)
- Glow & reflection dimatikan
- Animasi tetap smooth tapi ringan
- Preview maksimal **10 detik** disarankan (dapat diubah 5–30 dt)

---

## Catatan teknis

- **Render menggunakan pipe FFmpeg langsung** (`-f rawvideo` → `libx264`). Ini lebih cepat, lebih stabil, dan memberikan **progress callback yang nyata** karena kita yang mengontrol berapa frame yang dikirim.
- **Audio analysis dipre-compute sekali** lalu di-index per frame video — ini yang menjaga loop render tetap responsif.
- Lirik karaoke menggunakan **forced alignment WhisperX** kalau tersedia (word-level). Jika hanya plain Whisper, fallback ke word_timestamps. Jika hanya per baris, durasi kata diestimasi proporsional dengan panjang kata.
- Cancel render aman: kirim sinyal ke FFmpeg, output parsial dihapus, log tampilkan "Render dibatalkan".

---

## Lisensi

Repo ini menggunakan lisensi default GitHub (lihat README upstream). Komponen pihak ketiga seperti FFmpeg, Whisper, dll mengikuti lisensinya masing-masing.
