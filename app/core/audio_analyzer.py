"""Audio decoding and spectrum analysis.

This module turns an audio file into:

* a 1-D ``numpy`` array of mono PCM samples (used for waveform-style
  spectrum visualisations),
* a 2-D ``numpy`` array of per-frame frequency-bin magnitudes
  ``[num_frames, num_bins]`` aligned to the video FPS.

Audio is decoded through ``ffmpeg`` (already required by the renderer)
because it understands every codec we care about — MP3, FLAC, M4A, OGG —
without pulling in an extra heavyweight Python decoder.

Results are cached on disk keyed by ``(file content hash, fps, bins,
fmin, fmax)``. Re-rendering with different colours/styles is therefore
near-instant.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from app.core.ffmpeg_manager import FFmpegManager, get_default_manager
from app.utils.file_utils import cache_dir, file_hash
from app.utils.logger import get_logger

log = get_logger("audio")


SAMPLE_RATE = 44_100  # decode target


@dataclass
class SpectrumData:
    """Pre-computed spectrum data for a single audio file."""

    fps: int
    num_bins: int
    fmin: float
    fmax: float
    duration: float            # seconds
    waveform: np.ndarray       # 1D float32, mono, downmixed
    spectrum: np.ndarray       # [num_frames, num_bins] float32 in [0, 1]
    sample_rate: int = SAMPLE_RATE

    @property
    def num_frames(self) -> int:
        return int(self.spectrum.shape[0])


class AudioAnalyzer:
    """Decode audio and compute spectrum frames for a target video FPS."""

    def __init__(self, ffmpeg: Optional[FFmpegManager] = None):
        self._ffmpeg = ffmpeg or get_default_manager()

    # ------------------------------------------------------------------
    def analyze(
        self,
        audio_path: str | Path,
        fps: int,
        num_bins: int = 64,
        fmin: float = 30.0,
        fmax: float = 16_000.0,
        on_progress: Optional[Callable[[float], None]] = None,
        force: bool = False,
    ) -> SpectrumData:
        """Return cached or freshly-computed :class:`SpectrumData`."""
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)

        key = self._cache_key(audio_path, fps, num_bins, fmin, fmax)
        npz_path = cache_dir() / f"{key}.npz"
        meta_path = cache_dir() / f"{key}.json"

        if not force and npz_path.exists() and meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                data = np.load(npz_path)
                return SpectrumData(
                    fps=int(meta["fps"]),
                    num_bins=int(meta["num_bins"]),
                    fmin=float(meta["fmin"]),
                    fmax=float(meta["fmax"]),
                    duration=float(meta["duration"]),
                    waveform=data["waveform"],
                    spectrum=data["spectrum"],
                    sample_rate=int(meta.get("sample_rate", SAMPLE_RATE)),
                )
            except Exception as e:  # noqa: BLE001
                log.warning("Cache load failed (%s): %s — recomputing", npz_path.name, e)

        # Otherwise decode + analyse.
        log.info("Analysing audio: %s", audio_path.name)
        samples = self._decode_pcm(audio_path)
        duration = len(samples) / float(SAMPLE_RATE)
        spectrum = self._compute_spectrum(
            samples, fps=fps, num_bins=num_bins, fmin=fmin, fmax=fmax,
            on_progress=on_progress,
        )
        data = SpectrumData(
            fps=fps, num_bins=num_bins, fmin=fmin, fmax=fmax,
            duration=duration, waveform=samples, spectrum=spectrum,
        )

        # Save to cache (best-effort).
        try:
            np.savez_compressed(npz_path, waveform=samples, spectrum=spectrum)
            meta_path.write_text(
                json.dumps(
                    {
                        "fps": fps, "num_bins": num_bins,
                        "fmin": fmin, "fmax": fmax,
                        "duration": duration,
                        "sample_rate": SAMPLE_RATE,
                    },
                    indent=0,
                ),
                encoding="utf-8",
            )
        except OSError as e:
            log.warning("Cache save failed: %s", e)
        return data

    # ------------------------------------------------------------------
    def _cache_key(self, audio_path: Path, fps: int, num_bins: int,
                    fmin: float, fmax: float) -> str:
        h = file_hash(audio_path)
        return f"{h}_fps{fps}_bins{num_bins}_{int(fmin)}_{int(fmax)}"

    def _decode_pcm(self, audio_path: Path) -> np.ndarray:
        """Use ffmpeg to decode audio to mono 16-bit PCM at SAMPLE_RATE."""
        info = self._ffmpeg.detect()
        if not info.ffmpeg_path:
            raise RuntimeError("FFmpeg is not available; cannot decode audio.")

        cmd = [
            info.ffmpeg_path, "-hide_banner", "-loglevel", "error",
            "-i", str(audio_path),
            "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-f", "s16le", "-",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, check=True)
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode("utf-8", errors="ignore")[:500]
            raise RuntimeError(f"FFmpeg decode failed: {err}") from e

        raw = proc.stdout
        if not raw:
            raise RuntimeError("FFmpeg returned no audio data.")
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        return samples

    # ------------------------------------------------------------------
    def _compute_spectrum(
        self,
        samples: np.ndarray,
        fps: int,
        num_bins: int,
        fmin: float,
        fmax: float,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> np.ndarray:
        """Compute frame-aligned magnitude spectrogram with log-spaced bins."""
        if fps <= 0:
            raise ValueError("fps must be positive")
        if num_bins < 8:
            num_bins = 8

        hop = max(1, int(SAMPLE_RATE / fps))
        # Use a generous window so low-frequency bins still resolve.
        win_size = max(1024, hop * 2)
        # Round window up to a power of two for fft efficiency.
        win_size = 1 << (win_size - 1).bit_length()

        window = np.hanning(win_size).astype(np.float32)
        n_fft = win_size
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / SAMPLE_RATE)

        # Pre-compute log-spaced bin edges in Hz, then map to FFT indices.
        edges = np.geomspace(max(20.0, fmin), min(fmax, SAMPLE_RATE / 2), num_bins + 1)
        bin_idx_edges = np.searchsorted(freqs, edges).astype(np.int32)

        # Pad samples so the last frame is full.
        num_frames = int(np.ceil(len(samples) / hop))
        total_padded = num_frames * hop + win_size
        if total_padded > len(samples):
            samples = np.pad(samples, (0, total_padded - len(samples)))

        spectrum = np.zeros((num_frames, num_bins), dtype=np.float32)
        progress_every = max(1, num_frames // 100)

        for i in range(num_frames):
            start = i * hop
            frame = samples[start: start + win_size] * window
            mag = np.abs(np.fft.rfft(frame, n=n_fft))
            # Map FFT bins -> our log bins by averaging within each edge pair.
            for b in range(num_bins):
                lo = bin_idx_edges[b]
                hi = max(lo + 1, bin_idx_edges[b + 1])
                spectrum[i, b] = mag[lo:hi].mean()
            if on_progress and (i % progress_every == 0):
                on_progress(i / num_frames)

        # Log compress + normalise to [0, 1] using a sensible reference so the
        # bars don't max out on every transient.
        spectrum = np.log1p(spectrum)
        # Per-bin normalisation against the 98th percentile of that bin keeps
        # quieter highs visible without clipping bass.
        ref = np.percentile(spectrum, 98, axis=0)
        ref = np.where(ref < 1e-3, 1.0, ref)
        spectrum = np.clip(spectrum / ref, 0.0, 1.0)

        # Gentle temporal smoothing so bars don't twitch.
        if num_frames > 4:
            smoothed = spectrum.copy()
            alpha = 0.55
            for t in range(1, num_frames):
                smoothed[t] = alpha * smoothed[t - 1] + (1.0 - alpha) * spectrum[t]
            # Bias slightly toward the live value for responsiveness.
            spectrum = 0.7 * smoothed + 0.3 * spectrum

        if on_progress:
            on_progress(1.0)
        return spectrum.astype(np.float32)


def apply_sensitivity_and_smoothness(
    spectrum: np.ndarray,
    sensitivity: float = 1.0,
    smoothness: float = 0.0,
) -> np.ndarray:
    """Return a new spectrum with user-tunable response.

    ``sensitivity`` > 1 lifts quieter parts; ``smoothness`` in ``[0, 1]``
    blends each frame with its predecessor.
    """
    out = np.clip(spectrum * float(max(0.05, sensitivity)), 0.0, 1.0)
    smoothness = float(min(0.95, max(0.0, smoothness)))
    if smoothness > 0 and out.shape[0] > 1:
        smoothed = out.copy()
        for t in range(1, out.shape[0]):
            smoothed[t] = (smoothness * smoothed[t - 1]
                            + (1.0 - smoothness) * out[t])
        out = smoothed
    return out
