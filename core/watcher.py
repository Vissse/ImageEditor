"""Live folder watching, bridged into Qt via a signal.

watchdog runs its own background thread and calls our handler from that
thread, so we never touch Qt widgets there directly - we just emit a
signal, which Qt safely queues onto the GUI thread.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from core.processing import SUPPORTED_EXTENSIONS
from core.state import STATE_FILENAME
import os


def _is_relevant(path: str) -> bool:
    name = os.path.basename(path)
    if name == STATE_FILENAME:
        return False
    return os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS


class _Handler(FileSystemEventHandler):
    def __init__(self, bridge: "FolderWatcher"):
        self._bridge = bridge

    def on_any_event(self, event):
        if event.is_directory:
            return
        paths = [event.src_path]
        if hasattr(event, "dest_path") and event.dest_path:
            paths.append(event.dest_path)
        if any(_is_relevant(p) for p in paths):
            self._bridge.changed.emit()


class FolderWatcher(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._observer: Observer | None = None

    def start(self, folder: str) -> None:
        self.stop()
        self._observer = Observer()
        self._observer.schedule(_Handler(self), folder, recursive=False)
        self._observer.start()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
