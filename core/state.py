"""Persisted processing state for a watched folder.

Keeps a hidden JSON sidecar file inside the folder that remembers which
images were already processed (and their mtime at the time), so the
"processed" flag survives app restarts and is cleared automatically if the
file changes again on disk (re-edited outside the app).
"""
from __future__ import annotations

import json
import os
import threading

STATE_FILENAME = ".photobatch_state.json"


class FolderState:
    def __init__(self, folder: str):
        self.folder = folder
        self.path = os.path.join(folder, STATE_FILENAME)
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError:
            pass

    def _mtime(self, filename: str) -> float | None:
        full = os.path.join(self.folder, filename)
        try:
            return os.path.getmtime(full)
        except OSError:
            return None

    def is_processed(self, filename: str) -> bool:
        with self._lock:
            entry = self._data.get(filename)
            if not entry:
                return False
            current_mtime = self._mtime(filename)
            if current_mtime is None:
                return False
            # Any edit after it was marked processed invalidates the flag.
            return abs(current_mtime - entry.get("mtime", -1)) < 0.001

    def mark_processed(self, filename: str) -> None:
        with self._lock:
            mtime = self._mtime(filename)
            if mtime is None:
                return
            self._data[filename] = {"mtime": mtime}
            self._save()

    def forget(self, filename: str) -> None:
        with self._lock:
            if filename in self._data:
                del self._data[filename]
                self._save()

    def rename(self, old_name: str, new_name: str) -> None:
        with self._lock:
            if old_name in self._data:
                self._data[new_name] = self._data.pop(old_name)
                self._save()

    def clear_all(self) -> None:
        with self._lock:
            self._data = {}
            self._save()
