"""Audio analysis for the spectrum visualizer.

Loads the user's audio with ``librosa``, computes:
- a per-frame magnitude spectrogram aggregated into perceptual bands,
- onset / beat envelopes for beat-reactive effects,
- bass / treble band energies for boosted reactions.

The output is a :class:`SpectrumFrames` object whose ``frames`` array has shape
``(num_frames, num_bars)`` with values normalised to ``[0, 1]``.

Heavy work is done up-front so the renderer just indexes into the array per
video frame -- this is what keeps the render loop responsive and the UI smooth.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from logger_manager import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------
@dataclass
class SpectrumFrames:
    """Pre-computed spectrum data sampled at the video frame rate."""

    frames: np.ndarray            # (num_frames, num_bars), float32 in [0,1]
    bass: np.ndarray              # (num_frames,) float32 in [0,1]
    treble: np.ndarray            # (num_frames,) float32 in [0,1]
    beat: np.ndarray              # (num_frames,) float32 in [0,1] - onset strength
    duration: float               # seconds
    fps: float                    # video frame rate
    sr: int                       # audio sample rate
    bar_count: int

    def __len__(self) -> int:
        return int(self.frames.shape[0])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _log_frequency_bands(sr: int, n_fft: int, n_bands: int,
                         f_min: float = 30.0, f_max: Optional[float] = None) -> list[tuple[int, int]]:
    """Return ``n_bands`` (start, end) FFT-bin index pairs spaced logarithmically."""
    f_max = f_max or (sr / 2.0)
    freqs = np.linspace(0, sr / 2.0, n_fft // 2 + 1)
    log_edges = np.logspace(np.log10(f_min), np.log10(f_max), n_bands + 1)
    bands: list[tuple[int, int]] = []
    for i in range(n_bands):
        lo = int(np.searchsorted(freqs, log_edges[i], side="left"))
        hi = int(np.searchsorted(freqs, log_edges[i + 1], side="left"))
        hi = max(hi, lo + 1)  # at least one bin
        bands.append((lo, min(hi, len(freqs))))
    return bands


def _ema_smooth(arr: np.ndarray, alpha: float) -> np.ndarray:
    """Exponential moving-average smoothing along axis 0 (time)."""
    if alpha <= 0:
        return arr
    out = np.empty_like(arr)
    prev = arr[0]
    out[0] = prev
    a = float(alpha)
    for i in range(1, arr.shape[0]):
        prev = a * prev + (1.0 - a) * arr[i]
        out[i] = prev
    return out


def _normalise(arr: np.ndarray, percentile: float = 99.0) -> np.ndarray:
    """Scale ``arr`` so the given percentile -> 1.0 (clipped to [0,1])."""
    if arr.size == 0:
        return arr
    p = float(np.percentile(arr, percentile))
    if p <= 1e-9:
        return np.zeros_like(arr)
    out = arr / p
    return np.clip(out, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def analyze(audio_path: str | Path,
            *,
            fps: int,
            bar_count: int,
            sensitivity: float = 1.0,
            bass_boost: float = 1.4,
            treble_boost: float = 1.05,
            smoothing: float = 0.55,
            sr_target: int = 22050) -> SpectrumFrames:
    """Compute a per-video-frame spectrum from an audio file.

    Parameters
    ----------
    audio_path: path to mp3/wav/m4a/flac.
    fps: target video frame rate. The output array has one row per video frame.
    bar_count: number of frequency bars in the visualisation.
    sensitivity: post-normalisation gain (applied before clipping).
    bass_boost / treble_boost: per-bar gain for the lowest / highest 25% bars.
    smoothing: EMA alpha (0..0.95) applied along time. Higher = smoother.
    sr_target: target sample rate for analysis. 22050 is plenty for visuals
        and keeps memory/CPU low on weak machines.
    """
    import librosa  # heavy import; deferred

    path = str(audio_path)
    log.info("Loading audio: %s", path)
    y, sr = librosa.load(path, sr=sr_target, mono=True)
    duration = float(len(y)) / float(sr)
    log.info("Loaded %.2fs @ %d Hz", duration, sr)

    # Step / window aligned to one video frame so spectrogram time == video time.
    hop_length = max(1, int(round(sr / fps)))
    n_fft = 2048
    log.info("Computing STFT (n_fft=%d, hop=%d)", n_fft, hop_length)

    stft = librosa.stft(y, n_fft=n_fft, hop_length=hop_length, center=True)
    mag = np.abs(stft).astype(np.float32)        # (n_fft/2+1, n_frames)
    # Convert to dB then back to a perceptual scale.
    mag_db = librosa.amplitude_to_db(mag, ref=np.max)
    perceptual = np.clip((mag_db + 80.0) / 80.0, 0.0, 1.0)  # ~[0,1]

    bands = _log_frequency_bands(sr, n_fft, bar_count, f_min=30.0)
    n_time = perceptual.shape[1]
    bars = np.empty((n_time, bar_count), dtype=np.float32)
    for i, (lo, hi) in enumerate(bands):
        bars[:, i] = perceptual[lo:hi, :].mean(axis=0) if hi > lo else 0.0

    # Per-band boosts: low 25% bars = bass, top 25% = treble.
    n_bass = max(1, bar_count // 4)
    n_treble = max(1, bar_count // 4)
    bars[:, :n_bass] *= float(bass_boost)
    bars[:, -n_treble:] *= float(treble_boost)
    bars = np.clip(bars * float(sensitivity), 0.0, 1.5)

    # Time smoothing (EMA, attack/decay).
    bars = _ema_smooth(bars, alpha=float(smoothing))
    bars = np.clip(bars, 0.0, 1.0)

    # Beat / onset envelope at the same hop.
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    onset_env = _normalise(onset_env, percentile=98.0)

    bass_env = bars[:, :n_bass].mean(axis=1)
    treble_env = bars[:, -n_treble:].mean(axis=1)

    # Resample to video frame count (should already be ~equal due to hop choice).
    n_video_frames = int(np.floor(duration * fps))
    if n_video_frames <= 0:
        raise ValueError("Audio too short to render any video frames.")
    bars_v = _resample_axis0(bars, n_video_frames)
    bass_v = _resample_1d(bass_env, n_video_frames)
    treble_v = _resample_1d(treble_env, n_video_frames)
    beat_v = _resample_1d(onset_env, n_video_frames)

    return SpectrumFrames(
        frames=bars_v.astype(np.float32),
        bass=bass_v.astype(np.float32),
        treble=treble_v.astype(np.float32),
        beat=beat_v.astype(np.float32),
        duration=duration,
        fps=float(fps),
        sr=int(sr),
        bar_count=int(bar_count),
    )


def _resample_axis0(arr: np.ndarray, n_target: int) -> np.ndarray:
    """Linearly resample along axis 0 to length ``n_target``."""
    n = arr.shape[0]
    if n == n_target or n == 0:
        return arr
    src_idx = np.linspace(0, n - 1, n_target, dtype=np.float32)
    lo = np.floor(src_idx).astype(np.int32)
    hi = np.clip(lo + 1, 0, n - 1)
    frac = (src_idx - lo).astype(np.float32)[:, None]
    return arr[lo] * (1.0 - frac) + arr[hi] * frac


def _resample_1d(arr: np.ndarray, n_target: int) -> np.ndarray:
    n = arr.shape[0]
    if n == n_target or n == 0:
        return arr
    src_idx = np.linspace(0, n - 1, n_target, dtype=np.float32)
    lo = np.floor(src_idx).astype(np.int32)
    hi = np.clip(lo + 1, 0, n - 1)
    frac = (src_idx - lo).astype(np.float32)
    return arr[lo] * (1.0 - frac) + arr[hi] * frac
