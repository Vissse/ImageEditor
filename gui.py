from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import (
    Qt, QThread, Signal, QObject, QRunnable, QThreadPool, QSize, QSettings, QRect, QRectF, QPoint, QPointF, QEvent,
    QPropertyAnimation, QEasingCurve, QTimer, QElapsedTimer,
)
from PySide6.QtGui import (
    QImage, QImageReader, QPixmap, QIcon, QColor, QPainter, QPen, QBrush, QLinearGradient, QCursor,
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
    QMessageBox,
)

from core.processing import Operations, process_file, SUPPORTED_EXTENSIONS
from core.config import CURRENT_VERSION, APP_NAME
from core.updater import (
    UpdateCheckWorker, DownloadWorker, run_installer, can_self_update,
)
from splash import SplashScreen
from preview import PreviewDialog
from core.state import FolderState
from core.export import ExportWorker, same_folder
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
            reader = QImageReader(self.path)
            size = reader.size()
            if size.isValid() and size.width() > 0 and size.height() > 0:
                size.scale(THUMB_SIZE, THUMB_SIZE, Qt.KeepAspectRatio)
                reader.setScaledSize(size)
            image = reader.read()
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
        self.processed = processed
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

    def _image_rect(self) -> QRect:
        if self._pixmap is None:
            return QRect(CARD_PAD, CARD_PAD, THUMB_SIZE, THUMB_SIZE)
        w, h = self._pixmap.width(), self._pixmap.height()
        return QRect(CARD_PAD + (THUMB_SIZE - w) // 2, CARD_PAD + (THUMB_SIZE - h) // 2, w, h)

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

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(plate, PLATE_RADIUS, PLATE_RADIUS)

        if self._pixmap is not None:
            painter.drawPixmap(rect.topLeft(), self._pixmap)
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

        name_rect = QRect(2, THUMB_SIZE + CARD_PAD * 2 - 8, self.width() - 4, NAME_HEIGHT)
        painter.setPen(QColor(241, 240, 250, 175))
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        elided = painter.fontMetrics().elidedText(self.filename, Qt.ElideMiddle, name_rect.width())
        painter.drawText(name_rect, Qt.AlignHCenter | Qt.AlignTop, elided)

    def plate_rect(self) -> QRect:
        """The white plate in card coordinates - the clickable/selectable area."""
        return self._image_rect().adjusted(-PLATE, -PLATE, PLATE, PLATE)

    def set_processed(self, processed: bool, repaint_only: bool = False) -> None:
        self.processed = processed
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
    progress = Signal(str, bool, str)  # filename, success, new_path_or_error
    finished_all = Signal()

    def __init__(self, folder: str, filenames: list[str], ops: Operations):
        super().__init__()
        self.folder = folder
        self.filenames = filenames
        self.ops = ops

    def run(self) -> None:
        for filename in self.filenames:
            full_path = os.path.join(self.folder, filename)
            try:
                new_path = process_file(full_path, self.ops)
                self.progress.emit(filename, True, new_path)
            except Exception as exc:  # noqa: BLE001
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
        self.export_worker: ExportWorker | None = None
        self.export_folder: str = self.settings.value("export_folder", "", type=str)
        self._export_errors: list[str] = []
        self._export_count = 0

        self._build_ui()
        QShortcut(QKeySequence.SelectAll, self, activated=self.select_all)
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
        version_label = QLabel(f"v{CURRENT_VERSION}")
        version_label.setStyleSheet("color: rgba(241, 240, 250, 120); font-size: 12px;")
        footer.addWidget(self.status_label)
        footer.addStretch(1)
        footer.addWidget(version_label)
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

        self.folder_path_edit = QLineEdit()
        self.folder_path_edit.setReadOnly(True)
        self.folder_path_edit.setPlaceholderText("Nevybrána žádná složka")
        folder_row.addWidget(self.folder_path_edit, stretch=1)
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
        self.grid_container.card_clicked.connect(self._show_preview)
        self.grid_container.selection_changed.connect(self._update_status)
        self.scroll_area.setWidget(self.grid_container)
        folder_panel.canvas = self.grid_container
        layout.addWidget(self.scroll_area, stretch=1)

        return folder_panel

    def _build_sidebar(self) -> SidebarPanel:
        self.sidebar = SidebarPanel(self.export_folder)
        self.sidebar.process_requested.connect(self.apply_to_selected)
        self.sidebar.select_all_requested.connect(self.select_all)
        self.sidebar.select_none_requested.connect(self.select_none)
        self.sidebar.clear_marks_requested.connect(self.reset_processed_marks)
        self.sidebar.choose_export_folder_requested.connect(self.choose_export_folder)
        self.sidebar.export_requested.connect(self.export_selected)
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

    def _set_folder(self, folder: str) -> None:
        self.folder = folder
        self.state = FolderState(folder)
        self.folder_path_edit.setText(folder)
        self.settings.setValue("last_folder", folder)
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
        existing = set(self.cards.keys())
        current = set(filenames)

        # Remove cards for files that disappeared.
        for name in existing - current:
            card = self.cards.pop(name)
            card.setParent(None)
            card.deleteLater()

        # Add cards for new files.
        for name in current - existing:
            processed = self.state.is_processed(name)
            card = ThumbnailCard(self.folder, name, processed)
            card.toggled.connect(self._update_status)
            self.cards[name] = card

        # Update processed state for files that already have a card
        # (covers the case where an external edit invalidated the flag).
        for name in current & existing:
            self.cards[name].reload_if_changed()
            self.cards[name].set_processed(self.state.is_processed(name))

        self._relayout(force=True)
        self._update_status()

    def _show_preview(self, filename: str) -> None:
        if self.folder:
            PreviewDialog(self, os.path.join(self.folder, filename)).exec()

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

        names = sorted(self.cards.keys(), key=str.lower)
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

    def reset_processed_marks(self) -> None:
        if not self.state:
            return
        self.state.clear_all()
        for card in self.cards.values():
            card.set_processed(False)
        self._update_status()

    def _update_status(self) -> None:
        total = len(self.cards)
        selected = sum(1 for c in self.cards.values() if c.is_checked())
        processed = sum(1 for c in self.cards.values() if c.processed)
        self.status_label.setText(f"{total} souborů · {selected} vybráno · {processed} zpracováno")
        self.sidebar.set_selected_count(selected)

    # -- Export ---------------------------------------------------------
    def choose_export_folder(self) -> None:
        start = self.export_folder if os.path.isdir(self.export_folder) else (self.folder or "")
        folder = QFileDialog.getExistingDirectory(self, "Vybrat cílovou složku exportu", start)
        if not folder:
            return
        self.export_folder = folder
        self.settings.setValue("export_folder", folder)
        self.sidebar.set_export_folder(folder)

    def export_selected(self) -> None:
        if not self.folder:
            QMessageBox.information(self, "Není vybrána složka", "Nejprve vyberte složku s fotkami.")
            return
        selected = [name for name, card in self.cards.items() if card.is_checked()]
        if not selected:
            QMessageBox.information(self, "Žádný výběr", "Vyberte alespoň jednu fotku.")
            return
        if not self.export_folder:
            self.choose_export_folder()
            if not self.export_folder:
                return
        if not os.path.isdir(self.export_folder):
            QMessageBox.warning(self, "Cílová složka neexistuje", self.export_folder)
            return
        if same_folder(self.export_folder, self.folder):
            QMessageBox.information(self, "Stejná složka", "Cílová složka je stejná jako zdrojová.")
            return

        self._export_errors = []
        self._export_count = 0
        self.sidebar.set_exporting(True)
        self.export_worker = ExportWorker(self.folder, selected, self.export_folder)
        self.export_worker.progress.connect(self._on_file_exported)
        self.export_worker.finished_all.connect(self._on_export_finished)
        self.export_worker.start()

    def _on_file_exported(self, filename: str, success: bool, info: str) -> None:
        if success:
            self._export_count += 1
        else:
            self._export_errors.append(f"{filename}: {info}")

    def _on_export_finished(self) -> None:
        self.sidebar.set_exporting(False)
        if self._export_errors:
            QMessageBox.warning(
                self, "Export dokončen s chybami",
                f"Odesláno: {self._export_count}\n\n" + "\n".join(self._export_errors),
            )
        else:
            self.status_label.setText(f"Odesláno {self._export_count} souborů do {self.export_folder}")

    # -- Processing -----------------------------------------------------
    def apply_to_selected(self) -> None:
        if not self.folder or not self.state:
            QMessageBox.information(self, "Není vybrána složka", "Nejprve vyberte složku s fotkami.")
            return

        ops = self.sidebar.operations()
        if not ops.any:
            QMessageBox.information(self, "Žádná akce", "Zaškrtněte alespoň jednu operaci.")
            return

        selected = [name for name, card in self.cards.items() if card.is_checked()]
        if not selected:
            QMessageBox.information(self, "Žádný výběr", "Vyberte alespoň jednu fotku.")
            return

        self.sidebar.set_processing(True)
        self.worker = ProcessWorker(self.folder, selected, ops)
        self.worker.progress.connect(self._on_file_processed)
        self.worker.finished_all.connect(self._on_processing_finished)
        self.worker.start()

    def _on_file_processed(self, filename: str, success: bool, info: str) -> None:
        if not success:
            QMessageBox.warning(self, "Chyba při zpracování", f"{filename}: {info}")
            return
        if self.state:
            new_name = os.path.basename(info)
            if new_name != filename:
                self.state.rename(filename, new_name)
            self.state.mark_processed(new_name)
        self.refresh_files()

    def _on_processing_finished(self) -> None:
        self.sidebar.set_processing(False)
        self.refresh_files()


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
