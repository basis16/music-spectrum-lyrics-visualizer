// Small shared helpers.

export function $(sel, root = document) { return root.querySelector(sel); }
export function $$(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

export function clamp(v, min, max) { return Math.min(max, Math.max(min, v)); }

export function formatTime(t) {
  if (!isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

let toastTimer = null;
export function toast(msg, ms = 2400) {
  const el = $('#toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), ms);
}

// HSL → CSS string.
export function hsl(h, s = 100, l = 55, a = 1) {
  return `hsla(${h}, ${s}%, ${l}%, ${a})`;
}

// Map a normalized 0..1 value through one of the named themes.
// Returns an HSLA color string. Used by every visualizer mode.
export function themeColor(theme, t, alpha = 1) {
  switch (theme) {
    case 'aurora': {
      // green→cyan→magenta
      const h = 140 + t * 180;
      return hsl(h, 95, 55, alpha);
    }
    case 'sunset': {
      // red-orange-yellow-pink
      const h = 350 + t * 60;
      return hsl(h % 360, 95, 58, alpha);
    }
    case 'cyberpunk': {
      // pink ↔ cyan
      const h = t < 0.5 ? 320 - t * 60 : 180 + (t - 0.5) * 40;
      return hsl(h, 100, 58, alpha);
    }
    case 'ocean': {
      const h = 190 + t * 70; // teal → indigo
      return hsl(h, 95, 55, alpha);
    }
    case 'mono': {
      return hsl(190, 100, 55 + t * 25, alpha);
    }
    case 'rainbow':
    default:
      return hsl(t * 360, 100, 58, alpha);
  }
}

// Sample multiple visualizer-quality presets.
export const QUALITY_PRESETS = {
  low:    { fft: 512,  bars: 48,  particleMax: 80,  dpr: 1 },
  medium: { fft: 1024, bars: 72,  particleMax: 160, dpr: 1 },
  high:   { fft: 2048, bars: 110, particleMax: 280, dpr: 2 },
};
