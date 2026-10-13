"""Large-image popup opened by the magnifier icon on a thumbnail."""
from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QPropertyAnimation, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImageReader, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from splash import _Panel

PLATE_PADDING = 12
PLATE_RADIUS = 14


class _Plate(QWidget):
    """The same white rounded plate the thumbnails sit on, only bigger."""

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self._pixmap = pixmap
        self.setFixedSize(
            pixmap.width() / pixmap.devicePixelRatio() + 2 * PLATE_PADDING,
            pixmap.height() / pixmap.devicePixelRatio() + 2 * PLATE_PADDING,
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawRoundedRect(QRectF(self.rect()), PLATE_RADIUS, PLATE_RADIUS)
        painter.drawPixmap(PLATE_PADDING, PLATE_PADDING, self._pixmap)


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


class PreviewDialog(QDialog):
    def __init__(self, parent: QWidget, path: str):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)

        screen = (parent.screen() if parent is not None else QApplication.primaryScreen()).availableGeometry()
        # The dialog covers the whole parent window (dimmed), so a click anywhere
        # outside the panel lands on the dialog itself and can close it.
        area = parent.frameGeometry() if parent is not None else screen
        max_w = int(min(screen.width() * 0.78, area.width() * 0.9)) - 2 * PLATE_PADDING
        max_h = int(min(screen.height() * 0.74, area.height() * 0.85)) - 2 * PLATE_PADDING

        reader = QImageReader(path)
        reader.setAutoTransform(True)
        original = reader.size()
        if original.isValid() and (original.width() > max_w or original.height() > max_h):
            reader.setScaledSize(original.scaled(QSize(max_w, max_h), Qt.KeepAspectRatio))
        image = reader.read()
        pixmap = QPixmap.fromImage(image) if not image.isNull() else QPixmap()

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
        title = QLabel(os.path.basename(path))
        title.setStyleSheet("font-size: 14px; font-weight: 600; color: #ffffff;")
        header.addWidget(title, stretch=1)
        close = _CloseButton()
        close.clicked.connect(self.accept)
        header.addWidget(close)
        layout.addLayout(header)

        if pixmap.isNull():
            body = QLabel("Obrázek se nepodařilo načíst")
            body.setAlignment(Qt.AlignCenter)
            body.setMinimumSize(360, 220)
            layout.addWidget(body)
        else:
            layout.addWidget(_Plate(pixmap), alignment=Qt.AlignCenter)

        if parent is not None:
            self.setGeometry(parent.frameGeometry())
        else:
            self.adjustSize()

        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(180)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(8, 6, 24, 140))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fade.start()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Escape, Qt.Key_Space):
            self.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        # A click on the dim margin around the panel closes the popup, too.
        if not self.childAt(event.position().toPoint()):
            self.accept()
            return
        super().mousePressEvent(event)
