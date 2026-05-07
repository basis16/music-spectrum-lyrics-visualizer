// LRC parser and live-sync renderer.

export function parseLRC(text) {
  if (!text) return [];
  const lines = text.split(/\r?\n/);
  // [mm:ss.xx] OR [mm:ss] capture, possibly multiple per line (extended LRC).
  const re = /\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]/g;
  const out = [];
  for (const raw of lines) {
    const stamps = [];
    let m;
    re.lastIndex = 0;
    while ((m = re.exec(raw))) {
      const min = parseInt(m[1], 10);
      const sec = parseInt(m[2], 10);
      const fracStr = m[3] || '0';
      const frac = parseInt(fracStr, 10) / Math.pow(10, fracStr.length);
      const t = min * 60 + sec + frac;
      stamps.push(t);
    }
    if (!stamps.length) continue;
    const text = raw.replace(re, '').trim();
    for (const t of stamps) out.push({ t, text });
  }
  out.sort((a, b) => a.t - b.t);
  return out;
}

export function serializeLRC(lines) {
  return lines.map(l => {
    const m = Math.floor(l.t / 60);
    const s = (l.t % 60).toFixed(2).padStart(5, '0');
    return `[${m.toString().padStart(2, '0')}:${s}] ${l.text}`;
  }).join('\n');
}

export class LyricsRenderer {
  constructor(layer) {
    this.layer = layer;
    this.prevEl = layer.querySelector('.lyric-prev');
    this.activeEl = layer.querySelector('.lyric-active');
    this.nextEl = layer.querySelector('.lyric-next');
    this.lines = [];
    this._lastIndex = -2;
    this.visible = true;
  }

  setLines(lines) {
    this.lines = lines || [];
    this._lastIndex = -2;
    this.update(0);
  }

  setVisible(v) {
    this.visible = v;
    this.layer.classList.toggle('hidden', !v);
  }

  setPositionPct(p) { this.layer.style.setProperty('--lyric-y', `${p}%`); }
  setFontSize(px) { this.layer.style.setProperty('--lyric-size', `${px}px`); }

  // Find the current active line for time `t` using a simple linear scan;
  // small list so this stays cheap.
  _findIndex(t) {
    if (!this.lines.length) return -1;
    let idx = -1;
    for (let i = 0; i < this.lines.length; i++) {
      if (this.lines[i].t <= t) idx = i; else break;
    }
    return idx;
  }

  update(t) {
    if (!this.visible) return;
    const i = this._findIndex(t);
    if (i === this._lastIndex) return;
    this._lastIndex = i;
    const cur = this.lines[i];
    const prev = this.lines[i - 1];
    const next = this.lines[i + 1];
    this.prevEl.textContent = prev ? prev.text : '';
    this.nextEl.textContent = next ? next.text : '';
    this.activeEl.classList.remove('fade-in');
    // Force reflow to restart the animation.
    void this.activeEl.offsetWidth;
    this.activeEl.textContent = cur ? cur.text : '';
    this.activeEl.classList.add('fade-in');
  }
}
