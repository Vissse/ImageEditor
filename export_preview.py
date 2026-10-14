"""Small preview of the export folder in the sidebar: what is there, with the
files that were just moved first and highlighted."""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from core.processing import SUPPORTED_EXTENSIONS
from core.qimage import read_image
from style import ACCENT_COLOR

COLUMNS = 4
MAX_ITEMS = 8
MINI_SIZE = 58
MINI_PAD = 3

_pool = QThreadPool()
_pool.setMaxThreadCount(2)


def _first_image(folder: str) -> str | None:
    try:
        names = sorted(os.listdir(folder), key=str.lower)
    except OSError:
        return None
    for name in names:
        if os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS and os.path.isfile(os.path.join(folder, name)):
            return os.path.join(folder, name)
    return None


def folder_entries(folder: str, recent: list[str]) -> list[str]:
    """Names of images and image subfolders in `folder`: those in `recent`
    (just moved, newest first) lead, the rest follow by modification time."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    entries = []
    for name in names:
        path = os.path.join(folder, name)
        if name.startswith("."):
            continue
        if os.path.isfile(path) and os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS:
            entries.append(name)
        elif os.path.isdir(path) and _first_image(path):
            entries.append(name)
    present = set(entries)
    lead = [n for n in recent if n in present]
    rest = sorted(
        (n for n in entries if n not in set(lead)),
        key=lambda n: os.path.getmtime(os.path.join(folder, n)), reverse=True,
    )
    return lead + rest


class _Signals(QObject):
    done = Signal(int, QImage)


class _Job(QRunnable):
    def __init__(self, path: str, generation: int, signals: _Signals):
        super().__init__()
        self.path, self.generation, self.signals = path, generation, signals

    def run(self) -> None:
        image = read_image(self.path, QSize(MINI_SIZE * 2, MINI_SIZE * 2))
        try:
            self.signals.done.emit(self.generation, image)
        except RuntimeError:  # widget deleted meanwhile
            pass


class _MiniThumb(QWidget):
    """A small white plate with the image (or a folder's first image as a
    little stack); `fresh` items get the accent outline."""

    clicked = Signal(str)

    def __init__(self, path: str, fresh: bool):
        super().__init__()
        self.path = path
        self.fresh = fresh
        self.is_folder = os.path.isdir(path)
        self._pixmap: QPixmap | None = None
        self._generation = 0
        self._signals = _Signals(self)
        self._signals.done.connect(self._on_loaded)
        self.setFixedSize(MINI_SIZE, MINI_SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(os.path.basename(path) + (" (složka)" if self.is_folder else ""))
        source = _first_image(path) if self.is_folder else path
        if source:
            _pool.start(_Job(source, self._generation, self._signals))

    def _on_loaded(self, generation: int, image: QImage) -> None:
        if generation == self._generation and not image.isNull():
            self._pixmap = QPixmap.fromImage(image)
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.path)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        stack = 3 if self.is_folder else 0
        plate = QRectF(1, 1 + 2 * stack, MINI_SIZE - 2 - 2 * stack, MINI_SIZE - 2 - 2 * stack)

        painter.setPen(Qt.NoPen)
        for depth in (2, 1)[: 2 if stack else 0]:
            painter.setBrush(QColor(255, 255, 255, 90 * (3 - depth)))
            painter.drawRoundedRect(plate.translated(depth * stack, -depth * stack), 7, 7)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(plate, 7, 7)

        inner = plate.adjusted(MINI_PAD, MINI_PAD, -MINI_PAD, -MINI_PAD).toRect()
        if self._pixmap is not None:
            scaled = self._pixmap.scaled(inner.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = inner.left() + (inner.width() - scaled.width()) // 2
            y = inner.top() + (inner.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)

        if self.fresh:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(ACCENT_COLOR), 2.5))
            painter.drawRoundedRect(plate.adjusted(1, 1, -1, -1), 7, 7)


class ExportPreview(QWidget):
    """Grid of the newest items in the export folder plus a short summary."""

    item_clicked = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(8)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(10)
        layout.addLayout(self._grid)

        self.caption = QLabel()
        self.caption.setObjectName("Hint")
        layout.addWidget(self.caption)
        self._items: list[_MiniThumb] = []

    def show_folder(self, folder: str, recent: list[str]) -> None:
        for item in self._items:
            item.setParent(None)
            item.deleteLater()
        self._items = []
        if not folder or not os.path.isdir(folder):
            self.caption.setText("" if not folder else "cílová složka neexistuje")
            return

        entries = folder_entries(folder, recent)
        fresh = set(recent)
        new_count = sum(1 for n in entries if n in fresh)
        hidden = len(entries) - MAX_ITEMS
        parts = []
        if new_count:
            parts.append(f"{new_count} nově přesunuto")
        parts.append(f"{len(entries)} ve složce" if entries else "složka je prázdná")
        if hidden > 0:
            parts.append(f"+{hidden} dalších")
        self.caption.setText(" · ".join(parts))

        for index, name in enumerate(entries[:MAX_ITEMS]):
            item = _MiniThumb(os.path.join(folder, name), name in fresh)
            item.clicked.connect(self.item_clicked.emit)
            row, col = divmod(index, COLUMNS)
            self._grid.addWidget(item, row, col, Qt.AlignLeft)
            self._items.append(item)
