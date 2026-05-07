// Background image/video swap + filter controls.

export class Background {
  constructor(imgEl, videoEl, overlayEl) {
    this.img = imgEl;
    this.video = videoEl;
    this.overlay = overlayEl;
    this._url = null;
    this._mode = 'none'; // 'image' | 'video' | 'none'
    this._filters = { blur: 0, brightness: 1, opacity: 1, dark: 0.35 };
    this.applyFilters();
  }

  setImage(file) {
    this.clear();
    this._url = URL.createObjectURL(file);
    this.img.src = this._url;
    this.img.classList.add('show');
    this._mode = 'image';
    this.applyFilters();
  }

  setVideo(file) {
    this.clear();
    this._url = URL.createObjectURL(file);
    this.video.src = this._url;
    this.video.classList.add('show');
    this.video.play().catch(() => {/* blocked until user interaction */});
    this._mode = 'video';
    this.applyFilters();
  }

  clear() {
    if (this._url) { URL.revokeObjectURL(this._url); this._url = null; }
    this.img.removeAttribute('src');
    this.img.classList.remove('show');
    this.video.pause();
    this.video.removeAttribute('src');
    this.video.load();
    this.video.classList.remove('show');
    this._mode = 'none';
  }

  // Re-sync video transport when audio is paused/seeked so they stay aligned.
  syncToAudio(audioEl) {
    if (this._mode !== 'video') return;
    try {
      if (audioEl.paused) this.video.pause();
      else this.video.play().catch(() => {});
    } catch (_) {}
  }

  setFilter(key, val) {
    this._filters[key] = val;
    this.applyFilters();
  }

  applyFilters() {
    const f = this._filters;
    const css = `blur(${f.blur}px) brightness(${f.brightness})`;
    [this.img, this.video].forEach(el => {
      el.style.filter = css;
      el.style.opacity = f.opacity;
    });
    this.overlay.style.background = `rgba(0,0,0,${f.dark})`;
  }
}
