# Music Spectrum Lyrics Visualizer

Aplikasi web statis untuk membuat video musik visualizer dengan **spectrum analyzer warna-warni**, **background gambar/video**, **lirik LRC otomatis**, dan **logo watermark**.

Dibangun murni dengan HTML + CSS + Vanilla JS (ES Modules), tanpa build step. Cukup buka `index.html` lewat web server statis (atau deploy ke hosting statis manapun).

## Fitur

- **Layout split**: preview (stage) di kiri terpisah dari panel **Settings** di kanan — tidak overlay. Mobile otomatis jadi panel slide-in.
- **Audio**: upload MP3 / WAV, kontrol volume, sensitivitas, smoothing.
- **Spectrum analyzer real-time** dengan 4 mode:
  - Bar Spectrum (dengan refleksi mirror)
  - Circular Spectrum
  - Waveform
  - Particle Beat (partikel meledak saat ada beat)
- 6 tema warna neon (Rainbow, Aurora, Sunset, Cyberpunk, Ocean, Mono).
- Slider **glow**, **kualitas** (Low / Medium / High).
- **Background**: upload gambar atau video, kontrol blur, brightness, opacity, dark overlay.
- **Lirik LRC**:
  - **Auto-Generate** dari audio menggunakan AI Whisper (berjalan langsung di browser via [@xenova/transformers](https://www.npmjs.com/package/@xenova/transformers)). Pilih bahasa + model Tiny/Base. Model di-download sekali (~75–145 MB) lalu di-cache browser. Hasil otomatis jadi LRC bertimestamp.
  - Upload `.lrc` (parser `[mm:ss.xx]` + ekstensi multi-stamp).
  - Editor manual dengan tombol **Stamp** (atau tekan `T`) untuk timing real-time.
  - Tampil active + prev + next dengan glow + fade animation.
  - Slider posisi vertikal + ukuran font.
  - Unduh `.lrc`.
- **Logo watermark**: upload PNG transparan, 5 posisi preset, slider ukuran/opacity/glow neon.
- **Player**: Play, Pause, Stop, progress bar, volume, fullscreen.
- **Export video** dengan `MediaRecorder` (canvas + audio gabungan). Mendukung WebM (VP9/VP8) dan MP4 jika browser mendukung. Hasil export sudah termasuk background, spectrum, lirik, dan logo.
- UI **dark futuristic glassmorphism** dengan animated gradient & responsive untuk mobile.

## Cara pakai

1. Buka aplikasi.
2. Tab **Audio** → upload MP3/WAV.
3. Tab **BG** → upload gambar atau video (opsional).
4. Tab **Lirik** → tiga pilihan:
   - **Auto-Generate**: pilih bahasa + model, klik **Generate dari musik**. Tunggu model di-download (sekali saja) lalu transkripsi berjalan otomatis.
   - **Upload `.lrc`**.
   - **Editor manual** + tombol Stamp (`T`).
5. Tab **Logo** → upload PNG (opsional).
6. Tekan ▶ untuk memulai. Tekan ⛶ untuk fullscreen.
7. Tab **Export** → klik **Mulai Rekam**, lalu **Stop & Simpan** untuk mengunduh video.

### Format LRC

```
[ti:Title]
[ar:Artist]
[00:12.50] Baris pertama
[00:16.00] Baris kedua
```

### Pintasan keyboard

- `Space` — Play/Pause
- `F` — Fullscreen toggle
- `T` — Stamp timestamp di editor lirik

## Menjalankan secara lokal

Karena aplikasi memakai ES Modules, butuh dijalankan via HTTP (bukan `file://`). Salah satu cara:

```bash
# Python 3
python3 -m http.server 8080

# atau Node (npx)
npx -y serve -l 8080 .
```

Lalu buka `http://localhost:8080`.

## Catatan browser

- Web Audio API + `MediaElementAudioSourceNode` ada di Chrome, Edge, Firefox, Safari modern.
- `MediaRecorder` + `canvas.captureStream()` paling stabil di Chrome/Edge. Safari mungkin tidak menyediakan codec yang dibutuhkan; jika tidak didukung, tombol export akan dinonaktifkan dan tampil notifikasi.
- File audio yang diputar via blob URL **tidak** memicu CORS (file lokal milik user).

## Struktur

```
index.html
css/styles.css
js/
  app.js          # entry point, glue
  audio.js        # AudioEngine (Web Audio analyser pipeline)
  visualizers.js  # 4 mode visual
  lyrics.js       # LRC parser + renderer
  background.js   # bg image/video + filters
  logo.js         # logo overlay
  exporter.js     # MediaRecorder export (composite canvas)
  transcribe.js   # Whisper auto-generate lyrics (lazy import dari CDN)
  utils.js        # helpers
```

## Catatan auto-generate lirik

- Pertama kali klik **Generate dari musik**, model Whisper akan di-download dari Hugging Face (~75 MB untuk Tiny, ~145 MB untuk Base) dan dicache di browser. Selanjutnya jauh lebih cepat.
- Whisper berjalan **sepenuhnya di browser** — audio Anda tidak dikirim ke server manapun.
- Untuk hasil terbaik gunakan audio dengan vokal yang jelas. Lagu dengan musik instrumental dominan mungkin tidak menghasilkan banyak teks.
- Mendukung banyak bahasa (Indonesia, English, Malay, Japanese, Korean, Chinese, Spanish, French, German, Arabic, dll). Pilih `Auto-detect` jika ragu.

## Lisensi

MIT — bebas dipakai dan dimodifikasi.
