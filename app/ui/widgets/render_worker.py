"""Background workers for single and batch rendering.

Workers run on a ``QThread`` so the UI never blocks. Progress and log
updates are emitted as signals on the Qt event loop.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QObject, QThread, Signal

from app.core.batch_manager import BatchItem, BatchManager, BatchOptions
from app.core.renderer import RenderConfig, Renderer


class _SingleRenderWorker(QObject):
    progress = Signal(float, str)
    finished = Signal(bool, str)  # success, message

    def __init__(self, renderer: Renderer, config: RenderConfig):
        super().__init__()
        self.renderer = renderer
        self.config = config

    def run(self) -> None:
        try:
            out = self.renderer.render(
                self.config,
                on_progress=lambda p, m: self.progress.emit(p, m),
            )
            self.finished.emit(True, str(out))
        except Exception as e:  # noqa: BLE001
            self.finished.emit(False, str(e))


class SingleRenderController(QObject):
    """Owns the ``QThread`` so the page can ``start()`` and ``cancel()``."""

    progress = Signal(float, str)
    finished = Signal(bool, str)

    def __init__(self, renderer: Renderer, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._renderer = renderer
        self._worker: Optional[_SingleRenderWorker] = None
        self._thread: Optional[QThread] = None

    def start(self, config: RenderConfig) -> None:
        self.cancel()
        self._renderer.reset_cancel()
        self._thread = QThread()
        self._worker = _SingleRenderWorker(self._renderer, config)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.emit)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def cancel(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            self._renderer.cancel()

    def _on_finished(self, ok: bool, msg: str) -> None:
        self.finished.emit(ok, msg)
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(1500)
        self._thread = None
        self._worker = None


class BatchRenderController(QObject):
    """Wraps a :class:`BatchManager` for Qt signal/slot use."""

    item_changed = Signal(int, object)        # idx, BatchItem
    item_progress = Signal(int, float, str)   # idx, pct, message
    finished = Signal(object)                 # BatchResult

    def __init__(self, renderer: Renderer, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._renderer = renderer
        self._manager: Optional[BatchManager] = None

    def start(self, base_config: RenderConfig, options: BatchOptions,
              items: List[BatchItem]) -> None:
        self._manager = BatchManager(self._renderer, base_config, options)
        self._manager.start(
            items,
            on_item=lambda i, it: self.item_changed.emit(i, it),
            on_progress=lambda i, p, m: self.item_progress.emit(i, p, m),
            on_done=lambda result: self.finished.emit(result),
        )

    def cancel(self) -> None:
        if self._manager is not None:
            self._manager.cancel()

    def is_running(self) -> bool:
        return self._manager is not None and self._manager.is_running

    def preview_items(self, base_config: RenderConfig,
                       options: BatchOptions) -> List[BatchItem]:
        mgr = BatchManager(self._renderer, base_config, options)
        return mgr.build_items()
