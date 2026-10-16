"""Large-image popup opened by clicking a thumbnail; also hosts cropping."""
from __future__ import annotations

import os

from PIL import Image
from PySide6.QtCore import QPointF, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from core.processing import crop_file, detect_content_box, is_convert_only
from core.qimage import read_image
from dialogs import warning
from splash import _Panel

PLATE_PADDING = 12
PLATE_RADIUS = 14
HANDLE = 12        # grab distance around a crop corner/edge, in px
MIN_CROP = 8       # smallest crop rectangle, in displayed px


class _Plate(QWidget):
    """The same white rounded plate the thumbnails sit on, only bigger.
    In crop mode a frame around the whole image (as in Paint) is pulled in
    by its corner and edge handles and moved by dragging inside it."""

    selection_changed = Signal()

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self._crop_mode = False
        self._sel = QRectF()
        self._drag: str | None = None   # "move" or a combination of l/t/r/b
        self._anchor = QPointF()
        self._start_sel = QRectF()
        self.setMouseTracking(True)
        self.set_pixmap(pixmap)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.setFixedSize(
            pixmap.width() / pixmap.devicePixelRatio() + 2 * PLATE_PADDING,
            pixmap.height() / pixmap.devicePixelRatio() + 2 * PLATE_PADDING,
        )
        self._sel = QRectF()
        self.update()

    # -- geometry -------------------------------------------------------------
    def _image_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(PLATE_PADDING, PLATE_PADDING, -PLATE_PADDING, -PLATE_PADDING)

    def _clamp(self, pos: QPointF) -> QPointF:
        img = self._image_rect()
        return QPointF(min(max(pos.x(), img.left()), img.right()), min(max(pos.y(), img.top()), img.bottom()))

    def _hit(self, pos: QPointF) -> str | None:
        if self._sel.isEmpty():
            return None
        s = self._sel
        near = lambda a, b: abs(a - b) <= HANDLE  # noqa: E731
        inside_x = s.left() - HANDLE <= pos.x() <= s.right() + HANDLE
        inside_y = s.top() - HANDLE <= pos.y() <= s.bottom() + HANDLE
        edges = ""
        if inside_y and near(pos.x(), s.left()):
            edges += "l"
        elif inside_y and near(pos.x(), s.right()):
            edges += "r"
        if inside_x and near(pos.y(), s.top()):
            edges += "t"
        elif inside_x and near(pos.y(), s.bottom()):
            edges += "b"
        if edges:
            return edges
        return "move" if s.contains(pos) else None

    _CURSORS = {
        "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor, "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
        "lt": Qt.SizeFDiagCursor, "rb": Qt.SizeFDiagCursor, "rt": Qt.SizeBDiagCursor, "lb": Qt.SizeBDiagCursor,
        "move": Qt.SizeAllCursor,
    }

    # -- public API -------------------------------------------------------------
    def set_crop_mode(self, on: bool) -> None:
        # Like Paint: the crop frame starts around the whole image.
        self._crop_mode = on
        self._sel = self._image_rect() if on else QRectF()
        self._drag = None
        self.setCursor(Qt.ArrowCursor)
        self.update()
        self.selection_changed.emit()

    def set_selection_fraction(self, box: tuple[float, float, float, float]) -> None:
        img = self._image_rect()
        left, top, right, bottom = box
        self._sel = QRectF(
            QPointF(img.left() + left * img.width(), img.top() + top * img.height()),
            QPointF(img.left() + right * img.width(), img.top() + bottom * img.height()),
        )
        self.update()
        self.selection_changed.emit()

    def has_selection(self) -> bool:
        """True once the frame was pulled in from the full image."""
        if not self._crop_mode:
            return False
        img = self._image_rect()
        return any(abs(a - b) >= 0.5 for a, b in (
            (self._sel.left(), img.left()), (self._sel.top(), img.top()),
            (self._sel.right(), img.right()), (self._sel.bottom(), img.bottom()),
        ))

    def selection_fraction(self) -> tuple[float, float, float, float]:
        img = self._image_rect()
        s = self._sel.intersected(img)
        return (
            (s.left() - img.left()) / img.width(), (s.top() - img.top()) / img.height(),
            (s.right() - img.left()) / img.width(), (s.bottom() - img.top()) / img.height(),
        )

    def selection_pixels(self, full: QSize) -> QSize:
        left, top, right, bottom = self.selection_fraction()
        return QSize(round((right - left) * full.width()), round((bottom - top) * full.height()))

    # -- mouse ----------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if not self._crop_mode or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        self._drag = self._hit(event.position())
        self._anchor = self._clamp(event.position())
        self._start_sel = QRectF(self._sel)

    def mouseMoveEvent(self, event) -> None:
        if not self._crop_mode:
            return
        if self._drag is None:
            self.setCursor(self._CURSORS.get(self._hit(event.position()), Qt.ArrowCursor))
            return
        pos = self._clamp(event.position())
        img = self._image_rect()
        s = QRectF(self._start_sel)
        if self._drag == "move":
            moved = s.translated(pos - self._anchor)
            dx = max(img.left() - moved.left(), 0) + min(img.right() - moved.right(), 0)
            dy = max(img.top() - moved.top(), 0) + min(img.bottom() - moved.bottom(), 0)
            self._sel = moved.translated(dx, dy)
        else:  # resize from an edge or corner, never smaller than MIN_CROP
            if "l" in self._drag:
                s.setLeft(min(pos.x(), s.right() - MIN_CROP))
            if "r" in self._drag:
                s.setRight(max(pos.x(), s.left() + MIN_CROP))
            if "t" in self._drag:
                s.setTop(min(pos.y(), s.bottom() - MIN_CROP))
            if "b" in self._drag:
                s.setBottom(max(pos.y(), s.top() + MIN_CROP))
            self._sel = s
        self.update()
        self.selection_changed.emit()

    def mouseReleaseEvent(self, event) -> None:
        if self._crop_mode and event.button() == Qt.LeftButton:
            self._drag = None
            return
        super().mouseReleaseEvent(event)

    # -- painting ---------------------------------------------------------------
    def _handles(self) -> list[QPointF]:
        s = self._sel
        c = s.center()
        return [
            s.topLeft(), QPointF(c.x(), s.top()), s.topRight(),
            QPointF(s.right(), c.y()), s.bottomRight(), QPointF(c.x(), s.bottom()),
            s.bottomLeft(), QPointF(s.left(), c.y()),
        ]

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(QRectF(self.rect()), PLATE_RADIUS, PLATE_RADIUS)
        painter.drawPixmap(PLATE_PADDING, PLATE_PADDING, self._pixmap)

        if not self._crop_mode or self._sel.isEmpty():
            return
        img, s = self._image_rect(), self._sel
        outside = QPainterPath()
        outside.addRect(img)
        inner = QPainterPath()
        inner.addRect(s)
        painter.fillPath(outside.subtracted(inner), QColor(10, 8, 28, 160))

        if self._drag is not None:  # rule-of-thirds guides while adjusting
            painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
            for i in (1, 2):
                x = s.left() + s.width() * i / 3
                y = s.top() + s.height() * i / 3
                painter.drawLine(QPointF(x, s.top()), QPointF(x, s.bottom()))
                painter.drawLine(QPointF(s.left(), y), QPointF(s.right(), y))
        # dashed frame: dark under white, visible on any photo
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(20, 20, 30, 200), 1.5))
        painter.drawRect(s)
        dashed = QPen(QColor(255, 255, 255), 1.5, Qt.DashLine)
        painter.setPen(dashed)
        painter.drawRect(s)
        # round handles at the corners and edge midpoints, like Paint
        painter.setPen(QPen(QColor(40, 40, 60), 1.2))
        painter.setBrush(QColor(255, 255, 255))
        for point in self._handles():
            painter.drawEllipse(point, 5.5, 5.5)


class _CloseButton(QPushButton):
    def __init__(self):
        super().__init__()
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        hover = self.underMouse()
        painter.setPen(QPen(QColor(255, 255, 255, 90 if hover else 60), 1))
        painter.setBrush(QColor(255, 255, 255, 55 if hover else 28))
        painter.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        painter.setPen(QPen(QColor(255, 255, 255, 255 if hover else 215), 1.8, Qt.SolidLine, Qt.RoundCap))
        c, r = QRectF(self.rect()).center(), 4.6
        painter.drawLine(QPointF(c.x() - r, c.y() - r), QPointF(c.x() + r, c.y() + r))
        painter.drawLine(QPointF(c.x() - r, c.y() + r), QPointF(c.x() + r, c.y() - r))


def _header_button(text: str, handler, object_name: str = "") -> QPushButton:
    btn = QPushButton(text)
    if object_name:
        btn.setObjectName(object_name)
    btn.setCursor(Qt.PointingHandCursor)
    btn.clicked.connect(handler)
    return btn


class PreviewDialog(QDialog):
    about_to_crop = Signal(str)  # emitted right before the file is overwritten
    cropped = Signal(str)        # path of the file that was cropped and saved
    crop_failed = Signal(str)

    def __init__(self, parent: QWidget, path: str):
        super().__init__(parent)
        self.path = path
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)

        screen = (parent.screen() if parent is not None else QApplication.primaryScreen()).availableGeometry()
        # The dialog covers the whole parent window (dimmed), so a click anywhere
        # outside the panel lands on the dialog itself and can close it.
        area = parent.frameGeometry() if parent is not None else screen
        self._max_size = QSize(
            int(min(screen.width() * 0.78, area.width() * 0.9)) - 2 * PLATE_PADDING,
            int(min(screen.height() * 0.74, area.height() * 0.80)) - 2 * PLATE_PADDING,
        )
        pixmap = self._load_pixmap()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 28)
        panel = _Panel()
        self._shadow = QGraphicsDropShadowEffect(panel)
        self._shadow.setBlurRadius(34)
        self._shadow.setOffset(0, 10)
        self._shadow.setColor(QColor(0, 0, 0, 170))
        panel.setGraphicsEffect(self._shadow)
        outer.addStretch(1)
        outer.addWidget(panel, alignment=Qt.AlignCenter)
        outer.addStretch(1)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 14, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel(os.path.basename(path))
        title.setStyleSheet("font-size: 14px; font-weight: 600; color: #ffffff;")
        header.addWidget(title, stretch=1)
        self.size_label = QLabel()
        self.size_label.setStyleSheet("font-size: 12px; color: rgba(241, 240, 250, 160);")
        header.addWidget(self.size_label)
        self.smart_btn = _header_button("Chytrý ořez", self._smart_crop)
        self.crop_btn = _header_button("Oříznout", self._start_crop)
        self.cancel_btn = _header_button("Zrušit", self._cancel_crop)
        self.save_btn = _header_button("Uložit ořez", self._save_crop, "PrimaryButton")
        for btn in (self.smart_btn, self.crop_btn, self.cancel_btn, self.save_btn):
            header.addWidget(btn)
        close = _CloseButton()
        close.clicked.connect(self.accept)
        header.addWidget(close)
        layout.addLayout(header)

        self.plate: _Plate | None = None
        if pixmap.isNull():
            body = QLabel("Obrázek se nepodařilo načíst")
            body.setAlignment(Qt.AlignCenter)
            body.setMinimumSize(360, 220)
            layout.addWidget(body)
        else:
            self.plate = _Plate(pixmap)
            self.plate.selection_changed.connect(self._update_crop_ui)
            layout.addWidget(self.plate, alignment=Qt.AlignCenter)

        if self.plate is None:
            self.crop_btn.setEnabled(False)
            self.smart_btn.setEnabled(False)
        elif is_convert_only(path):
            self.crop_btn.setEnabled(False)
            self.smart_btn.setEnabled(False)
            self.crop_btn.setToolTip("Tento formát nejde oříznout – nejdřív ho převeďte na JPEG")
        else:
            self.crop_btn.setToolTip("Oříznout fotku tažením za úchyty rámečku (C)")
            self.smart_btn.setToolTip("Najde obrázek na jednobarevném pozadí a nastaví na něj rámeček (A)")
        self._smart_failed = False
        self._cropping = False
        self._update_crop_ui()

        if parent is not None:
            self.setGeometry(parent.frameGeometry())
        else:
            self.adjustSize()

        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(180)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)

    def _load_pixmap(self) -> QPixmap:
        self._full_size = QSize()
        image = read_image(self.path, self._max_size)
        if image.isNull():
            return QPixmap()
        try:  # the real pixel size, shown in the header
            with Image.open(self.path) as img:
                w, h = img.size
                if (img.getexif().get(0x0112) or 1) in (5, 6, 7, 8):  # rotated by EXIF
                    w, h = h, w
                self._full_size = QSize(w, h)
        except Exception:  # noqa: BLE001 - PDF and other formats Pillow cannot open
            pass
        return QPixmap.fromImage(image)

    # -- cropping -----------------------------------------------------------------
    def _start_crop(self) -> None:
        if self.plate is None or not self.crop_btn.isEnabled():
            return
        self._cropping = True
        self.plate.set_crop_mode(True)

    def _smart_crop(self) -> None:
        # Sets the frame onto the detected picture; the user checks it and saves.
        if self.plate is None or not self.smart_btn.isEnabled():
            return
        try:
            box = detect_content_box(self.path)
        except Exception:  # noqa: BLE001
            box = None
        if not self._cropping:
            self._start_crop()
        self._smart_failed = box is None
        if box is not None:
            self.plate.set_selection_fraction(box)
        self._update_crop_ui()

    def _cancel_crop(self) -> None:
        self._cropping = False
        self._smart_failed = False
        if self.plate is not None:
            self.plate.set_crop_mode(False)

    def _save_crop(self) -> None:
        if self.plate is None or not self.plate.has_selection():
            return
        self.about_to_crop.emit(self.path)
        try:
            crop_file(self.path, self.plate.selection_fraction())
        except Exception as exc:  # noqa: BLE001
            self.crop_failed.emit(self.path)
            warning(self, "Ořez se nepodařil", str(exc))
            return
        self.cropped.emit(self.path)
        self._cancel_crop()
        pixmap = self._load_pixmap()
        if not pixmap.isNull():
            self.plate.set_pixmap(pixmap)
        self._update_crop_ui()

    def _update_crop_ui(self) -> None:
        cropping = self._cropping
        self.crop_btn.setVisible(not cropping)
        self.cancel_btn.setVisible(cropping)
        self.save_btn.setVisible(cropping)
        has = self.plate is not None and self.plate.has_selection()
        self.save_btn.setEnabled(has)
        size = self._full_size
        if cropping and self._smart_failed and not has:
            self.size_label.setText("Pozadí k oříznutí nenalezeno")
        elif cropping and size.isValid():
            sel = self.plate.selection_pixels(size)
            self.size_label.setText(f"výřez {sel.width()} × {sel.height()} px")
        elif cropping:
            self.size_label.setText("Táhněte za úchyty rámečku")
        elif size.isValid():
            self.size_label.setText(f"{size.width()} × {size.height()} px")
        else:
            self.size_label.setText("")

    # -- events -------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(8, 6, 24, 140))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fade.start()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if self._cropping:
            if key == Qt.Key_Escape:
                self._cancel_crop()
            elif key in (Qt.Key_Return, Qt.Key_Enter):
                self._save_crop()
            elif key == Qt.Key_A:
                self._smart_crop()
            return
        if key in (Qt.Key_Escape, Qt.Key_Space):
            self.accept()
            return
        if key == Qt.Key_C:
            self._start_crop()
            return
        if key == Qt.Key_A:
            self._smart_crop()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        # A click on the dim margin around the panel closes the popup, too
        # (but not while cropping, where a slightly missed drag is common).
        if not self._cropping and not self.childAt(event.position().toPoint()):
            self.accept()
            return
        super().mousePressEvent(event)
