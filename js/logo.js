// Logo overlay positioning + style.

export class Logo {
  constructor(el) {
    this.el = el;
    this._url = null;
    this._pos = 'tr';
    this._size = 120;
    this._opacity = 0.9;
    this._glow = 14;
    this.apply();
  }

  setImage(file) {
    this.clear();
    this._url = URL.createObjectURL(file);
    this.el.src = this._url;
    this.el.classList.add('show');
  }

  clear() {
    if (this._url) { URL.revokeObjectURL(this._url); this._url = null; }
    this.el.removeAttribute('src');
    this.el.classList.remove('show');
  }

  setPosition(p) { this._pos = p; this.apply(); }
  setSize(px)    { this._size = px; this.apply(); }
  setOpacity(a)  { this._opacity = a; this.apply(); }
  setGlow(g)     { this._glow = g; this.apply(); }

  apply() {
    const m = 24; // margin from edge
    const s = this._size;
    const e = this.el;
    e.style.width = `${s}px`;
    e.style.height = 'auto';
    e.style.opacity = this._opacity;
    e.style.setProperty('--logo-glow', `${this._glow}px`);
    // Reset all positioning first.
    e.style.top = e.style.bottom = e.style.left = e.style.right = 'auto';
    e.style.transform = 'none';
    switch (this._pos) {
      case 'tl': e.style.top = `${m}px`; e.style.left = `${m}px`; break;
      case 'tr': e.style.top = `${m}px`; e.style.right = `${m}px`; break;
      case 'bl': e.style.bottom = `${m + 80}px`; e.style.left = `${m}px`; break; // leave room for player bar
      case 'br': e.style.bottom = `${m + 80}px`; e.style.right = `${m}px`; break;
      case 'cc':
        e.style.top = '50%'; e.style.left = '50%';
        e.style.transform = 'translate(-50%, -50%)';
        break;
    }
  }
}
