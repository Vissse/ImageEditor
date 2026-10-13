"""Copying selected photos into another folder."""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import QThread, Signal


def unique_path(folder: str, filename: str) -> str:
    """folder/filename, or folder/name (2).ext etc. if it already exists."""
    stem, ext = os.path.splitext(filename)
    path = os.path.join(folder, filename)
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return path


def same_folder(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


class ExportWorker(QThread):
    progress = Signal(str, bool, str)  # filename, success, new_path_or_error
    finished_all = Signal()

    def __init__(self, folder: str, filenames: list[str], target: str):
        super().__init__()
        self.folder = folder
        self.filenames = filenames
        self.target = target

    def run(self) -> None:
        for filename in self.filenames:
            try:
                dest = unique_path(self.target, filename)
                shutil.copy2(os.path.join(self.folder, filename), dest)
                self.progress.emit(filename, True, dest)
            except Exception as exc:  # noqa: BLE001
                self.progress.emit(filename, False, str(exc))
        self.finished_all.emit()
