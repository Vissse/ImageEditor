from __future__ import annotations

import os

from PySide6.QtCore import (
    Qt, QThread, Signal, QSize, QSettings, QRect, QPoint, QEvent,
    QPropertyAnimation, QEasingCurve, QTimer,
)
from PySide6.QtGui import (
    QPixmap, QIcon, QColor, QPainter, QPen, QBrush, QLinearGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QCheckBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QFrame,
    QFileDialog,
    QStatusBar,
    QSizePolicy,
    QMessageBox,
    QGraphicsDropShadowEffect,
)

from core.processing import Operations, process_file, SUPPORTED_EXTENSIONS
from core.config import CURRENT_VERSION
from core.state import FolderState
from core.watcher import FolderWatcher
from style import (
    STYLE_SHEET, enable_windows_acrylic_blur, set_windows_titlebar,
    ACCENT_COLOR, ACCENT_COLOR_2, SUCCESS_COLOR,
)

THUMB_SIZE = 220
SCROLLBAR_RESERVE = 16


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


def _glass_shadow(blur: int = 24, alpha: int = 90, y_offset: int = 6) -> QGraphicsDropShadowEffect:
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(0, 0, 0, alpha))
    return effect


_GLOW_A = QColor(ACCENT_COLOR)
_GLOW_B = QColor(ACCENT_COLOR_2)
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
        self._recheck_timer = QTimer(self)
        self._recheck_timer.setSingleShot(True)
        self._recheck_timer.timeout.connect(self._recheck)
        self.setFixedSize(THUMB_SIZE + CARD_PAD * 2, THUMB_SIZE + CARD_PAD * 2 + NAME_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setToolTip(filename)
        self._load_thumbnail()

    @property
    def _path(self) -> str:
        return os.path.join(self.folder, self.filename)

    def _file_stamp(self) -> tuple[float, int] | None:
        try:
            st = os.stat(self._path)
            return (st.st_mtime, st.st_size)
        except OSError:
            return None

    def _load_thumbnail(self) -> None:
        self._stamp = self._file_stamp()
        self._pixmap = None
        pixmap = QPixmap(self._path)
        if not pixmap.isNull():
            self._pixmap = pixmap.scaled(
                THUMB_SIZE, THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        # A file that was just copied in may still be locked or half written,
        # so look again shortly until it loads and its size/mtime stop changing.
        if self._pixmap is not None or self._retries < 60:
            self._retries += 1
            self._recheck_timer.start(800)

    def _recheck(self) -> None:
        stamp = self._file_stamp()
        if stamp is None:
            return
        if self._pixmap is None or stamp != self._stamp:
            self._load_thumbnail()
            self.update()

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
        if self._file_stamp() != self._stamp:
            self._retries = 0
            self._load_thumbnail()
            self.update()

    def _image_rect(self) -> QRect:
        if self._pixmap is None:
            return QRect(CARD_PAD, CARD_PAD, THUMB_SIZE, THUMB_SIZE)
        w, h = self._pixmap.width(), self._pixmap.height()
        return QRect(CARD_PAD + (THUMB_SIZE - w) // 2, CARD_PAD + (THUMB_SIZE - h) // 2, w, h)

    @staticmethod
    def _gradient(rect: QRect, a: QColor, b: QColor, alpha_a: int, alpha_b: int) -> QLinearGradient:
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, _with_alpha(a, alpha_a))
        grad.setColorAt(1.0, _with_alpha(b, alpha_b))
        return grad

    def _paint_glow(self, painter: QPainter, rect: QRect, spread: int, peak: int, gradient: bool) -> None:
        painter.setPen(Qt.NoPen)
        for i in range(spread, 0, -1):
            alpha = int(peak * (1 - i / (spread + 1)) ** 2)
            layer = rect.adjusted(-i, -i, i, i)
            if gradient:
                painter.setBrush(QBrush(self._gradient(layer, _GLOW_A, _GLOW_B, alpha, alpha)))
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
            painter.drawText(rect, Qt.AlignCenter, "?")

        if self.selected:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QBrush(self._gradient(plate, _GLOW_A, _GLOW_B, 255, 255)), 2))
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

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.selected = not self.selected
            self.update()
            self.toggled.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)


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
        self.setWindowTitle("Photo Batch Editor")
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
        self.watcher.changed.connect(self.refresh_files)
        self.worker: ProcessWorker | None = None

        self._build_ui()
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
        columns.addWidget(self._build_options_panel(), stretch=0)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        version_label = QLabel(f"v{CURRENT_VERSION}")
        version_label.setStyleSheet("color: rgba(255, 255, 255, 120); padding-right: 6px;")
        self.status_bar.addPermanentWidget(version_label)
        self._update_status()

    def _build_folder_panel(self) -> QFrame:
        folder_panel = QFrame()
        folder_panel.setObjectName("GlassPanel")
        folder_panel.setGraphicsEffect(_glass_shadow())
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
        self.grid_container = QWidget()
        self.grid_container.setObjectName("Transparent")
        self.scroll_area.setWidget(self.grid_container)
        layout.addWidget(self.scroll_area, stretch=1)

        return folder_panel

    def _build_options_panel(self) -> QFrame:
        ops_panel = QFrame()
        ops_panel.setObjectName("GlassPanel")
        ops_panel.setFixedWidth(300)
        ops_panel.setGraphicsEffect(_glass_shadow())
        layout = QVBoxLayout(ops_panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        ops_title = QLabel("Operace")
        ops_title.setObjectName("Title")
        layout.addWidget(ops_title)

        self.op_resize = QCheckBox("Změnit velikost na 1024 px")
        self.op_resize.setChecked(True)
        self.op_resize.setEnabled(False)
        self.op_resize.setToolTip("Vždy zapnuto")
        self.op_border = QCheckBox("Přidat černý rámeček (1 px)")
        self.op_jpeg = QCheckBox("Převést na JPEG")
        layout.addWidget(self.op_resize)
        layout.addWidget(self.op_border)
        layout.addWidget(self.op_jpeg)
        self.apply_btn = QPushButton("Zpracovat vybrané")
        self.apply_btn.setObjectName("PrimaryButton")
        self.apply_btn.setGraphicsEffect(_glass_shadow(blur=28, alpha=110, y_offset=4))
        self.apply_btn.clicked.connect(self.apply_to_selected)
        layout.addSpacing(6)
        layout.addWidget(self.apply_btn)

        layout.addSpacing(18)
        selection_title = QLabel("Výběr")
        selection_title.setObjectName("Title")
        layout.addWidget(selection_title)

        self.select_all_btn = QPushButton("Vybrat vše")
        self.select_all_btn.clicked.connect(self.select_all)
        layout.addWidget(self.select_all_btn)

        self.select_none_btn = QPushButton("Zrušit výběr")
        self.select_none_btn.clicked.connect(self.select_none)
        layout.addWidget(self.select_none_btn)

        self.reset_processed_btn = QPushButton("Vymazat značky zpracování")
        self.reset_processed_btn.clicked.connect(self.reset_processed_marks)
        layout.addWidget(self.reset_processed_btn)

        layout.addStretch(1)
        return ops_panel

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
            card.move_to(QPoint(x0 + col * cell_w, row * cell_h), animate=reflowed)
        rows = -(-len(names) // columns) if names else 0
        self.grid_container.setMinimumHeight(rows * cell_h)

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
        self.status_bar.showMessage(
            f"{total} souborů · {selected} vybráno · {processed} zpracováno"
        )

    # -- Processing -----------------------------------------------------
    def apply_to_selected(self) -> None:
        if not self.folder or not self.state:
            QMessageBox.information(self, "Není vybrána složka", "Nejprve vyberte složku s fotkami.")
            return

        ops = Operations(
            resize=True,
            border=self.op_border.isChecked(),
            to_jpeg=self.op_jpeg.isChecked(),
        )
        if not ops.any:
            QMessageBox.information(self, "Žádná akce", "Zaškrtněte alespoň jednu operaci.")
            return

        selected = [name for name, card in self.cards.items() if card.is_checked()]
        if not selected:
            QMessageBox.information(self, "Žádný výběr", "Vyberte alespoň jednu fotku.")
            return

        self.apply_btn.setEnabled(False)
        self.apply_btn.setText("Zpracovávám…")
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

    def _on_processing_finished(self) -> None:
        self.apply_btn.setEnabled(True)
        self.apply_btn.setText("Zpracovat vybrané")
        self.refresh_files()


def run() -> None:
    import sys

    app = QApplication(sys.argv)
    app.setApplicationName("Photo Batch Editor")
    app.setStyleSheet(STYLE_SHEET)
    icon_path = resource_path("icon.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow()
    window.show()
    enable_windows_acrylic_blur(int(window.winId()))
    set_windows_titlebar(int(window.winId()))
    sys.exit(app.exec())
