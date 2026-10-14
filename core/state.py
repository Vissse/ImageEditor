"""Persisted processing state for a watched folder.

Keeps a hidden JSON sidecar file inside the folder that remembers which
images were already processed, what was done to them (see OPERATION_LABELS)
and their mtime at the time, so the
"processed" flag survives app restarts and is cleared automatically if the
file changes again on disk (re-edited outside the app).
"""
from __future__ import annotations

import json
import os
import threading

STATE_FILENAME = ".photobatch_state.json"

# Operation ids stored per file, in display order, with their short labels.
OPERATION_LABELS = {
    "pdf": "pdf",
    "crop": "ořez",
    "resize": "1024",
    "border": "rámeček",
    "jpeg": "jpg",
}
OPERATION_DESCRIPTIONS = {
    "pdf": "převedeno z PDF",
    "crop": "oříznuto",
    "resize": "zmenšeno na max. 1024 px",
    "border": "černý rámeček",
    "jpeg": "převedeno na JPEG",
}


def ordered_operations(ops) -> list[str]:
    ops = set(ops)
    return [op for op in OPERATION_LABELS if op in ops]


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

    def mark_processed(self, filename: str, ops=()) -> None:
        with self._lock:
            mtime = self._mtime(filename)
            if mtime is None:
                return
            self._data[filename] = {"mtime": mtime, "ops": ordered_operations(ops)}
            self._save()

    def operations(self, filename: str) -> list[str]:
        """What was done to the file; empty unless it is still marked processed."""
        if not self.is_processed(filename):
            return []
        with self._lock:
            return list(self._data.get(filename, {}).get("ops", []))

    def forget(self, filename: str) -> None:
        with self._lock:
            if filename in self._data:
                del self._data[filename]
                self._save()

    def entry(self, filename: str) -> dict | None:
        """A copy of the raw entry (for undo)."""
        with self._lock:
            entry = self._data.get(filename)
            return dict(entry) if entry else None

    def restore_entry(self, filename: str, entry: dict | None) -> None:
        with self._lock:
            if entry:
                self._data[filename] = dict(entry)
            else:
                self._data.pop(filename, None)
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
