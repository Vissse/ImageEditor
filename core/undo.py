"""Undo / redo for edits that overwrite files (processing, cropping).

Before a file is changed, a copy of it goes to a private temp folder. Undoing
a step first copies aside what the step produced (so it can be redone), then
removes it and copies the originals back; redoing does the opposite. Copies
keep their modification time, so the folder state's "processed" flags and
operation lists come back exactly as they were. The temp folder is deleted
when the app closes.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field

UNDO_LIMIT = 10


@dataclass
class _Saved:
    path: str                # where the file lives when this side is active
    backup: str              # its copy in the step folder
    entry: dict | None       # its folder-state entry


@dataclass
class _Record:
    before: _Saved                                       # the file before the step
    results: list[str] = field(default_factory=list)     # what the step produced
    after: list[_Saved] = field(default_factory=list)    # copies of those, taken on undo


@dataclass
class UndoStep:
    label: str
    folder: str
    _dir: str
    records: dict[str, _Record] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _copy_aside(self, path: str, tag: str) -> str:
        target = os.path.join(self._dir, f"{tag}_{len(os.listdir(self._dir))}_{os.path.basename(path)}")
        shutil.copy2(path, target)
        return target

    def backup(self, path: str, state_entry: dict | None) -> None:
        """Copies `path` aside before it is changed (safe from a worker thread)."""
        with self._lock:
            self.records[path] = _Record(_Saved(path, self._copy_aside(path, "before"), state_entry))

    def set_results(self, original: str, results: list[str]) -> None:
        with self._lock:
            if original in self.records:
                self.records[original].results = list(results)

    def discard(self, original: str) -> None:
        """Forgets a file whose edit failed (nothing changed on disk)."""
        with self._lock:
            record = self.records.pop(original, None)
        if record is not None:
            _remove(record.before.backup)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class UndoStack:
    def __init__(self, limit: int = UNDO_LIMIT):
        self.limit = limit
        self._root = tempfile.mkdtemp(prefix="ImageEditor-undo-")
        self._done: list[UndoStep] = []
        self._undone: list[UndoStep] = []
        self._counter = 0

    # -- recording ----------------------------------------------------------------
    def begin(self, label: str, folder: str) -> UndoStep:
        """Starts a new step; a new edit makes the undone steps unredoable."""
        for step in self._undone:
            shutil.rmtree(step._dir, ignore_errors=True)
        self._undone.clear()
        self._counter += 1
        step_dir = os.path.join(self._root, str(self._counter))
        os.makedirs(step_dir)
        step = UndoStep(label, folder, step_dir)
        self._done.append(step)
        while len(self._done) > self.limit:
            shutil.rmtree(self._done.pop(0)._dir, ignore_errors=True)
        return step

    def drop_if_empty(self, step: UndoStep) -> None:
        if not step.records and step in self._done:
            self._done.remove(step)
            shutil.rmtree(step._dir, ignore_errors=True)

    def next_undo(self) -> UndoStep | None:
        return self._done[-1] if self._done else None

    def next_redo(self) -> UndoStep | None:
        return self._undone[-1] if self._undone else None

    # -- undo / redo -----------------------------------------------------------------
    def undo(self, state_for) -> tuple[UndoStep | None, int, list[str]]:
        """Puts the last step's files back as they were before it.
        `state_for(folder)` gives the FolderState to fix up. Returns the step,
        how many files were restored and the names that could not be (their
        result was moved or deleted in the meantime)."""
        if not self._done:
            return None, 0, []
        step = self._done.pop()
        restored, missing = 0, []
        for record in step.records.values():
            results = record.results or [record.before.path]
            if not all(os.path.exists(p) for p in results):
                missing.append(os.path.basename(record.before.path))
                continue
            # keep the edited version, for redo
            record.after = [
                _Saved(p, step._copy_aside(p, "after"), state_for(os.path.dirname(p)).entry(os.path.basename(p)))
                for p in results
            ]
            original_dir = os.path.dirname(record.before.path)
            for path in results:
                if not _same(path, record.before.path):
                    _remove(path)
                    state_for(os.path.dirname(path)).forget(os.path.basename(path))
            # pages of a PDF lived in a subfolder the step created
            for folder in {os.path.dirname(p) for p in results} - {original_dir}:
                shutil.rmtree(folder, ignore_errors=True)
            shutil.copy2(record.before.backup, record.before.path)
            state_for(original_dir).restore_entry(os.path.basename(record.before.path), record.before.entry)
            restored += 1
        self._undone.append(step)
        return step, restored, missing

    def redo(self, state_for) -> tuple[UndoStep | None, int, list[str]]:
        """Applies the last undone step again, from the copies taken on undo."""
        if not self._undone:
            return None, 0, []
        step = self._undone.pop()
        restored, missing = 0, []
        for record in step.records.values():
            if not record.after:
                continue  # it could not be undone, so there is nothing to redo
            if not os.path.exists(record.before.path):
                missing.append(os.path.basename(record.before.path))
                continue
            if not any(_same(saved.path, record.before.path) for saved in record.after):
                _remove(record.before.path)
                state_for(os.path.dirname(record.before.path)).forget(os.path.basename(record.before.path))
            for saved in record.after:
                os.makedirs(os.path.dirname(saved.path), exist_ok=True)
                shutil.copy2(saved.backup, saved.path)
                state_for(os.path.dirname(saved.path)).restore_entry(os.path.basename(saved.path), saved.entry)
            restored += 1
        self._done.append(step)
        return step, restored, missing

    def close(self) -> None:
        shutil.rmtree(self._root, ignore_errors=True)
