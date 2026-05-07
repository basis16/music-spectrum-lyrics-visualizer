// Canvas-based visualizers: bar, circular, waveform, particle.
// Each function takes a draw context and the latest analyser data.

import { themeColor, QUALITY_PRESETS } from './utils.js';

export class Visualizer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.mode = 'bar';
    this.theme = 'rainbow';
    this.glow = 18;
    this.sensitivity = 1.4;
    this.quality = 'medium';
    this.particles = [];
    this.lastBeat = 0;
    this._dpr = 1;
    this._resizeRaf = null;
    this.handleResize = this.handleResize.bind(this);
    window.addEventListener('resize', this.handleResize);
    this.handleResize();
  }

  setMode(mode) { this.mode = mode; }
  setTheme(theme) { this.theme = theme; }
  setGlow(v) { this.glow = v; }
  setSensitivity(v) { this.sensitivity = v; }
  setQuality(q) {
    this.quality = q;
    this._dpr = Math.min(window.devicePixelRatio || 1, QUALITY_PRESETS[q].dpr);
    this.handleResize();
  }

  handleResize() {
    cancelAnimationFrame(this._resizeRaf);
    this._resizeRaf = requestAnimationFrame(() => {
      const dpr = this._dpr || 1;
      const w = this.canvas.clientWidth || window.innerWidth;
      const h = this.canvas.clientHeight || window.innerHeight;
      this.canvas.width = Math.floor(w * dpr);
      this.canvas.height = Math.floor(h * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    });
  }

  draw(audioData, energy) {
    const { freq, wave } = audioData || {};
    const ctx = this.ctx;
    const w = this.canvas.clientWidth || window.innerWidth;
    const h = this.canvas.clientHeight || window.innerHeight;
    ctx.clearRect(0, 0, w, h);
    if (!freq) return;

    switch (this.mode) {
      case 'circular': this._drawCircular(freq, w, h, energy); break;
      case 'waveform': this._drawWaveform(wave, w, h); break;
      case 'particle': this._drawParticles(freq, w, h, energy); break;
      case 'bar':
      default:         this._drawBars(freq, w, h);
    }
  }

  // ----- Bar Spectrum -----
  _drawBars(freq, w, h) {
    const ctx = this.ctx;
    const bars = QUALITY_PRESETS[this.quality].bars;
    const usable = Math.floor(freq.length * 0.78);
    const step = usable / bars;
    const barW = w / bars * 0.78;
    const gap = w / bars * 0.22;
    ctx.lineCap = 'round';
    for (let i = 0; i < bars; i++) {
      // Pull the average of [i*step .. (i+1)*step] for a smoother shape.
      let sum = 0; const start = Math.floor(i * step), end = Math.floor((i + 1) * step);
      for (let j = start; j < end; j++) sum += freq[j];
      const v = (sum / Math.max(1, end - start) / 255) * this.sensitivity;
      const barH = Math.min(1, v) * h * 0.62;
      const x = i * (barW + gap) + gap / 2;
      const y = h - barH - 12;
      const t = i / bars;
      const color = themeColor(this.theme, t, 1);
      const grad = ctx.createLinearGradient(0, y, 0, y + barH);
      grad.addColorStop(0, color);
      grad.addColorStop(1, themeColor(this.theme, (t + 0.18) % 1, 0.85));
      ctx.shadowBlur = this.glow;
      ctx.shadowColor = color;
      ctx.fillStyle = grad;
      this._roundRect(ctx, x, y, barW, barH, Math.min(barW * 0.45, 8));
      ctx.fill();
    }
    ctx.shadowBlur = 0;

    // Mirror reflection for the music-video vibe.
    ctx.save();
    ctx.globalAlpha = 0.25;
    ctx.scale(1, -1);
    ctx.translate(0, -2 * (h - 12));
    for (let i = 0; i < bars; i++) {
      let sum = 0; const start = Math.floor(i * step), end = Math.floor((i + 1) * step);
      for (let j = start; j < end; j++) sum += freq[j];
      const v = (sum / Math.max(1, end - start) / 255) * this.sensitivity;
      const barH = Math.min(1, v) * h * 0.18;
      const x = i * (barW + gap) + gap / 2;
      const y = h - barH - 12;
      const t = i / bars;
      ctx.fillStyle = themeColor(this.theme, t, 0.6);
      this._roundRect(ctx, x, y, barW, barH, 4);
      ctx.fill();
    }
    ctx.restore();
  }

  // ----- Circular Spectrum -----
  _drawCircular(freq, w, h, energy) {
    const ctx = this.ctx;
    const cx = w / 2, cy = h / 2;
    const radius = Math.min(w, h) * 0.22 + (energy || 0) * 18;
    const bars = Math.min(180, QUALITY_PRESETS[this.quality].bars * 2);
    const step = Math.floor(freq.length * 0.7 / bars);
    ctx.save();
    ctx.translate(cx, cy);
    ctx.lineCap = 'round';
    for (let i = 0; i < bars; i++) {
      let sum = 0;
      for (let j = 0; j < step; j++) sum += freq[i * step + j] || 0;
      const v = (sum / Math.max(1, step) / 255) * this.sensitivity;
      const len = Math.min(1, v) * Math.min(w, h) * 0.28;
      const angle = (i / bars) * Math.PI * 2 - Math.PI / 2;
      const x1 = Math.cos(angle) * radius;
      const y1 = Math.sin(angle) * radius;
      const x2 = Math.cos(angle) * (radius + len);
      const y2 = Math.sin(angle) * (radius + len);
      const color = themeColor(this.theme, i / bars, 1);
      ctx.strokeStyle = color;
      ctx.shadowBlur = this.glow;
      ctx.shadowColor = color;
      ctx.lineWidth = Math.max(2, w / bars * 0.55);
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
    // Inner glowing ring
    ctx.shadowBlur = this.glow * 1.4;
    ctx.shadowColor = themeColor(this.theme, 0.5, 1);
    ctx.strokeStyle = themeColor(this.theme, 0.5, 0.9);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(0, 0, radius - 6, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
    ctx.shadowBlur = 0;
  }

  // ----- Waveform -----
  _drawWaveform(wave, w, h) {
    if (!wave) return;
    const ctx = this.ctx;
    const cy = h / 2;
    const amp = h * 0.32 * this.sensitivity;
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    // Two layered strokes (neon outer + bright inner).
    const drawPass = (alpha, blur, lineWidth, hueShift = 0) => {
      ctx.shadowBlur = blur;
      ctx.beginPath();
      const stride = Math.max(1, Math.floor(wave.length / w));
      for (let i = 0, x = 0; i < wave.length; i += stride, x = (i / wave.length) * w) {
        const v = (wave[i] - 128) / 128;
        const y = cy + v * amp;
        const hue = (x / w + hueShift) % 1;
        const color = themeColor(this.theme, hue, alpha);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        ctx.strokeStyle = color;
        ctx.shadowColor = color;
      }
      ctx.lineWidth = lineWidth;
      ctx.stroke();
    };
    drawPass(0.9, this.glow * 1.4, 6, 0);
    drawPass(1, this.glow, 2.5, 0.15);
    ctx.shadowBlur = 0;
  }

  // ----- Particle Beat -----
  _drawParticles(freq, w, h, energy) {
    const ctx = this.ctx;
    const cap = QUALITY_PRESETS[this.quality].particleMax;
    // Detect a beat — high band energy spike.
    let bass = 0;
    for (let i = 0; i < 12; i++) bass += freq[i] || 0;
    bass /= 12 * 255;
    const now = performance.now();
    const beat = bass > 0.55 && now - this.lastBeat > 110;
    if (beat) {
      this.lastBeat = now;
      const burst = 18 + Math.floor(bass * 22);
      for (let i = 0; i < burst && this.particles.length < cap; i++) {
        const angle = Math.random() * Math.PI * 2;
        const speed = 2 + Math.random() * 6 * (0.5 + bass);
        this.particles.push({
          x: w / 2, y: h / 2,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed,
          life: 1,
          size: 2 + Math.random() * 4,
          hue: Math.random(),
        });
      }
    }
    // Always emit a few ambient particles tied to overall energy.
    if (this.particles.length < cap && Math.random() < 0.4 + (energy || 0)) {
      this.particles.push({
        x: Math.random() * w, y: h + 8,
        vx: (Math.random() - 0.5) * 0.6,
        vy: -1 - Math.random() * 1.5 - (energy || 0) * 1.5,
        life: 1, size: 1.5 + Math.random() * 2.5, hue: Math.random(),
      });
    }
    ctx.globalCompositeOperation = 'lighter';
    for (let i = this.particles.length - 1; i >= 0; i--) {
      const p = this.particles[i];
      p.x += p.vx; p.y += p.vy;
      p.vx *= 0.985; p.vy *= 0.985;
      p.life -= 0.012;
      if (p.life <= 0) { this.particles.splice(i, 1); continue; }
      const color = themeColor(this.theme, p.hue, p.life);
      ctx.shadowBlur = this.glow;
      ctx.shadowColor = color;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size * (0.5 + p.life), 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalCompositeOperation = 'source-over';
    ctx.shadowBlur = 0;
  }

  _roundRect(ctx, x, y, w, h, r) {
    if (h < 1) h = 1;
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }
}
