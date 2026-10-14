from __future__ import annotations

import os
import shutil
from typing import Callable

from PySide6.QtCore import (
    QFile, Qt, QThread, Signal, QObject, QRunnable, QThreadPool, QSize, QSettings, QRect, QRectF, QPoint, QPointF, QEvent,
    QPropertyAnimation, QEasingCurve, QTimer, QElapsedTimer,
)
from PySide6.QtGui import (
    QImage, QPixmap, QIcon, QColor, QPainter, QPen, QBrush, QLinearGradient, QCursor,
    QKeySequence, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QLineEdit,
    QScrollArea,
    QFrame,
    QFileDialog,
)

from core.processing import Operations, process_file, SUPPORTED_EXTENSIONS
from core.qimage import read_image
from core.config import CURRENT_VERSION, APP_NAME
from core.updater import (
    UpdateCheckWorker, DownloadWorker, run_installer, can_self_update,
)
from splash import SplashScreen
from preview import PreviewDialog
from dialogs import confirm, information, toast, warning, whats_new
from core.changelog import CHANGELOG, changes_since
from core.undo import UndoStack, UndoStep
from core.state import FolderState, OPERATION_DESCRIPTIONS, OPERATION_LABELS
from core.export import ExportWorker, same_folder, unique_path
from sidebar import SidebarPanel, glass_shadow
from core.watcher import FolderWatcher
from style import (
    STYLE_SHEET, enable_windows_acrylic_blur, set_windows_titlebar,
    ACCENT_COLOR, SUCCESS_COLOR,
)

THUMB_SIZE = 220
SCROLLBAR_RESERVE = 16
GRID_TOP = 26


def resource_path(filename: str) -> str:
    """Resolves a bundled resource both when run from source and when
    running as a PyInstaller --onefile exe (files are unpacked to a temp
    dir referenced by sys._MEIPASS at runtime).
    """
    import sys

    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, filename)


def list_images(folder: str) -> list[str]:
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    files = [
        n for n in names
        if os.path.splitext(n)[1].lower() in SUPPORTED_EXTENSIONS
        and os.path.isfile(os.path.join(folder, n))
    ]
    files.sort(key=str.lower)
    return files


def list_subfolders(folder: str) -> list[str]:
    """Subfolders that hold at least one image (e.g. the pages of a PDF)."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(
        (n for n in names if not n.startswith(".") and os.path.isdir(os.path.join(folder, n))
         and list_images(os.path.join(folder, n))),
        key=str.lower,
    )


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Czech plural: 1 soubor, 2 soubory, 5 souborů."""
    return f"{count} {one if count == 1 else few if 2 <= count <= 4 else many}"


def _images_word(count: int) -> str:
    if count == 1:
        return "obrázek"
    return "obrázky" if 2 <= count <= 4 else "obrázků"


_SELECT_STOPS = (QColor("#3fa9f5"), QColor(ACCENT_COLOR), QColor("#ff9f5a"))
_GLOW_HOVER = QColor(255, 255, 255)
_BADGE_COLOR = QColor(SUCCESS_COLOR)
CARD_PAD = 17
PLATE = 6
PLATE_RADIUS = 10
NAME_HEIGHT = 20


def _with_alpha(color: QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(max(0, min(255, alpha)))
    return c


def _selection_gradient(rect, alpha: int) -> QLinearGradient:
    """Blue -> purple -> orange, diagonally across `rect` (same hues as the app icon)."""
    rect = QRectF(rect)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    for position, color in zip((0.0, 0.5, 1.0), _SELECT_STOPS):
        grad.setColorAt(position, _with_alpha(color, alpha))
    return grad


_thumb_pool = QThreadPool()
_thumb_pool.setMaxThreadCount(max(2, min(8, (os.cpu_count() or 4))))


def _file_stamp(path: str) -> tuple[float, int] | None:
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


class _ThumbSignals(QObject):
    done = Signal(int, QImage, object)  # generation, image (null on failure), stamp


class _ThumbJob(QRunnable):
    """Decodes a thumbnail off the GUI thread. The reader decodes straight to
    the target size (JPEG shrinks during decoding), so even big photos are fast."""

    def __init__(self, path: str, generation: int, signals: _ThumbSignals):
        super().__init__()
        self.path = path
        self.generation = generation
        self.signals = signals

    def run(self) -> None:
        stamp = _file_stamp(self.path)
        image = QImage()
        if stamp is not None:
            image = read_image(self.path, QSize(THUMB_SIZE, THUMB_SIZE), upscale=True)
        try:
            self.signals.done.emit(self.generation, image, stamp)
        except RuntimeError:  # the card was deleted while loading
            pass


class ThumbnailCard(QWidget):
    """Clickable thumbnail painted by hand: the full image with square
    corners, a gradient glow when selected and a processed badge,
    on a white rounded plate."""

    toggled = Signal()

    def __init__(self, folder: str, filename: str, processed: bool):
        super().__init__()
        self.folder = folder
        self.filename = filename
        self.display_name = filename
        self.processed = processed
        self.operations: list[str] = []
        self.selected = False
        self._hovered = False
        self._pixmap: QPixmap | None = None
        self._stamp: tuple[float, int] | None = None
        self._placed = False
        self._anim: QPropertyAnimation | None = None
        self._retries = 0
        self._generation = 0
        self._loading = False
        self._signals = _ThumbSignals(self)
        self._signals.done.connect(self._on_loaded)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._request_load)
        self.setFixedSize(THUMB_SIZE + CARD_PAD * 2, THUMB_SIZE + CARD_PAD * 2 + NAME_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setToolTip(filename)
        self._request_load()

    @property
    def _path(self) -> str:
        return os.path.join(self.folder, self.filename)

    def _request_load(self) -> None:
        self._generation += 1
        self._loading = True
        _thumb_pool.start(_ThumbJob(self._path, self._generation, self._signals))

    def _on_loaded(self, generation: int, image: QImage, stamp) -> None:
        if generation != self._generation:
            return  # superseded by a newer request
        self._loading = False
        if not image.isNull():
            self._pixmap = QPixmap.fromImage(image)
            self._stamp = stamp
            self.update()
        # A file that was just copied in may still be locked or half written:
        # if it failed to load, or changed while we read it, look again shortly.
        changed = _file_stamp(self._path) != stamp
        if (image.isNull() or changed) and self._retries < 60:
            self._retries += 1
            self._retry_timer.start(250)
        else:
            self._retries = 0

    def move_to(self, target: QPoint, animate: bool) -> None:
        if self._anim is not None and self._anim.state() == QPropertyAnimation.Running:
            self._anim.setEndValue(target)
            return
        if not animate or not self._placed or not self.isVisible():
            self.move(target)
        elif self.pos() != target:
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setDuration(240)
            anim.setStartValue(self.pos())
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._anim = anim
        self._placed = True

    def reload_if_changed(self) -> None:
        if not self._loading and _file_stamp(self._path) != self._stamp:
            self._retries = 0
            self._request_load()

    def _image_area(self) -> QRect:
        """The square the image is fitted into."""
        return QRect(CARD_PAD, CARD_PAD, THUMB_SIZE, THUMB_SIZE)

    def _image_rect(self) -> QRect:
        area = self._image_area()
        if self._pixmap is None:
            return area
        size = self._pixmap.size()
        if size.width() > area.width() or size.height() > area.height():
            size = size.scaled(area.size(), Qt.KeepAspectRatio)
        # centred horizontally, sitting on the bottom edge: plates and names
        # in a row line up even when portraits and landscapes are mixed
        return QRect(
            area.left() + (area.width() - size.width()) // 2,
            area.bottom() + 1 - size.height(),
            size.width(), size.height(),
        )

    @staticmethod
    def _gradient(rect: QRect, alpha: int) -> QLinearGradient:
        return _selection_gradient(rect, alpha)

    def _paint_glow(self, painter: QPainter, rect: QRect, spread: int, peak: int, gradient: bool) -> None:
        painter.setPen(Qt.NoPen)
        for i in range(spread, 0, -1):
            alpha = int(peak * (1 - i / (spread + 1)) ** 2)
            layer = rect.adjusted(-i, -i, i, i)
            if gradient:
                painter.setBrush(QBrush(self._gradient(layer, alpha)))
            else:
                painter.setBrush(_with_alpha(_GLOW_HOVER, alpha))
            painter.drawRoundedRect(layer, PLATE_RADIUS + i, PLATE_RADIUS + i)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = self._image_rect()
        plate = rect.adjusted(-PLATE, -PLATE, PLATE, PLATE)

        if self.selected:
            self._paint_glow(painter, plate, spread=CARD_PAD - PLATE - 1, peak=115, gradient=True)
        elif self._hovered:
            self._paint_glow(painter, plate, spread=8, peak=50, gradient=False)
        self._paint_behind(painter, plate)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(plate, PLATE_RADIUS, PLATE_RADIUS)

        if self._pixmap is not None:
            painter.drawPixmap(rect, self._pixmap)
        else:
            painter.setPen(QColor(120, 120, 140))
            painter.drawText(rect, Qt.AlignCenter, "…" if self._loading or self._retries else "?")

        if self.selected:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QBrush(self._gradient(plate, 255)), 2))
            painter.drawRoundedRect(plate.adjusted(1, 1, -1, -1), PLATE_RADIUS, PLATE_RADIUS)

        if self.processed:
            badge = QRect(rect.right() - 22, rect.top() + 6, 20, 20)
            painter.setPen(Qt.NoPen)
            painter.setBrush(_BADGE_COLOR)
            painter.drawEllipse(badge)
            painter.setPen(QPen(QColor("white"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawPolyline([
                QPoint(badge.left() + 5, badge.top() + 10),
                QPoint(badge.left() + 9, badge.top() + 14),
                QPoint(badge.left() + 15, badge.top() + 6),
            ])

        if self.processed and self.operations:
            self._paint_operations(painter, rect)

        self._paint_overlay(painter, rect)

        name_rect = QRect(2, THUMB_SIZE + CARD_PAD * 2 - 8, self.width() - 4, NAME_HEIGHT)
        painter.setPen(QColor(241, 240, 250, 175))
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        elided = painter.fontMetrics().elidedText(self.display_name, Qt.ElideMiddle, name_rect.width())
        painter.drawText(name_rect, Qt.AlignHCenter | Qt.AlignTop, elided)

    def _paint_operations(self, painter: QPainter, rect: QRect) -> None:
        """One quiet pill in the bottom-left corner: "1024 · rámeček · jpg"."""
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        text = " · ".join(OPERATION_LABELS.get(op, op) for op in self.operations)
        text = metrics.elidedText(text, Qt.ElideRight, rect.width() - 28)
        pill = QRect(rect.left() + 6, rect.bottom() - 21, metrics.horizontalAdvance(text) + 14, 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(10, 8, 24, 150))
        painter.drawRoundedRect(pill, 8, 8)
        painter.setPen(QColor(255, 255, 255, 225))
        painter.drawText(pill, Qt.AlignCenter, text)

    def _paint_behind(self, painter: QPainter, plate: QRect) -> None:
        """Hook for subclasses: drawn under the plate."""

    def _paint_overlay(self, painter: QPainter, rect: QRect) -> None:
        """Hook for subclasses: drawn over the image."""

    def plate_rect(self) -> QRect:
        """The white plate in card coordinates - the clickable/selectable area."""
        return self._image_rect().adjusted(-PLATE, -PLATE, PLATE, PLATE)

    def set_processed(self, processed: bool, operations: list[str] | None = None) -> None:
        operations = operations or []
        if processed == self.processed and operations == self.operations:
            return
        self.processed = processed
        self.operations = operations
        tip = self.display_name
        if processed and operations:
            tip += "\nZpracováno: " + ", ".join(OPERATION_DESCRIPTIONS.get(op, op) for op in operations)
        self.setToolTip(tip)
        self.update()

    def is_checked(self) -> bool:
        return self.selected

    def set_checked(self, value: bool) -> None:
        if self.selected != value:
            self.selected = value
            self.update()
            self.toggled.emit()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)


class FolderCard(ThumbnailCard):
    """A subfolder in the grid: a little stack of plates showing its first
    image and how many images it holds. Clicking it opens the folder."""

    is_folder = True
    STACK = 4  # offset of each plate behind, in px

    def __init__(self, folder: str, dirname: str):
        self.dirname = dirname
        self.count = len(list_images(os.path.join(folder, dirname)))
        super().__init__(folder, dirname + "/", processed=False)
        self.display_name = dirname
        self.setToolTip(f"{dirname} – {self.count} {_images_word(self.count)} (otevřít kliknutím)")

    @property
    def _path(self) -> str:
        # the thumbnail is the folder's first image
        sub = os.path.join(self.folder, self.dirname)
        images = list_images(sub)
        return os.path.join(sub, images[0]) if images else sub

    def _image_area(self) -> QRect:
        # Shrunk by the stack's offset, so the plates behind (shifted up and
        # right) end where a single card's plate does and the grid stays even.
        inset = 2 * self.STACK
        return QRect(CARD_PAD, CARD_PAD + inset, THUMB_SIZE - inset, THUMB_SIZE - inset)

    def refresh_count(self) -> None:
        count = len(list_images(os.path.join(self.folder, self.dirname)))
        if count != self.count:
            self.count = count
            self.setToolTip(f"{self.dirname} – {count} {_images_word(count)} (otevřít kliknutím)")
            self.update()

    def _paint_behind(self, painter: QPainter, plate: QRect) -> None:
        painter.setPen(QPen(QColor(0, 0, 0, 40), 1))
        for depth, alpha in ((2, 120), (1, 190)):
            offset = depth * self.STACK
            painter.setBrush(QColor(255, 255, 255, alpha))
            painter.drawRoundedRect(plate.translated(offset, -offset), PLATE_RADIUS, PLATE_RADIUS)

    def _paint_overlay(self, painter: QPainter, rect: QRect) -> None:
        font = painter.font()
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        text = f"{self.count} {_images_word(self.count)}"
        width = painter.fontMetrics().horizontalAdvance(text) + 18
        pill = QRect(rect.right() - width - 6, rect.bottom() - 28, width, 22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 16, 44, 200))
        painter.drawRoundedRect(pill, 11, 11)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(pill, Qt.AlignCenter, text)
        font.setBold(False)
        painter.setFont(font)


ThumbnailCard.is_folder = False


class _Marquee(QWidget):
    """Translucent selection rectangle drawn above the cards."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._rect = QRect()
        self.hide()

    def set_rect(self, rect: QRect) -> None:
        self._rect = rect
        self.update()

    def paintEvent(self, event) -> None:
        if self._rect.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self._rect).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = _selection_gradient(rect, 60)
        edge = _selection_gradient(rect, 235)
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(QBrush(edge), 1.5))
        painter.drawRoundedRect(rect, 5, 5)


class GridCanvas(QWidget):
    """Holds the thumbnails and does the rubber-band selection. It does not
    receive the mouse itself: SelectionPanel forwards presses from anywhere in
    the panel, so dragging works over the whole container, not just the grid."""

    card_clicked = Signal(str)
    selection_changed = Signal()

    DRAG_THRESHOLD = 6
    EDGE = 28

    def __init__(self):
        super().__init__()
        self.cards_getter: Callable[[], dict[str, ThumbnailCard]] = dict
        self.scrollbar = None
        self.viewport = None
        self._press: QPoint | None = None
        self._press_card: str | None = None
        self._dragging = False
        self._additive = False
        self._base: set[str] = set()
        self._marquee = _Marquee(self)
        self._autoscroll = QTimer(self)
        self._autoscroll.setInterval(25)
        self._autoscroll.timeout.connect(self._autoscroll_tick)

    # -- helpers ----------------------------------------------------------------
    def _card_rect(self, card: "ThumbnailCard") -> QRect:
        return card.plate_rect().translated(card.pos())

    def _card_at(self, pos: QPoint) -> str | None:
        for name, card in self.cards_getter().items():
            if self._card_rect(card).contains(pos):
                return name
        return None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._marquee.setGeometry(self.rect())

    def is_active(self) -> bool:
        return self._press is not None

    def clamp_to_canvas(self, pos: QPoint) -> QPoint:
        return QPoint(max(0, min(self.width() - 1, pos.x())), max(0, min(self.height() - 1, pos.y())))

    def clamp_to_visible(self, pos: QPoint) -> QPoint:
        top = -self.pos().y()
        bottom = top + (self.viewport.height() if self.viewport is not None else self.height()) - 1
        return QPoint(max(0, min(self.width() - 1, pos.x())), max(top, min(bottom, pos.y())))

    # -- selection gesture (driven by SelectionPanel) ---------------------------
    def begin(self, raw: QPoint, additive: bool) -> None:
        self._press = self.clamp_to_visible(raw)
        self._press_card = self._card_at(raw) if self.rect().contains(raw) else None
        self._dragging = False
        self._additive = additive
        self._base = {n for n, c in self.cards_getter().items() if c.is_checked()} if additive else set()

    def drag_to(self, raw: QPoint) -> None:
        if self._press is None:
            return
        pos = self.clamp_to_canvas(raw)
        if not self._dragging:
            if (pos - self._press).manhattanLength() < self.DRAG_THRESHOLD:
                return
            self._dragging = True
            self._marquee.setGeometry(self.rect())
            self._marquee.raise_()
            self._marquee.show()
            self._autoscroll.start()
        rect = QRect(self._press, pos).normalized()
        self._marquee.set_rect(rect)
        hit = {n for n, c in self.cards_getter().items() if self._card_rect(c).intersects(rect)}
        wanted = self._base | hit
        for name, card in self.cards_getter().items():
            card.set_checked(name in wanted)
        self.selection_changed.emit()

    def end(self) -> None:
        if self._press is None:
            return
        if self._dragging:
            self._marquee.hide()
            self._marquee.set_rect(QRect())
        elif self._press_card is not None:
            card = self.cards_getter().get(self._press_card)
            if card is not None:
                if self._additive:
                    card.set_checked(not card.is_checked())
                    self.selection_changed.emit()
                else:
                    self.card_clicked.emit(self._press_card)
        elif not self._additive:
            for card in self.cards_getter().values():
                card.set_checked(False)
            self.selection_changed.emit()
        self._autoscroll.stop()
        self._press = None
        self._press_card = None
        self._dragging = False

    def _autoscroll_tick(self) -> None:
        if not self._dragging or self.scrollbar is None or self.viewport is None:
            return
        y = self.viewport.mapFromGlobal(QCursor.pos()).y()
        height = self.viewport.height()
        step = 0
        if y < self.EDGE:
            step = -max(4, (self.EDGE - y) // 2)
        elif y > height - self.EDGE:
            step = max(4, (y - (height - self.EDGE)) // 2)
        if step:
            self.scrollbar.setValue(self.scrollbar.value() + step)
            self.drag_to(self.mapFromGlobal(QCursor.pos()))


class SelectionPanel(QFrame):
    """The glass panel around the grid. Mouse presses on any empty part of it
    (padding, gaps, margins - children that handle the mouse, such as the
    buttons and the scrollbar, keep their own events) start a drag selection."""

    def __init__(self):
        super().__init__()
        self.canvas: GridCanvas | None = None

    def _canvas_pos(self, event) -> QPoint:
        return self.canvas.mapFrom(self, event.position().toPoint())

    def mousePressEvent(self, event) -> None:
        if self.canvas is not None and event.button() == Qt.LeftButton:
            additive = bool(event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
            self.canvas.begin(self._canvas_pos(event), additive)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.canvas is not None and self.canvas.is_active():
            self.canvas.drag_to(self._canvas_pos(event))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.canvas is not None and self.canvas.is_active() and event.button() == Qt.LeftButton:
            self.canvas.end()
            return
        super().mouseReleaseEvent(event)


class ProcessWorker(QThread):
    progress = Signal(str, bool, object)  # filename, success, ProcessResult or error (str)
    finished_all = Signal()

    def __init__(self, folder: str, filenames: list[str], ops: Operations, bordered: set[str],
                 step: UndoStep, entries: dict[str, dict | None]):
        super().__init__()
        self.folder = folder
        self.filenames = filenames
        self.ops = ops
        self.bordered = bordered  # files the state says already have a border
        self.step = step          # originals are copied here first, for undo
        self.entries = entries    # their folder-state entries, for undo

    def run(self) -> None:
        for filename in self.filenames:
            full_path = os.path.join(self.folder, filename)
            try:
                self.step.backup(full_path, self.entries.get(filename))
                result = process_file(full_path, self.ops, has_border=filename in self.bordered)
                self.step.set_results(full_path, result.paths)
                self.progress.emit(filename, True, result)
            except Exception as exc:  # noqa: BLE001
                self.step.discard(full_path)
                self.progress.emit(filename, False, str(exc))
        self.finished_all.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 780)
        icon_path = resource_path("icon.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.settings = QSettings("PhotoBatchEditor", "PhotoBatchEditor")
        self.folder: str | None = None
        self.root_folder: str = ""
        self.state: FolderState | None = None
        self.cards: dict[str, ThumbnailCard] = {}
        self._columns = 0
        self.watcher = FolderWatcher()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(60)  # coalesce bursts of events
        self._refresh_timer.timeout.connect(self.refresh_files)
        self.watcher.changed.connect(self._refresh_timer.start)
        self.worker: ProcessWorker | None = None
        self._prior_ops: dict[str, list[str]] = {}
        self.undo_stack = UndoStack()
        self._update_worker: UpdateCheckWorker | None = None
        self._download_worker: DownloadWorker | None = None
        self._process_step: UndoStep | None = None
        self._crop_step: UndoStep | None = None
        self._skipped_border = 0
        self.export_worker: ExportWorker | None = None
        self.export_folder: str = self.settings.value("export_folder", "", type=str)
        self._export_errors: list[str] = []
        self._export_count = 0
        self._export_recent: list[str] = []  # names moved this session, newest first
        self.export_watcher = FolderWatcher()
        self._export_timer = QTimer(self)
        self._export_timer.setSingleShot(True)
        self._export_timer.setInterval(150)
        self._export_timer.timeout.connect(self._refresh_export_preview)
        self.export_watcher.changed.connect(self._export_timer.start)

        self._build_ui()
        self._watch_export_folder()
        self.setAcceptDrops(True)
        QShortcut(QKeySequence.SelectAll, self, activated=self.select_all)
        QShortcut(QKeySequence(Qt.Key_Backspace), self, activated=self.go_up)
        QShortcut(QKeySequence.Delete, self, activated=self.delete_selected)
        QShortcut(QKeySequence.Undo, self, activated=self.undo_last)
        QShortcut(QKeySequence.Redo, self, activated=self.redo_last)  # Ctrl+Y
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo_last)
        self._restore_last_folder()

    # -- UI construction -------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("Background")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        root.addLayout(columns, stretch=1)

        columns.addWidget(self._build_folder_panel(), stretch=3)
        columns.addWidget(self._build_sidebar(), stretch=0)

        footer = QHBoxLayout()
        footer.setContentsMargins(6, 0, 6, 0)
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: rgba(241, 240, 250, 175); font-size: 12px;")
        version_btn = QPushButton(f"v{CURRENT_VERSION} · Co je nového")
        version_btn.setObjectName("LinkButton")
        version_btn.setCursor(Qt.PointingHandCursor)
        version_btn.setToolTip("Zobrazit novinky v této verzi")
        version_btn.clicked.connect(self.show_whats_new)
        self.update_btn = QPushButton(self.UPDATE_TEXT)
        self.update_btn.setObjectName("LinkButton")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.setToolTip("Zjistí, jestli na GitHubu není novější verze")
        self.update_btn.clicked.connect(self.check_for_updates)
        footer.addWidget(self.status_label)
        footer.addStretch(1)
        footer.addWidget(self.update_btn)
        footer.addWidget(version_btn)
        root.addLayout(footer)
        self._update_status()

    def _build_folder_panel(self) -> QFrame:
        folder_panel = SelectionPanel()
        folder_panel.setObjectName("GlassPanel")
        folder_panel.setGraphicsEffect(glass_shadow())
        layout = QVBoxLayout(folder_panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(10)
        self.choose_folder_btn = QPushButton("Vybrat složku…")
        self.choose_folder_btn.clicked.connect(self.choose_folder)
        folder_row.addWidget(self.choose_folder_btn)

        self.back_btn = QPushButton("← Zpět")
        self.back_btn.setToolTip("Zpět do nadřazené složky (Backspace)")
        self.back_btn.clicked.connect(self.go_up)
        self.back_btn.hide()
        folder_row.addWidget(self.back_btn)

        self.folder_path_edit = QLineEdit()
        self.folder_path_edit.setReadOnly(True)
        self.folder_path_edit.setPlaceholderText("Nevybrána žádná složka")
        folder_row.addWidget(self.folder_path_edit, stretch=1)

        self.add_files_btn = QPushButton("Přidat soubory…")
        self.add_files_btn.setToolTip("Zkopíruje soubory do složky (lze je sem i přetáhnout myší)")
        self.add_files_btn.clicked.connect(self.choose_files_to_add)
        folder_row.addWidget(self.add_files_btn)
        layout.addLayout(folder_row)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.viewport().installEventFilter(self)
        self.grid_container = GridCanvas()
        self.grid_container.setObjectName("Transparent")
        self.grid_container.cards_getter = lambda: self.cards
        self.grid_container.scrollbar = self.scroll_area.verticalScrollBar()
        self.grid_container.viewport = self.scroll_area.viewport()
        self.grid_container.card_clicked.connect(self._open_card)
        self.grid_container.selection_changed.connect(self._update_status)
        self.scroll_area.setWidget(self.grid_container)
        folder_panel.canvas = self.grid_container
        layout.addWidget(self.scroll_area, stretch=1)

        return folder_panel

    def _build_sidebar(self) -> SidebarPanel:
        self.sidebar = SidebarPanel(self.export_folder)
        self.sidebar.process_requested.connect(self.apply_to_selected)
        self.sidebar.undo_requested.connect(self.undo_last)
        self.sidebar.redo_requested.connect(self.redo_last)
        self.sidebar.select_all_requested.connect(self.select_all)
        self.sidebar.select_none_requested.connect(self.select_none)
        self.sidebar.clear_marks_requested.connect(self.reset_processed_marks)
        self.sidebar.delete_requested.connect(self.delete_selected)
        self.sidebar.choose_export_folder_requested.connect(self.choose_export_folder)
        self.sidebar.export_requested.connect(self.export_selected)
        self.sidebar.open_export_folder_requested.connect(self.open_export_folder)
        self.sidebar.export_item_clicked.connect(self._open_export_item)
        return self.sidebar

    # -- Folder handling ---------------------------------------------------
    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Vybrat složku s fotkami")
        if not folder:
            return
        self._set_folder(folder)

    def _restore_last_folder(self) -> None:
        last = self.settings.value("last_folder", "", type=str)
        if last and os.path.isdir(last):
            self._set_folder(last)

    def _set_folder(self, folder: str, subfolder: bool = False) -> None:
        """Shows `folder`. A subfolder opened from the grid keeps the chosen
        folder as the root that "Zpět" returns to."""
        folder = os.path.normpath(folder)
        if not subfolder:
            self.root_folder = folder
            self.settings.setValue("last_folder", folder)
        self.folder = folder
        self.state = FolderState(folder)
        self.folder_path_edit.setText(folder)
        self.back_btn.setVisible(not same_folder(folder, self.root_folder))
        for card in self.cards.values():
            card.hide()
            card.deleteLater()
        self.cards.clear()
        self.watcher.start(folder)
        self.refresh_files()

    def refresh_files(self) -> None:
        if not self.folder or not self.state:
            return
        filenames = list_images(self.folder)
        folders = [name + "/" for name in list_subfolders(self.folder)]
        existing = set(self.cards.keys())
        current = set(filenames) | set(folders)

        # Remove cards for files that disappeared.
        for name in existing - current:
            card = self.cards.pop(name)
            card.setParent(None)
            card.deleteLater()

        # Add cards for new files.
        for name in current - existing:
            if name.endswith("/"):
                card = FolderCard(self.folder, name[:-1])
            else:
                card = ThumbnailCard(self.folder, name, False)
                card.set_processed(self.state.is_processed(name), self.state.operations(name))
            card.toggled.connect(self._update_status)
            self.cards[name] = card

        # Update processed state for files that already have a card
        # (covers the case where an external edit invalidated the flag).
        for name in current & existing:
            card = self.cards[name]
            card.reload_if_changed()
            if card.is_folder:
                card.refresh_count()
            else:
                card.set_processed(self.state.is_processed(name), self.state.operations(name))

        self._relayout(force=True)
        self._update_status()

    # -- Undo -------------------------------------------------------------------
    def _refresh_undo(self) -> None:
        undo, redo = self.undo_stack.next_undo(), self.undo_stack.next_redo()
        self.sidebar.set_history(undo.label if undo else None, redo.label if redo else None)

    def undo_last(self) -> None:
        self._history_step(redo=False)

    def redo_last(self) -> None:
        self._history_step(redo=True)

    def _history_step(self, redo: bool) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        if (self.undo_stack.next_redo() if redo else self.undo_stack.next_undo()) is None:
            self._show_notice("Není co zopakovat." if redo else "Není co vrátit.")
            return
        states: dict[str, FolderState] = {}

        def state_for(folder: str) -> FolderState:
            if self.state is not None and same_folder(folder, self.folder):
                return self.state
            key = os.path.normcase(os.path.abspath(folder))
            return states.setdefault(key, FolderState(folder))

        action = self.undo_stack.redo if redo else self.undo_stack.undo
        step, restored, missing = action(state_for)
        self._refresh_undo()
        self.refresh_files()
        if missing:
            warning(self, "Něco nešlo " + ("zopakovat" if redo else "vrátit"),
                    "Tyto soubory se mezitím přesunuly nebo smazaly, a tak zůstaly, jak jsou:\n"
                    + "\n".join(missing))
        if restored:
            self._show_notice(("Znovu provedeno: " if redo else "Vráceno: ") + step.label)

    def closeEvent(self, event) -> None:
        self.undo_stack.close()
        super().closeEvent(event)

    # -- Updates -----------------------------------------------------------------
    UPDATE_TEXT = "Zkontrolovat aktualizace"

    def check_for_updates(self) -> None:
        if self._update_worker is not None and self._update_worker.isRunning():
            return
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Kontroluji…")
        self._update_worker = UpdateCheckWorker()
        self._update_worker.result.connect(self._on_update_checked)
        self._update_worker.start()

    def _reset_update_button(self) -> None:
        self.update_btn.setEnabled(True)
        self.update_btn.setText(self.UPDATE_TEXT)

    def _on_update_checked(self, info, error: str) -> None:
        self._reset_update_button()
        if error:
            self._show_notice(f"Aktualizace se nepodařilo ověřit – {error.lower()}.", "warning")
            return
        if info is None:
            self._show_notice(f"Máte nejnovější verzi (v{CURRENT_VERSION}).")
            return
        if not can_self_update():
            information(self, f"Je k dispozici verze {info.version}",
                        "Aktualizovat jde jen nainstalovaná aplikace. Stáhněte si nový instalátor z GitHubu.")
            return
        if confirm(self, f"Je k dispozici verze {info.version}",
                   f"Máte verzi {CURRENT_VERSION}. Stáhnout a nainstalovat novou verzi?\n\n"
                   "Aplikace se během instalace zavře a sama znovu spustí.",
                   "Aktualizovat"):
            self._download_update(info)

    def _download_update(self, info) -> None:
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Stahuji aktualizaci… 0 %")
        self._download_worker = DownloadWorker(info.url, info.size)
        self._download_worker.progress.connect(
            lambda percent: self.update_btn.setText(f"Stahuji aktualizaci… {percent} %"))
        self._download_worker.finished_ok.connect(self._on_update_downloaded)
        self._download_worker.failed.connect(self._on_update_failed)
        self._download_worker.start()

    def _on_update_downloaded(self, path: str) -> None:
        self.update_btn.setText("Instaluji…")
        run_installer(path)
        QTimer.singleShot(500, QApplication.instance().quit)

    def _on_update_failed(self, message: str) -> None:
        self._reset_update_button()
        warning(self, "Stažení selhalo", f"Aktualizaci se nepodařilo stáhnout.\n{message}")

    # -- What's new -----------------------------------------------------------
    def show_whats_new(self) -> None:
        whats_new(self, [entry for entry in CHANGELOG if entry[0] == CURRENT_VERSION] or CHANGELOG[:1])

    def show_whats_new_after_update(self) -> None:
        """Once per new version: what changed since the last version seen."""
        seen = self.settings.value("seen_version", "", type=str)
        if seen == CURRENT_VERSION:
            return
        self.settings.setValue("seen_version", CURRENT_VERSION)
        whats_new(self, changes_since(seen, CURRENT_VERSION))

    # -- Adding files ------------------------------------------------------
    def choose_files_to_add(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Přidat soubory do složky", "",
            f"Obrázky a PDF ({patterns});;Všechny soubory (*)",
        )
        if paths:
            self.add_files(paths)

    @staticmethod
    def _supported_drop(event) -> list[str]:
        if not event.mimeData().hasUrls():
            return []
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        return [p for p in paths if os.path.isfile(p) and os.path.splitext(p)[1].lower() in SUPPORTED_EXTENSIONS]

    def dragEnterEvent(self, event) -> None:
        if self._supported_drop(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = self._supported_drop(event)
        if paths:
            event.acceptProposedAction()
            self.add_files(paths)

    def add_files(self, paths: list[str]) -> None:
        if not self.folder:
            information(self, "Není vybrána složka", "Nejprve vyberte složku, kam se soubory přidají.")
            return
        errors, skipped = [], []
        for path in paths:
            name = os.path.basename(path)
            if os.path.splitext(name)[1].lower() not in SUPPORTED_EXTENSIONS:
                skipped.append(name)
                continue
            if same_folder(os.path.dirname(path), self.folder):
                continue  # already there
            try:
                shutil.copy2(path, unique_path(self.folder, name))
            except OSError as exc:
                errors.append(f"{name}: {exc}")
        self.refresh_files()
        if errors or skipped:
            lines = errors + [f"{name}: nepodporovaný formát" for name in skipped]
            warning(self, "Některé soubory se nepřidaly", "\n".join(lines))

    def _open_card(self, name: str) -> None:
        if not self.folder:
            return
        card = self.cards.get(name)
        if card is not None and card.is_folder:
            self._set_folder(os.path.join(self.folder, card.dirname), subfolder=True)
        else:
            dialog = PreviewDialog(self, os.path.join(self.folder, name))
            dialog.about_to_crop.connect(self._before_crop)
            dialog.crop_failed.connect(self._crop_failed)
            dialog.cropped.connect(self._on_cropped)
            dialog.exec()

    def _before_crop(self, path: str) -> None:
        self._crop_step = self.undo_stack.begin(f"ořez {os.path.basename(path)}", self.folder)
        entry = self.state.entry(os.path.basename(path)) if self.state else None
        try:
            self._crop_step.backup(path, entry)
        except OSError:
            pass  # no backup, no undo for this crop - the crop itself still works

    def _crop_failed(self, path: str) -> None:
        self._crop_step.discard(path)
        self.undo_stack.drop_if_empty(self._crop_step)

    def _on_cropped(self, path: str) -> None:
        self._crop_step.set_results(path, [path])
        self.undo_stack.drop_if_empty(self._crop_step)
        self._refresh_undo()
        if self.state and same_folder(os.path.dirname(path), self.folder):
            name = os.path.basename(path)
            self.state.mark_processed(name, self.state.operations(name) + ["crop"])
            self.refresh_files()

    def go_up(self) -> None:
        if self.folder and not same_folder(self.folder, self.root_folder):
            self._set_folder(os.path.dirname(self.folder), subfolder=True)

    def _relayout(self, force: bool = False) -> None:
        cell_w = THUMB_SIZE + CARD_PAD * 2
        cell_h = THUMB_SIZE + CARD_PAD * 2 + NAME_HEIGHT
        view_w = self.scroll_area.viewport().width()
        # Always reserve room for the vertical scrollbar, so the column count does
        # not flip when the scrollbar appears or disappears (e.g. after a reload).
        usable = self.scroll_area.width() - 2 * self.scroll_area.frameWidth() - SCROLLBAR_RESERVE
        columns = max(1, usable // cell_w)
        reflowed = columns != self._columns
        self._columns = columns

        # folders first, then files, each alphabetically
        names = sorted(self.cards.keys(), key=lambda n: (not self.cards[n].is_folder, n.lower()))
        used = min(columns, len(names))
        x0 = max(0, (view_w - used * cell_w) // 2)
        for index, name in enumerate(names):
            row, col = divmod(index, columns)
            card = self.cards[name]
            if card.parent() is not self.grid_container:
                card.setParent(self.grid_container)
                card.show()
            card.move_to(QPoint(x0 + col * cell_w, GRID_TOP + row * cell_h), animate=reflowed)
        rows = -(-len(names) // columns) if names else 0
        self.grid_container.setMinimumHeight(GRID_TOP + rows * cell_h)

    def eventFilter(self, obj, event) -> bool:
        # The grid must follow the scroll viewport's real width (it is only
        # final after the window is shown), not the main window's size.
        if obj is self.scroll_area.viewport() and event.type() == QEvent.Resize:
            self._relayout()
        return super().eventFilter(obj, event)

    # -- Selection helpers --------------------------------------------------
    def select_all(self) -> None:
        for card in self.cards.values():
            card.set_checked(True)
        self._update_status()

    def select_none(self) -> None:
        for card in self.cards.values():
            card.set_checked(False)
        self._update_status()

    def delete_selected(self) -> None:
        """Moves the selected files (and folders) to the Recycle Bin."""
        if not self.folder or self.worker is not None and self.worker.isRunning():
            return
        if self.export_worker is not None and self.export_worker.isRunning():
            return
        selected = [name for name, card in self.cards.items() if card.is_checked()]
        if not selected:
            return
        folders = sum(1 for n in selected if self.cards[n].is_folder)
        files = len(selected) - folders
        parts = ([_plural(files, "soubor", "soubory", "souborů")] if files else []) + \
                ([_plural(folders, "složku", "složky", "složek")] if folders else [])
        if not confirm(
            self, "Smazat vybrané?",
            f"Smaže se {' a '.join(parts)} ze složky\n{self.folder}\n\n"
            "Soubory se přesunou do Koše, odkud je jde obnovit.",
            "Smazat", danger=True,
        ):
            return
        errors = []
        for name in selected:
            path = os.path.join(self.folder, name.rstrip("/"))
            if QFile.moveToTrash(path):
                if self.state:
                    self.state.forget(name)
            else:
                errors.append(name.rstrip("/"))
        self.refresh_files()
        if errors:
            warning(self, "Některé soubory se nesmazaly",
                    "Nepodařilo se přesunout do Koše:\n" + "\n".join(errors))
        else:
            self._show_notice(f"Přesunuto do Koše: {_plural(len(selected), 'položka', 'položky', 'položek')}")

    def reset_processed_marks(self) -> None:
        if not self.state:
            return
        self.state.clear_all()
        for card in self.cards.values():
            card.set_processed(False)
        self._update_status()

    def _show_notice(self, text: str, kind: str = "info") -> None:
        toast(self, text, kind)

    def _update_status(self) -> None:
        folders = sum(1 for c in self.cards.values() if c.is_folder)
        total = len(self.cards) - folders
        selected = sum(1 for c in self.cards.values() if c.is_checked())
        processed = sum(1 for c in self.cards.values() if c.processed)
        parts = [f"{total} souborů"] + ([f"{folders} složek"] if folders else [])
        parts += [f"{selected} vybráno", f"{processed} zpracováno"]
        self.status_label.setText(" · ".join(parts))
        self.sidebar.set_selected_count(selected, len(self.cards))

    # -- Export ---------------------------------------------------------
    def choose_export_folder(self) -> None:
        start = self.export_folder if os.path.isdir(self.export_folder) else (self.folder or "")
        folder = QFileDialog.getExistingDirectory(self, "Vybrat cílovou složku exportu", start)
        if not folder:
            return
        self.export_folder = folder
        self.settings.setValue("export_folder", folder)
        self._export_recent = []
        self.sidebar.set_export_folder(folder)
        self._watch_export_folder()

    def _watch_export_folder(self) -> None:
        if self.export_folder and os.path.isdir(self.export_folder):
            self.export_watcher.start(self.export_folder)
        else:
            self.export_watcher.stop()

    def _refresh_export_preview(self) -> None:
        self.sidebar.show_export_preview(self.export_folder, self._export_recent)

    def open_export_folder(self) -> None:
        if self.export_folder and os.path.isdir(self.export_folder):
            os.startfile(self.export_folder)

    def _open_export_item(self, path: str) -> None:
        if os.path.isdir(path):
            os.startfile(path)
        elif os.path.isfile(path):
            PreviewDialog(self, path).exec()

    def export_selected(self) -> None:
        if not self.folder:
            information(self, "Není vybrána složka", "Nejprve vyberte složku s fotkami.")
            return
        selected = [name.rstrip("/") for name, card in self.cards.items() if card.is_checked()]
        if not selected:
            information(self, "Žádný výběr", "Vyberte alespoň jednu fotku.")
            return
        if not self.export_folder:
            self.choose_export_folder()
            if not self.export_folder:
                return
        if not os.path.isdir(self.export_folder):
            warning(self, "Cílová složka neexistuje", self.export_folder)
            return
        if same_folder(self.export_folder, self.folder):
            information(self, "Stejná složka", "Cílová složka je stejná jako zdrojová.")
            return

        self._export_errors = []
        self._export_count = 0
        self._export_moved: list[str] = []
        self.sidebar.set_exporting(True)
        self.export_worker = ExportWorker(self.folder, selected, self.export_folder)
        self.export_worker.progress.connect(self._on_file_exported)
        self.export_worker.finished_all.connect(self._on_export_finished)
        self.export_worker.start()

    def _on_file_exported(self, filename: str, success: bool, info: str) -> None:
        if success:
            self._export_count += 1
            self._export_moved.append(os.path.basename(info))
            if self.state:
                self.state.forget(filename)
        else:
            self._export_errors.append(f"{filename}: {info}")

    def _on_export_finished(self) -> None:
        self.sidebar.set_exporting(False)
        moved = self._export_moved
        self._export_recent = moved + [n for n in self._export_recent if n not in moved]
        self._refresh_export_preview()
        if self._export_errors:
            warning(
                self, "Export dokončen s chybami",
                f"Přesunuto: {self._export_count}\n\n" + "\n".join(self._export_errors),
            )
        else:
            target = os.path.basename(os.path.normpath(self.export_folder))
            self._show_notice(f"Odesláno do „{target}“: {_plural(self._export_count, 'soubor', 'soubory', 'souborů')}")

    # -- Processing -----------------------------------------------------
    def apply_to_selected(self) -> None:
        if not self.folder or not self.state:
            information(self, "Není vybrána složka", "Nejprve vyberte složku s fotkami.")
            return

        ops = self.sidebar.operations()
        if not ops.any:
            information(self, "Žádná akce", "Zaškrtněte alespoň jednu operaci.")
            return

        selected = [name for name, card in self.cards.items() if card.is_checked() and not card.is_folder]
        if not selected:
            information(self, "Žádný výběr", "Vyberte alespoň jednu fotku (složky se nezpracovávají).")
            return

        # what was done before (e.g. a crop) is kept and extended
        self._prior_ops = {name: self.state.operations(name) for name in selected}
        self._skipped_border = 0
        bordered = {name for name, done in self._prior_ops.items() if "border" in done}
        entries = {name: self.state.entry(name) for name in selected}
        self._process_step = self.undo_stack.begin(
            "zpracování " + _plural(len(selected), "fotky", "fotek", "fotek"), self.folder)
        self.sidebar.set_processing(True)
        self.worker = ProcessWorker(self.folder, selected, ops, bordered, self._process_step, entries)
        self.worker.progress.connect(self._on_file_processed)
        self.worker.finished_all.connect(self._on_processing_finished)
        self.worker.start()

    def _on_file_processed(self, filename: str, success: bool, info) -> None:
        if not success:
            warning(self, "Chyba při zpracování", f"{filename}: {info}")
            return
        if info.skipped_border:
            self._skipped_border += 1
        if self.state:
            done = self._prior_ops.get(filename, []) + info.applied
            if info.skipped_border:
                done.append("border")  # it has one, just not a second
            if filename not in (os.path.basename(p) for p in info.paths):
                self.state.forget(filename)
            # pages of a multi-page PDF land in a subfolder with its own state
            states: dict[str, FolderState] = {}
            for path in info.paths:
                folder = os.path.dirname(path)
                if same_folder(folder, self.folder):
                    state = self.state
                else:
                    state = states.setdefault(folder, FolderState(folder))
                state.mark_processed(os.path.basename(path), done)
        self.refresh_files()

    def _on_processing_finished(self) -> None:
        self.sidebar.set_processing(False)
        self.undo_stack.drop_if_empty(self._process_step)
        self._refresh_undo()
        self.refresh_files()
        if self._skipped_border:
            count = _plural(self._skipped_border, "fotka", "fotky", "fotek")
            had = "měla" if self._skipped_border == 1 else "měly"
            self._show_notice(f"Rámeček už {had} {count} – znovu jsem ho nepřidal.", "warning")


MIN_SPLASH_MS = 1300
STATE_PAUSE_MS = 500


class StartupController:
    """Splash -> update check -> (optional update) -> main window."""

    def __init__(self, app: QApplication, splash: SplashScreen, update_url: str | None = None):
        self.app = app
        self.splash = splash
        self.update_url = update_url
        self.window: MainWindow | None = None
        self._workers: list = []
        self._info = None
        self._clock = QElapsedTimer()
        splash.update_accepted.connect(self._download)
        splash.update_declined.connect(self._continue_to_app)

    def start(self) -> None:
        self._clock.start()
        self.splash.set_status("Kontroluji aktualizace…")
        self.splash.set_indeterminate()
        worker = UpdateCheckWorker(self.update_url)
        worker.result.connect(self._on_check)
        self._workers.append(worker)
        worker.start()

    def _on_check(self, info, error: str) -> None:
        wait = max(0, MIN_SPLASH_MS - self._clock.elapsed())
        QTimer.singleShot(wait, lambda: self._after_check(info, error))

    def _after_check(self, info, error: str) -> None:
        if info is not None and can_self_update():
            self._info = info
            self.splash.show_update_prompt(info.version)
            return
        if error:
            self.splash.set_status("Aktualizace se nepodařilo ověřit")
        elif info is not None:
            self.splash.set_status(f"Nová verze v{info.version} (aktualizace jen z instalace)")
        else:
            self.splash.set_status("Máte nejnovější verzi")
        self.splash.set_progress(35)
        QTimer.singleShot(STATE_PAUSE_MS, self._continue_to_app)

    def _download(self) -> None:
        self.splash.hide_update_prompt()
        self.splash.set_status("Stahuji aktualizaci… 0 %")
        self.splash.set_progress(0)
        worker = DownloadWorker(self._info.url, self._info.size)
        worker.progress.connect(self._on_progress)
        worker.finished_ok.connect(self._on_downloaded)
        worker.failed.connect(self._on_download_failed)
        self._workers.append(worker)
        worker.start()

    def _on_progress(self, percent: int) -> None:
        self.splash.set_progress(percent)
        self.splash.set_status(f"Stahuji aktualizaci… {percent} %")

    def _on_downloaded(self, path: str) -> None:
        self.splash.set_status("Instaluji aktualizaci…")
        run_installer(path)
        QTimer.singleShot(500, self.app.quit)

    def _on_download_failed(self, message: str) -> None:
        self.splash.set_status("Stažení selhalo, spouštím aktuální verzi")
        self.splash.set_indeterminate()
        QTimer.singleShot(1800, self._continue_to_app)

    def _continue_to_app(self) -> None:
        self.splash.hide_update_prompt()
        self.splash.set_status("Načítám aplikaci…")
        self.splash.set_progress(60)
        self.app.processEvents()
        self.window = MainWindow()
        self.splash.set_progress(100)
        self.splash.set_status("Hotovo")
        QTimer.singleShot(STATE_PAUSE_MS, lambda: self.splash.finish(self._reveal))

    def _reveal(self) -> None:
        self.window.show()
        enable_windows_acrylic_blur(int(self.window.winId()))
        set_windows_titlebar(int(self.window.winId()))
        QTimer.singleShot(450, self.window.show_whats_new_after_update)


def run() -> None:
    import sys

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(STYLE_SHEET)
    icon_path = resource_path("icon.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    splash = SplashScreen(icon_path)
    splash.show()
    controller = StartupController(app, splash)
    controller.start()
    sys.exit(app.exec())
