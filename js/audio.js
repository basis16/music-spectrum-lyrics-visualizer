// Web Audio pipeline: <audio> → MediaElementSource → GainNode → AnalyserNode → destination
// Also exposes a MediaStream of the post-gain audio for MediaRecorder export.

export class AudioEngine {
  constructor(audioEl) {
    this.audioEl = audioEl;
    this.ctx = null;
    this.source = null;
    this.gain = null;
    this.analyser = null;
    this.streamDest = null;
    this.freqData = null;
    this.timeData = null;
    this._fftSize = 1024;
    this._smoothing = 0.78;
  }

  async ensureContext() {
    if (this.ctx) {
      if (this.ctx.state === 'suspended') {
        try { await this.ctx.resume(); } catch (_) {}
      }
      return;
    }
    const Ctx = window.AudioContext || window.webkitAudioContext;
    this.ctx = new Ctx();
    this.source = this.ctx.createMediaElementSource(this.audioEl);
    this.gain = this.ctx.createGain();
    this.gain.gain.value = parseFloat(this.audioEl.volume) || 0.85;
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = this._fftSize;
    this.analyser.smoothingTimeConstant = this._smoothing;
    // Stream destination for export (carries the same audio).
    this.streamDest = this.ctx.createMediaStreamDestination();

    // Wiring: source → gain → analyser → speakers
    //                       ↘
    //                        streamDest (for MediaRecorder)
    this.source.connect(this.gain);
    this.gain.connect(this.analyser);
    this.analyser.connect(this.ctx.destination);
    this.gain.connect(this.streamDest);

    this.freqData = new Uint8Array(this.analyser.frequencyBinCount);
    this.timeData = new Uint8Array(this.analyser.fftSize);
  }

  setFftSize(n) {
    if (!this.analyser) { this._fftSize = n; return; }
    if (this.analyser.fftSize === n) return;
    this.analyser.fftSize = n;
    this.freqData = new Uint8Array(this.analyser.frequencyBinCount);
    this.timeData = new Uint8Array(this.analyser.fftSize);
  }

  setSmoothing(v) {
    this._smoothing = v;
    if (this.analyser) this.analyser.smoothingTimeConstant = v;
  }

  setVolume(v) {
    this.audioEl.volume = v;
    if (this.gain) this.gain.gain.value = v;
  }

  // Pull current frequency + waveform buffers.
  update() {
    if (!this.analyser) return null;
    this.analyser.getByteFrequencyData(this.freqData);
    this.analyser.getByteTimeDomainData(this.timeData);
    return { freq: this.freqData, wave: this.timeData };
  }

  // Average loudness in 0..1 — used by particle mode + lyric "beat" effects.
  energy() {
    if (!this.freqData) return 0;
    let s = 0;
    for (let i = 0; i < this.freqData.length; i++) s += this.freqData[i];
    return (s / this.freqData.length) / 255;
  }
}
