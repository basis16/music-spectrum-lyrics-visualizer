// Record the visible stage (canvas + bg + lyrics + logo) into a downloadable video.
// Strategy:
//   - We composite EVERYTHING into an offscreen canvas at recording time, so
//     MediaRecorder gets a single source that already has the background, the
//     spectrum canvas, the lyrics text, and the logo baked in.
//   - We mix the audio MediaStream from AudioEngine with the canvas video stream.

import { toast } from './utils.js';

export class Exporter {
  constructor({ stage, audioEngine, getLyricsState, getLogoState, getBgState }) {
    this.stage = stage;
    this.audioEngine = audioEngine;
    this.getLyricsState = getLyricsState; // () => { lines, idx, posPct, fontPx, visible }
    this.getLogoState = getLogoState;     // () => { img, pos, size, opacity }
    this.getBgState = getBgState;         // () => { mode, source, filters }
    this.recorder = null;
    this.chunks = [];
    this._raf = 0;
    this._canvas = document.createElement('canvas');
    this._ctx = this._canvas.getContext('2d');
    this._spectrumCanvas = stage.querySelector('#visualCanvas');
    this._mime = '';
  }

  static isSupported() {
    return typeof MediaRecorder !== 'undefined' &&
           typeof HTMLCanvasElement.prototype.captureStream === 'function';
  }

  _pickMime(pref) {
    const candidates = [];
    if (pref === 'webm') candidates.push('video/webm;codecs=vp9,opus', 'video/webm;codecs=vp9');
    else if (pref === 'webm-vp8') candidates.push('video/webm;codecs=vp8,opus', 'video/webm;codecs=vp8');
    else if (pref === 'mp4') candidates.push('video/mp4;codecs=avc1,mp4a', 'video/mp4');
    candidates.push(
      'video/webm;codecs=vp9,opus',
      'video/webm;codecs=vp8,opus',
      'video/webm',
      'video/mp4'
    );
    for (const c of candidates) {
      try { if (MediaRecorder.isTypeSupported(c)) return c; } catch (_) {}
    }
    return '';
  }

  async start(prefFormat = 'auto') {
    if (!Exporter.isSupported()) {
      toast('Browser tidak mendukung export video (MediaRecorder).');
      return false;
    }
    if (!this.audioEngine.ctx) await this.audioEngine.ensureContext();

    const w = this.stage.clientWidth, h = this.stage.clientHeight;
    this._canvas.width = w;
    this._canvas.height = h;

    // 30fps stream from the offscreen composite canvas.
    const videoStream = this._canvas.captureStream(30);
    const audioStream = this.audioEngine.streamDest.stream;
    const merged = new MediaStream([
      ...videoStream.getVideoTracks(),
      ...audioStream.getAudioTracks(),
    ]);

    this._mime = this._pickMime(prefFormat === 'auto' ? '' : prefFormat);
    let opts = {};
    if (this._mime) opts.mimeType = this._mime;
    try {
      this.recorder = new MediaRecorder(merged, opts);
    } catch (e) {
      try { this.recorder = new MediaRecorder(merged); }
      catch (e2) { toast('Tidak ada codec yang didukung untuk export.'); return false; }
    }
    this.chunks = [];
    this.recorder.ondataavailable = (e) => { if (e.data && e.data.size) this.chunks.push(e.data); };
    this.recorder.onstop = () => this._save();
    this.recorder.start(1000);
    this._loop();
    return true;
  }

  stop() {
    if (this.recorder && this.recorder.state !== 'inactive') {
      this.recorder.stop();
    }
    cancelAnimationFrame(this._raf);
  }

  _save() {
    const blob = new Blob(this.chunks, { type: this._mime || 'video/webm' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const ext = (this._mime && this._mime.includes('mp4')) ? 'mp4' : 'webm';
    a.href = url;
    a.download = `visualizer-${new Date().toISOString().slice(0,19).replace(/[:T]/g,'-')}.${ext}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  _loop() {
    const draw = () => {
      this._composite();
      this._raf = requestAnimationFrame(draw);
    };
    this._raf = requestAnimationFrame(draw);
  }

  _composite() {
    const ctx = this._ctx;
    const c = this._canvas;
    const w = c.width, h = c.height;
    ctx.clearRect(0, 0, w, h);

    // 1) Background (image or video) with filters + dark overlay.
    const bg = this.getBgState();
    if (bg.mode !== 'none' && bg.source) {
      ctx.save();
      ctx.filter = `blur(${bg.filters.blur}px) brightness(${bg.filters.brightness})`;
      ctx.globalAlpha = bg.filters.opacity;
      this._drawCover(bg.source, w, h);
      ctx.restore();
    } else {
      // Fallback animated gradient (static snapshot).
      const g = ctx.createLinearGradient(0, 0, w, h);
      g.addColorStop(0, '#0a0d1f');
      g.addColorStop(0.5, '#191033');
      g.addColorStop(1, '#0a0d1f');
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);
    }
    // Dark overlay
    ctx.fillStyle = `rgba(0,0,0,${bg.filters.dark})`;
    ctx.fillRect(0, 0, w, h);

    // 2) Spectrum canvas (already drawn live). Just stamp it on.
    ctx.drawImage(this._spectrumCanvas, 0, 0, w, h);

    // 3) Lyrics
    const ly = this.getLyricsState();
    if (ly.visible) {
      ctx.save();
      ctx.textAlign = 'center';
      const cy = (ly.posPct / 100) * h;
      // active
      const active = ly.lines[ly.idx];
      const prev = ly.lines[ly.idx - 1];
      const next = ly.lines[ly.idx + 1];
      const fontMain = ly.fontPx;
      const fontSub = Math.max(14, fontMain * 0.45);
      ctx.shadowColor = 'rgba(0,240,255,0.55)';
      ctx.shadowBlur = 24;
      ctx.fillStyle = 'rgba(214,219,242,0.55)';
      ctx.font = `600 ${fontSub}px "Inter", "Segoe UI", sans-serif`;
      if (prev) this._fillTextWrapped(ctx, prev.text, w / 2, cy - fontMain * 0.85, w * 0.86, fontSub * 1.2);
      if (next) this._fillTextWrapped(ctx, next.text, w / 2, cy + fontMain * 0.95, w * 0.86, fontSub * 1.2);
      ctx.shadowColor = 'rgba(255,61,248,0.65)';
      ctx.shadowBlur = 32;
      ctx.fillStyle = '#ffffff';
      ctx.font = `800 ${fontMain}px "Inter", "Segoe UI", sans-serif`;
      if (active) this._fillTextWrapped(ctx, active.text, w / 2, cy + fontMain * 0.1, w * 0.86, fontMain * 1.15);
      ctx.restore();
    }

    // 4) Logo
    const lg = this.getLogoState();
    if (lg.img && lg.img.src) {
      const ratio = (lg.img.naturalWidth && lg.img.naturalHeight)
        ? lg.img.naturalWidth / lg.img.naturalHeight
        : 1;
      const lw = lg.size;
      const lh = lw / ratio;
      const m = 24;
      let x = m, y = m;
      switch (lg.pos) {
        case 'tl': x = m; y = m; break;
        case 'tr': x = w - lw - m; y = m; break;
        case 'bl': x = m; y = h - lh - m - 80; break;
        case 'br': x = w - lw - m; y = h - lh - m - 80; break;
        case 'cc': x = (w - lw) / 2; y = (h - lh) / 2; break;
      }
      ctx.save();
      ctx.globalAlpha = lg.opacity;
      ctx.shadowColor = 'rgba(0,240,255,0.7)';
      ctx.shadowBlur = lg.glow || 14;
      ctx.drawImage(lg.img, x, y, lw, lh);
      ctx.restore();
    }
  }

  _drawCover(srcEl, w, h) {
    let sw, sh;
    if (srcEl instanceof HTMLVideoElement) {
      sw = srcEl.videoWidth || w; sh = srcEl.videoHeight || h;
      if (!sw) { return; }
    } else {
      sw = srcEl.naturalWidth || w; sh = srcEl.naturalHeight || h;
    }
    const ratioCanvas = w / h, ratioSrc = sw / sh;
    let dx = 0, dy = 0, dw = w, dh = h;
    if (ratioSrc > ratioCanvas) {
      dh = h; dw = h * ratioSrc; dx = (w - dw) / 2;
    } else {
      dw = w; dh = w / ratioSrc; dy = (h - dh) / 2;
    }
    this._ctx.drawImage(srcEl, dx, dy, dw, dh);
  }

  _fillTextWrapped(ctx, text, cx, cy, maxWidth, lineHeight) {
    if (!text) return;
    // Wrap on whitespace if a single line would exceed maxWidth.
    const words = text.split(/\s+/);
    const lines = [];
    let cur = '';
    for (const w of words) {
      const test = cur ? cur + ' ' + w : w;
      if (ctx.measureText(test).width > maxWidth && cur) {
        lines.push(cur); cur = w;
      } else cur = test;
    }
    if (cur) lines.push(cur);
    const total = lines.length;
    const startY = cy - ((total - 1) * lineHeight) / 2;
    for (let i = 0; i < total; i++) ctx.fillText(lines[i], cx, startY + i * lineHeight);
  }
}
