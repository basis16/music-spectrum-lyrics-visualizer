"""Performance & system spec detection.

Reports a coarse hardware tier and a recommended :class:`PerfMode`.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Optional

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - psutil is in requirements but be defensive
    psutil = None  # type: ignore

from logger_manager import get_logger
from settings import PerfMode

log = get_logger(__name__)


@dataclass
class SystemInfo:
    cpu_count: int
    ram_gb: float
    free_disk_gb: float
    has_gpu: bool
    gpu_name: Optional[str]


def detect() -> SystemInfo:
    """Return a snapshot of the current machine's specs."""
    cpu = os.cpu_count() or 2
    ram = 4.0
    disk = 0.0
    if psutil is not None:
        try:
            ram = psutil.virtual_memory().total / (1024 ** 3)
        except Exception:
            pass
        try:
            disk = psutil.disk_usage(os.getcwd()).free / (1024 ** 3)
        except Exception:
            pass

    has_gpu, gpu_name = _detect_gpu()
    info = SystemInfo(
        cpu_count=cpu,
        ram_gb=round(ram, 1),
        free_disk_gb=round(disk, 1),
        has_gpu=has_gpu,
        gpu_name=gpu_name,
    )
    log.info("System info: %s", info)
    return info


def _detect_gpu() -> tuple[bool, Optional[str]]:
    """Best-effort GPU detection via nvidia-smi. Avoids heavy deps."""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return False, None
    try:
        import subprocess

        out = subprocess.run(
            [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        name = out.stdout.strip().splitlines()[0] if out.stdout.strip() else None
        return bool(name), name
    except Exception:
        return False, None


def recommended_mode(info: Optional[SystemInfo] = None) -> PerfMode:
    """Pick a sensible default perf mode based on system specs."""
    info = info or detect()
    if info.ram_gb < 6 or info.cpu_count < 4:
        return PerfMode.LOW
    if info.ram_gb >= 16 and info.cpu_count >= 8 and info.has_gpu:
        return PerfMode.HIGH
    return PerfMode.BALANCED


def low_spec_warning(info: Optional[SystemInfo] = None) -> Optional[str]:
    """Return a warning string if the machine is below recommended specs."""
    info = info or detect()
    if info.ram_gb < 6 or info.cpu_count < 4:
        return ("Disarankan menggunakan mode Low Spec agar aplikasi lebih ringan. "
                f"Terdeteksi: {info.cpu_count} CPU core, RAM {info.ram_gb} GB.")
    return None
