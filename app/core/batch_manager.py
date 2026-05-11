"""Batch render orchestrator.

The :class:`BatchManager` is intentionally headless — it knows nothing
about Qt. The UI subscribes to callbacks (``on_progress``, ``on_item``,
``on_log``) so it can show per-item status in a queue panel.

A batch run iterates over a list of audio files, building a
:class:`RenderConfig` for each one by combining the user's defaults
with a background selected according to the requested ``mode``
(``sequence`` / ``match`` / ``random``).

Errors on a single song never abort the batch: the failure is logged
and the next song is processed.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from app.core.renderer import RenderConfig, Renderer, default_output_path
from app.utils.file_utils import list_audio_files, list_background_files, pick_background
from app.utils.logger import get_logger

log = get_logger("batch")


class ItemStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class BatchItem:
    audio_path: Path
    background_path: Optional[Path] = None
    output_path: Optional[Path] = None
    status: ItemStatus = ItemStatus.PENDING
    message: str = ""
    elapsed: float = 0.0


@dataclass
class BatchOptions:
    audio_folder: str
    output_folder: str
    background_folder: Optional[str] = None
    background_mode: str = "sequence"  # sequence | match | random
    recursive: bool = True


@dataclass
class BatchResult:
    items: List[BatchItem] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    @property
    def succeeded(self) -> int:
        return sum(1 for i in self.items if i.status is ItemStatus.DONE)

    @property
    def failed(self) -> int:
        return sum(1 for i in self.items if i.status is ItemStatus.FAILED)


class BatchManager:
    """Run a list of render jobs sequentially in a background thread."""

    def __init__(self, renderer: Renderer,
                  base_config: RenderConfig,
                  options: BatchOptions):
        self._renderer = renderer
        self._base_config = base_config
        self._options = options
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._result: BatchResult = BatchResult()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def build_items(self) -> List[BatchItem]:
        audios = list_audio_files(self._options.audio_folder,
                                    recursive=self._options.recursive)
        bgs: List[Path] = []
        if self._options.background_folder:
            bgs = list_background_files(self._options.background_folder,
                                         recursive=self._options.recursive)
        items: List[BatchItem] = []
        for i, a in enumerate(audios):
            bg = pick_background(a, bgs, self._options.background_mode, i)
            out = default_output_path(str(a), self._options.output_folder,
                                       extension=self._base_config.encoder
                                       and "mp4")
            items.append(BatchItem(audio_path=a, background_path=bg,
                                    output_path=out))
        return items

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def start(
        self,
        items: Sequence[BatchItem],
        on_item: Optional[Callable[[int, BatchItem], None]] = None,
        on_progress: Optional[Callable[[int, float, str], None]] = None,
        on_done: Optional[Callable[[BatchResult], None]] = None,
    ) -> threading.Thread:
        """Start the batch in a daemon thread."""
        self._cancel.clear()
        with self._lock:
            self._result = BatchResult()
            self._result.items = list(items)

        def runner():
            try:
                self._run(on_item=on_item, on_progress=on_progress)
            finally:
                with self._lock:
                    self._result.finished_at = time.time()
                if on_done:
                    on_done(self._result)

        t = threading.Thread(target=runner, name="BatchManager",
                              daemon=True)
        self._thread = t
        t.start()
        return t

    def cancel(self) -> None:
        self._cancel.set()
        self._renderer.cancel()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def result(self) -> BatchResult:
        return self._result

    # ------------------------------------------------------------------
    def _run(self, on_item, on_progress):
        for idx, item in enumerate(self._result.items):
            if self._cancel.is_set():
                item.status = ItemStatus.SKIPPED
                item.message = "Batch cancelled."
                if on_item:
                    on_item(idx, item)
                continue

            item.status = ItemStatus.RUNNING
            if on_item:
                on_item(idx, item)
            start = time.time()

            try:
                cfg = self._build_config(item)
                if not item.output_path:
                    raise RuntimeError("No output path for item")
                self._renderer.reset_cancel()
                self._renderer.render(
                    cfg,
                    on_progress=(lambda pct, msg: on_progress(idx, pct, msg))
                    if on_progress else None,
                )
                item.status = ItemStatus.DONE
                item.message = f"Saved to {item.output_path}"
                log.info("Batch item OK: %s", item.audio_path.name)
            except Exception as e:  # noqa: BLE001
                item.status = ItemStatus.FAILED
                item.message = str(e)
                log.error("Batch item FAILED %s: %s", item.audio_path.name, e)
            finally:
                item.elapsed = time.time() - start
                if on_item:
                    on_item(idx, item)

    def _build_config(self, item: BatchItem) -> RenderConfig:
        cfg = RenderConfig(**self._base_config.__dict__)
        cfg.audio_path = str(item.audio_path)
        cfg.output_path = str(item.output_path) if item.output_path else \
            str(default_output_path(str(item.audio_path),
                                      self._options.output_folder))
        cfg.background_path = str(item.background_path) if item.background_path else None
        return cfg
