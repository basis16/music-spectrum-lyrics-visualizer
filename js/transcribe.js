// In-browser speech-to-text using Whisper via @xenova/transformers (loaded from CDN on demand).
// Decodes the user's audio file, runs Whisper, and returns LRC-ready chunks
// like [{ t: 0.0, text: "..." }, { t: 5.2, text: "..." }, ...].

const TRANSFORMERS_CDN = 'https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2';

let _transformers = null;
let _pipelineCache = new Map();      // model -> pipeline instance
let _loadingPromise = null;
let _aborted = false;

async function loadTransformers() {
  if (_transformers) return _transformers;
  if (!_loadingPromise) {
    _loadingPromise = import(/* @vite-ignore */ TRANSFORMERS_CDN).then(mod => {
      _transformers = mod;
      // Use only remote model files; never look in localhost.
      mod.env.allowLocalModels = false;
      mod.env.useBrowserCache = true;
      return mod;
    });
  }
  return _loadingPromise;
}

// Reset abort flag.
export function abortTranscription() { _aborted = true; }

/**
 * Transcribe an audio File or Blob using Whisper.
 * @param {File|Blob} file
 * @param {Object} opts
 * @param {string} [opts.model='Xenova/whisper-tiny']
 * @param {string|null} [opts.language='auto'] — 'indonesian' | 'english' | … or 'auto'
 * @param {(p: {stage:string, message:string, progress?:number})=>void} [opts.onProgress]
 * @returns {Promise<{text:string, chunks:Array<{timestamp:[number,number], text:string}>, lines:Array<{t:number,text:string}>}>}
 */
export async function transcribe(file, opts = {}) {
  const {
    model = 'Xenova/whisper-tiny',
    language = 'auto',
    onProgress = () => {},
  } = opts;
  _aborted = false;

  onProgress({ stage: 'load', message: 'Memuat library AI…', progress: 0 });
  const T = await loadTransformers();
  if (_aborted) throw new Error('Dibatalkan');

  // Pipeline cache per model (so switching languages doesn't re-download).
  let asrPipeline = _pipelineCache.get(model);
  if (!asrPipeline) {
    onProgress({ stage: 'load', message: `Mengunduh model ${model.split('/').pop()}…`, progress: 1 });
    asrPipeline = await T.pipeline('automatic-speech-recognition', model, {
      progress_callback: (p) => {
        if (_aborted) return;
        if (p.status === 'progress' && typeof p.progress === 'number') {
          onProgress({
            stage: 'load',
            message: `Mengunduh ${p.file || 'model'}… ${Math.round(p.progress)}%`,
            progress: Math.max(1, p.progress),
          });
        } else if (p.status === 'done') {
          onProgress({ stage: 'load', message: 'Model siap.', progress: 100 });
        } else if (p.status === 'ready') {
          onProgress({ stage: 'load', message: 'Model dimuat ke memori.', progress: 100 });
        }
      },
    });
    _pipelineCache.set(model, asrPipeline);
  }
  if (_aborted) throw new Error('Dibatalkan');

  onProgress({ stage: 'decode', message: 'Mendekode audio…', progress: 0 });
  const audio = await fileToFloat32Mono16k(file);
  if (_aborted) throw new Error('Dibatalkan');

  onProgress({
    stage: 'transcribe',
    message: 'AI sedang mendengarkan audio… ini bisa memakan waktu beberapa menit.',
    progress: 0,
  });

  const opts2 = {
    return_timestamps: true,
    chunk_length_s: 30,
    stride_length_s: 5,
    task: 'transcribe',
  };
  if (language && language !== 'auto') opts2.language = language;

  const result = await asrPipeline(audio, opts2);
  if (_aborted) throw new Error('Dibatalkan');

  const chunks = Array.isArray(result?.chunks) ? result.chunks : [];
  const lines = chunksToLines(chunks);
  onProgress({ stage: 'done', message: `Selesai: ${lines.length} baris`, progress: 100 });
  return { text: result?.text || '', chunks, lines };
}

// Convert a File/Blob to a Float32Array mono @ 16kHz (Whisper's expected sample rate).
async function fileToFloat32Mono16k(file) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const tmp = new Ctx();
  const arr = await file.arrayBuffer();
  let buf;
  try {
    buf = await tmp.decodeAudioData(arr.slice(0));
  } finally {
    try { await tmp.close(); } catch (_) {}
  }
  const targetSR = 16000;
  // Mix to mono if needed.
  let monoBuffer = buf;
  if (buf.numberOfChannels > 1) {
    const mono = new Float32Array(buf.length);
    const channels = [];
    for (let c = 0; c < buf.numberOfChannels; c++) channels.push(buf.getChannelData(c));
    for (let i = 0; i < buf.length; i++) {
      let s = 0;
      for (let c = 0; c < channels.length; c++) s += channels[c][i];
      mono[i] = s / channels.length;
    }
    const offCtx = new (window.OfflineAudioContext || window.webkitOfflineAudioContext)(
      1, mono.length, buf.sampleRate
    );
    const ab = offCtx.createBuffer(1, mono.length, buf.sampleRate);
    ab.copyToChannel(mono, 0);
    monoBuffer = ab;
  }
  if (monoBuffer.sampleRate === targetSR && monoBuffer.numberOfChannels === 1) {
    return monoBuffer.getChannelData(0).slice();
  }
  // Resample using OfflineAudioContext.
  const offCtx = new (window.OfflineAudioContext || window.webkitOfflineAudioContext)(
    1, Math.ceil(monoBuffer.duration * targetSR), targetSR
  );
  const src = offCtx.createBufferSource();
  src.buffer = monoBuffer;
  src.connect(offCtx.destination);
  src.start(0);
  const rendered = await offCtx.startRendering();
  return rendered.getChannelData(0).slice();
}

function chunksToLines(chunks) {
  const out = [];
  for (const c of chunks) {
    const text = (c.text || '').trim();
    if (!text) continue;
    let t = 0;
    if (Array.isArray(c.timestamp) && typeof c.timestamp[0] === 'number') {
      t = c.timestamp[0];
    }
    out.push({ t, text });
  }
  // Drop near-duplicate consecutive lines (Whisper sometimes repeats).
  return dedupeAdjacent(out);
}

function dedupeAdjacent(lines) {
  const out = [];
  for (const l of lines) {
    const prev = out[out.length - 1];
    if (prev && prev.text === l.text && (l.t - prev.t) < 1.0) continue;
    out.push(l);
  }
  return out;
}

export function linesToLRC(lines) {
  return lines.map(l => {
    const m = Math.floor(l.t / 60);
    const s = (l.t % 60).toFixed(2).padStart(5, '0');
    return `[${m.toString().padStart(2, '0')}:${s}] ${l.text}`;
  }).join('\n');
}
