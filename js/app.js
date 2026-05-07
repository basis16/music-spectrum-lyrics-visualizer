// Main entry — wires DOM ↔ AudioEngine, Visualizer, Lyrics, Background, Logo, Exporter, Transcribe.

import { $, $$, formatTime, toast, QUALITY_PRESETS } from './utils.js';
import { AudioEngine } from './audio.js';
import { Visualizer } from './visualizers.js';
import { LyricsRenderer, parseLRC, serializeLRC } from './lyrics.js';
import { Background } from './background.js';
import { Logo } from './logo.js';
import { Exporter } from './exporter.js';
import { transcribe, abortTranscription, linesToLRC } from './transcribe.js';

const SAMPLE_LRC = `[ti:Spectrum Demo]
[ar:Music Visualizer]
[00:00.00] ♪ Selamat datang di Spectrum Visualizer ♪
[00:04.00] Upload lagu favoritmu untuk memulai
[00:08.00] Pilih mode visual: Bar, Circular, Waveform, atau Particle
[00:12.00] Tambahkan background gambar atau video
[00:16.00] Sinkronkan lirik LRC dengan musik
[00:20.00] Atau pakai Auto-Generate untuk transkripsi otomatis
[00:24.00] Pasang logo watermark di pojok layar
[00:28.00] Lalu rekam jadi video musik karaokemu sendiri
[00:32.00] Selamat berkarya! ✨`;

// ---------- DOM refs ----------
const audioEl = $('#audioEl');
const stage = $('#stage');
const canvas = $('#visualCanvas');
const lyricsLayer = $('#lyricsLayer');
const bgImage = $('#bgImage');
const bgVideo = $('#bgVideo');
const bgOverlay = $('#bgOverlay');
const logoEl = $('#logoOverlay');
const stageHint = $('#stageHint');
const app = $('#app');

// Track latest user-uploaded audio file (for transcription reuse).
let currentAudioFile = null;

// ---------- Engines ----------
const audio = new AudioEngine(audioEl);
const visualizer = new Visualizer(canvas);
const lyrics = new LyricsRenderer(lyricsLayer);
const background = new Background(bgImage, bgVideo, bgOverlay);
const logo = new Logo(logoEl);
const exporter = new Exporter({
  stage,
  audioEngine: audio,
  getLyricsState: () => ({
    lines: lyrics.lines,
    idx: lyrics._lastIndex,
    posPct: parseFloat(getComputedStyle(lyricsLayer).getPropertyValue('--lyric-y')) || 62,
    fontPx: parseFloat(getComputedStyle(lyricsLayer).getPropertyValue('--lyric-size')) || 56,
    visible: lyrics.visible,
  }),
  getLogoState: () => ({
    img: logoEl,
    pos: logo._pos,
    size: logo._size,
    opacity: logo._opacity,
    glow: logo._glow,
  }),
  getBgState: () => ({
    mode: background._mode,
    source: background._mode === 'image' ? bgImage : (background._mode === 'video' ? bgVideo : null),
    filters: background._filters,
  }),
});

// ---------- Tabs ----------
$$('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const target = btn.dataset.tab;
    $$('.tab-pane').forEach(p => p.classList.toggle('active', p.dataset.pane === target));
  });
});

// ---------- Panel toggle ----------
$('#panelToggle').addEventListener('click', () => {
  if (window.innerWidth <= 900) app.classList.toggle('panel-open');
  else app.classList.toggle('panel-collapsed');
});
$('#panelClose').addEventListener('click', () => {
  if (window.innerWidth <= 900) app.classList.remove('panel-open');
  else app.classList.add('panel-collapsed');
});

// ---------- Audio file ----------
$('#audioInput').addEventListener('change', async (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  await audio.ensureContext();
  if (audioEl.src) URL.revokeObjectURL(audioEl.src);
  audioEl.src = URL.createObjectURL(file);
  currentAudioFile = file;
  $('#audioName').textContent = file.name;
  audioEl.load();
  stageHint?.classList.add('hidden');
  toast(`Audio dimuat: ${file.name}`);
});

$('#volumeSlider').addEventListener('input', e => {
  const v = parseFloat(e.target.value);
  audio.setVolume(v);
  $('#volumeBar').value = v;
});
$('#sensitivitySlider').addEventListener('input', e => visualizer.setSensitivity(parseFloat(e.target.value)));
$('#smoothingSlider').addEventListener('input', e => audio.setSmoothing(parseFloat(e.target.value)));

// ---------- Visual ----------
$$('.mode-btn').forEach(b => b.addEventListener('click', () => {
  $$('.mode-btn').forEach(x => x.classList.remove('active'));
  b.classList.add('active');
  visualizer.setMode(b.dataset.mode);
}));
$('#colorTheme').addEventListener('change', e => visualizer.setTheme(e.target.value));
$('#glowSlider').addEventListener('input', e => visualizer.setGlow(parseInt(e.target.value, 10)));
$('#qualitySelect').addEventListener('change', e => {
  const q = e.target.value;
  visualizer.setQuality(q);
  audio.setFftSize(QUALITY_PRESETS[q].fft);
});
visualizer.setQuality('medium');
audio.setFftSize(QUALITY_PRESETS.medium.fft);

// ---------- Background ----------
$('#bgImageInput').addEventListener('change', e => {
  const f = e.target.files?.[0]; if (!f) return;
  background.setImage(f); toast('Background gambar diterapkan');
});
$('#bgVideoInput').addEventListener('change', e => {
  const f = e.target.files?.[0]; if (!f) return;
  background.setVideo(f); toast('Background video diterapkan');
});
$('#bgClearBtn').addEventListener('click', () => { background.clear(); toast('Background dihapus'); });
$('#bgBlur').addEventListener('input', e => background.setFilter('blur', parseFloat(e.target.value)));
$('#bgBrightness').addEventListener('input', e => background.setFilter('brightness', parseFloat(e.target.value)));
$('#bgOpacity').addEventListener('input', e => background.setFilter('opacity', parseFloat(e.target.value)));
$('#bgDark').addEventListener('input', e => background.setFilter('dark', parseFloat(e.target.value)));

// ---------- Lyrics: file/manual ----------
$('#lrcInput').addEventListener('change', async (e) => {
  const f = e.target.files?.[0]; if (!f) return;
  const text = await f.text();
  $('#lrcEditor').value = text;
  lyrics.setLines(parseLRC(text));
  toast(`Lirik dimuat (${lyrics.lines.length} baris)`);
});

$('#lrcSampleBtn').addEventListener('click', () => {
  $('#lrcEditor').value = SAMPLE_LRC;
  lyrics.setLines(parseLRC(SAMPLE_LRC));
  toast('Contoh lirik dimuat');
});

$('#lrcApplyBtn').addEventListener('click', () => {
  const text = $('#lrcEditor').value;
  const parsed = parseLRC(text);
  if (!parsed.length) {
    const lns = text.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    const dur = audioEl.duration || 60;
    const step = lns.length > 1 ? dur / lns.length : 0;
    lyrics.setLines(lns.map((t, i) => ({ t: i * step, text: t })));
    toast('Tidak ada timestamp — lirik dibagi rata berdasarkan durasi');
  } else {
    lyrics.setLines(parsed);
    toast(`Lirik diterapkan (${parsed.length} baris)`);
  }
});

$('#lrcStampBtn').addEventListener('click', () => {
  const ta = $('#lrcEditor');
  const t = audioEl.currentTime || 0;
  const m = Math.floor(t / 60);
  const s = (t % 60).toFixed(2).padStart(5, '0');
  const stamp = `[${m.toString().padStart(2,'0')}:${s}] `;
  const start = ta.selectionStart;
  const before = ta.value.slice(0, start);
  const after = ta.value.slice(start);
  const lineStart = before.lastIndexOf('\n') + 1;
  ta.value = before.slice(0, lineStart) + stamp + before.slice(lineStart) + after;
  const newPos = lineStart + stamp.length;
  ta.focus();
  ta.setSelectionRange(newPos, newPos);
});

$('#lrcDownloadBtn').addEventListener('click', () => {
  const text = $('#lrcEditor').value || serializeLRC(lyrics.lines);
  const blob = new Blob([text], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'lyrics.lrc';
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

$('#lrcClearBtn').addEventListener('click', () => {
  $('#lrcEditor').value = '';
  lyrics.setLines([]);
  toast('Lirik dibersihkan');
});

$('#lyricY').addEventListener('input', e => lyrics.setPositionPct(parseFloat(e.target.value)));
$('#lyricSize').addEventListener('input', e => lyrics.setFontSize(parseFloat(e.target.value)));
$('#lyricVisible').addEventListener('change', e => lyrics.setVisible(e.target.checked));

// ---------- Lyrics: AUTO-GENERATE (Whisper) ----------
const autoBtn = $('#autoLyricBtn');
const autoCancel = $('#autoLyricCancelBtn');
const autoBar = $('#autoLyricProgress');
const autoStatus = $('#autoLyricStatus');
const autoWrap = $('#autoLyricProgressWrap');
let isTranscribing = false;

function setAutoProgress(pct, message) {
  autoWrap.hidden = false;
  if (typeof pct === 'number') autoBar.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  if (message) autoStatus.textContent = message;
}

autoBtn.addEventListener('click', async () => {
  if (isTranscribing) return;
  if (!currentAudioFile) {
    toast('Upload audio terlebih dulu di tab Audio.');
    return;
  }
  isTranscribing = true;
  autoBtn.disabled = true;
  autoCancel.disabled = false;
  setAutoProgress(0, 'Bersiap…');
  toast('Memulai auto-generate lirik. Pertama kali mungkin lama (download model).', 4000);

  try {
    const language = $('#autoLyricLang').value;
    const model = $('#autoLyricModel').value;
    const result = await transcribe(currentAudioFile, {
      model,
      language,
      onProgress: ({ stage, message, progress }) => {
        // Map stages to a global 0-100 bar.
        let pct = 0;
        if (stage === 'load')        pct = 0 + (progress || 0) * 0.55;
        else if (stage === 'decode') pct = 60;
        else if (stage === 'transcribe') pct = 65 + (progress || 0) * 0.30;
        else if (stage === 'done')   pct = 100;
        setAutoProgress(pct, message);
      },
    });

    if (!result.lines.length) {
      setAutoProgress(100, 'Selesai — tidak ada vokal terdeteksi.');
      toast('Tidak ada vokal/teks yang terdeteksi di audio.');
      return;
    }
    const lrcText = linesToLRC(result.lines);
    $('#lrcEditor').value = lrcText;
    lyrics.setLines(result.lines);
    setAutoProgress(100, `Selesai: ${result.lines.length} baris diterapkan.`);
    toast(`Lirik otomatis diterapkan (${result.lines.length} baris).`);
  } catch (err) {
    console.error(err);
    if (String(err?.message || err).includes('Dibatalkan')) {
      setAutoProgress(0, 'Dibatalkan.');
      toast('Auto-generate dibatalkan.');
    } else {
      setAutoProgress(0, 'Gagal: ' + (err?.message || err));
      toast('Auto-generate gagal: ' + (err?.message || err));
    }
  } finally {
    isTranscribing = false;
    autoBtn.disabled = false;
    autoCancel.disabled = true;
  }
});

autoCancel.addEventListener('click', () => {
  if (!isTranscribing) return;
  abortTranscription();
  setAutoProgress(0, 'Membatalkan…');
});

// ---------- Logo ----------
$('#logoInput').addEventListener('change', e => {
  const f = e.target.files?.[0]; if (!f) return;
  logo.setImage(f); toast('Logo diterapkan');
});
$('#logoClearBtn').addEventListener('click', () => { logo.clear(); toast('Logo dihapus'); });
$('#logoPos').addEventListener('change', e => logo.setPosition(e.target.value));
$('#logoSize').addEventListener('input', e => logo.setSize(parseFloat(e.target.value)));
$('#logoOpacity').addEventListener('input', e => logo.setOpacity(parseFloat(e.target.value)));
$('#logoGlow').addEventListener('input', e => logo.setGlow(parseFloat(e.target.value)));

// ---------- Player ----------
$('#btnPlay').addEventListener('click', async () => {
  if (!audioEl.src) { toast('Upload audio terlebih dulu.'); return; }
  await audio.ensureContext();
  audioEl.play().catch(err => toast('Gagal memutar audio: ' + err.message));
  background.syncToAudio(audioEl);
});
$('#btnPause').addEventListener('click', () => { audioEl.pause(); background.syncToAudio(audioEl); });
$('#btnStop').addEventListener('click', () => {
  audioEl.pause(); audioEl.currentTime = 0;
  background.syncToAudio(audioEl);
});

const progress = $('#progressBar');
let scrubbing = false;
progress.addEventListener('input', () => { scrubbing = true; });
progress.addEventListener('change', () => {
  if (!isFinite(audioEl.duration)) { scrubbing = false; return; }
  audioEl.currentTime = (parseFloat(progress.value) / 1000) * audioEl.duration;
  background.syncToAudio(audioEl);
  scrubbing = false;
});

$('#volumeBar').addEventListener('input', e => {
  const v = parseFloat(e.target.value);
  audio.setVolume(v);
  $('#volumeSlider').value = v;
});

$('#btnFullscreen').addEventListener('click', () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else stage.requestFullscreen?.();
});

audioEl.addEventListener('loadedmetadata', () => {
  $('#timeTotal').textContent = formatTime(audioEl.duration);
});
audioEl.addEventListener('ended', () => background.syncToAudio(audioEl));

// ---------- Export ----------
const exportStart = $('#exportStartBtn');
const exportStop = $('#exportStopBtn');
const exportStatus = $('#exportStatus');
const recIndicator = $('#recIndicator');

if (!Exporter.isSupported()) {
  exportStart.disabled = true;
  exportStatus.textContent = 'Browser ini tidak mendukung export video (MediaRecorder atau canvas.captureStream tidak tersedia).';
}

exportStart.addEventListener('click', async () => {
  const fmt = $('#exportFormat').value;
  const ok = await exporter.start(fmt);
  if (!ok) return;
  exportStart.disabled = true;
  exportStop.disabled = false;
  recIndicator.hidden = false;
  exportStatus.textContent = 'Merekam… mainkan audio jika belum.';
  toast('Mulai merekam video');
});
exportStop.addEventListener('click', () => {
  exporter.stop();
  exportStart.disabled = false;
  exportStop.disabled = true;
  recIndicator.hidden = true;
  exportStatus.textContent = 'Selesai. File akan otomatis terunduh.';
  toast('Stop & menyimpan video…');
});

// ---------- Render loop ----------
function frame() {
  const data = audio.update();
  const energy = audio.energy();
  visualizer.draw(data, energy);
  lyrics.update(audioEl.currentTime || 0);

  if (!scrubbing && isFinite(audioEl.duration) && audioEl.duration > 0) {
    progress.value = ((audioEl.currentTime || 0) / audioEl.duration) * 1000;
    $('#timeCurrent').textContent = formatTime(audioEl.currentTime);
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// ---------- Keyboard shortcuts ----------
document.addEventListener('keydown', (e) => {
  if (e.target.matches('input, textarea, select')) return;
  switch (e.code) {
    case 'Space':
      e.preventDefault();
      audioEl.paused ? $('#btnPlay').click() : $('#btnPause').click();
      break;
    case 'KeyF':
      $('#btnFullscreen').click();
      break;
    case 'KeyT':
      $('#lrcStampBtn').click();
      break;
  }
});

// ---------- Boot ----------
toast('Selamat datang! Upload audio untuk memulai. Lirik bisa otomatis (tab Lirik).', 3500);
