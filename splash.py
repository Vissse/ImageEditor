"""Startup splash: popping logo, shimmering progress bar and the update prompt."""
from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import (
    Qt, QPoint, QPointF, QRectF, QSize, QTimer, QVariantAnimation, QEasingCurve,
    QPropertyAnimation, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from core.config import APP_NAME, CURRENT_VERSION
from style import ACCENT_COLOR, ACCENT_COLOR_2

LOGO_SIZE = 128
LOGO_BOX = 190


class LogoWidget(QWidget):
    """Logo that pops in (scale overshoot + fade) over a softly pulsing glow."""

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self._pixmap = pixmap
        self._scale = 0.0
        self._opacity = 0.0
        self._pulse = 0.0
        self.setFixedSize(LOGO_BOX, LOGO_BOX)

        self._pop = QVariantAnimation(self)
        self._pop.setStartValue(0.0)
        self._pop.setEndValue(1.0)
        self._pop.setDuration(700)
        self._pop.setEasingCurve(QEasingCurve.OutBack)
        self._pop.valueChanged.connect(self._on_pop)

        self._glow = QVariantAnimation(self)
        self._glow.setStartValue(0.0)
        self._glow.setKeyValueAt(0.5, 1.0)
        self._glow.setEndValue(0.0)
        self._glow.setDuration(1800)
        self._glow.setLoopCount(-1)
        self._glow.setEasingCurve(QEasingCurve.InOutSine)
        self._glow.valueChanged.connect(self._on_glow)

    def start(self) -> None:
        self._pop.start()
        self._glow.start()

    def _on_pop(self, t) -> None:
        t = float(t)
        self._scale = 0.5 + 0.5 * t
        self._opacity = max(0.0, min(1.0, t * 2.2))
        self.update()

    def _on_glow(self, value) -> None:
        self._pulse = float(value)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        center = QPointF(self.width() / 2, self.height() / 2)

        radius = LOGO_SIZE * (0.78 + 0.08 * self._pulse) * min(1.0, self._scale + 0.2)
        glow = QRadialGradient(center, radius)
        accent = QColor(ACCENT_COLOR)
        accent.setAlpha(int((70 + 70 * self._pulse) * self._opacity))
        cyan = QColor(ACCENT_COLOR_2)
        cyan.setAlpha(int(30 * self._opacity))
        glow.setColorAt(0.0, accent)
        glow.setColorAt(0.6, cyan)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(center, radius, radius)

        side = LOGO_SIZE * self._scale
        target = QRectF(center.x() - side / 2, center.y() - side / 2, side, side)
        painter.setOpacity(self._opacity)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))


class GlassProgress(QWidget):
    """Rounded progress bar with a moving shine; also has an indeterminate mode."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(8)
        self._target = 0.0
        self._shown = 0.0
        self._indeterminate = True
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_value(self, value: float) -> None:
        self._indeterminate = False
        self._target = max(0.0, min(100.0, float(value)))

    def set_indeterminate(self) -> None:
        self._indeterminate = True

    def _tick(self) -> None:
        self._phase = (self._phase + 0.012) % 1.0
        self._shown += (self._target - self._shown) * 0.14
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        radius = rect.height() / 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawRoundedRect(rect, radius, radius)

        if self._indeterminate:
            width = rect.width() * 0.34
            x = -width + (rect.width() + width) * self._phase
            fill = QRectF(x, 0, width, rect.height()).intersected(rect)
        else:
            fill = QRectF(0, 0, rect.width() * self._shown / 100.0, rect.height())
        if fill.width() <= 0:
            return

        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter.setClipPath(clip)
        gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
        gradient.setColorAt(0.0, QColor(ACCENT_COLOR))
        gradient.setColorAt(1.0, QColor(ACCENT_COLOR_2))
        painter.setBrush(QBrush(gradient))
        painter.drawRoundedRect(fill, radius, radius)

        shine_w = 46.0
        sx = fill.left() + (fill.width() + shine_w) * self._phase - shine_w
        shine = QLinearGradient(sx, 0, sx + shine_w, 0)
        shine.setColorAt(0.0, QColor(255, 255, 255, 0))
        shine.setColorAt(0.5, QColor(255, 255, 255, 110))
        shine.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setClipPath(clip.intersected(self._rounded(fill, radius)))
        painter.setBrush(QBrush(shine))
        painter.drawRect(QRectF(sx, 0, shine_w, rect.height()))

    @staticmethod
    def _rounded(rect: QRectF, radius: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path


class _Panel(QFrame):
    """Glass-style splash background: the app's purple-teal gradient + soft border."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor("#241b4e"))
        gradient.setColorAt(0.45, QColor("#342a66"))
        gradient.setColorAt(1.0, QColor("#163a52"))
        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
        painter.drawRoundedRect(rect, 22, 22)


class SplashScreen(QWidget):
    update_accepted = Signal()
    update_declined = Signal()

    def __init__(self, icon_path: str):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(APP_NAME)
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            pixmap = QIcon(icon_path).pixmap(QSize(LOGO_SIZE * 2, LOGO_SIZE * 2))
        else:
            pixmap = QPixmap(LOGO_SIZE, LOGO_SIZE)
            pixmap.fill(Qt.transparent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 22, 22, 26)
        self._panel = _Panel()
        self._shadow = QGraphicsDropShadowEffect(self._panel)
        self._shadow.setBlurRadius(30)
        self._shadow.setOffset(0, 8)
        self._shadow.setColor(QColor(0, 0, 0, 150))
        self._panel.setGraphicsEffect(self._shadow)
        outer.addWidget(self._panel)

        layout = QVBoxLayout(self._panel)
        layout.setContentsMargins(40, 26, 40, 30)
        layout.setSpacing(0)

        self.logo = LogoWidget(pixmap)
        layout.addWidget(self.logo, alignment=Qt.AlignHCenter)

        title = QLabel(APP_NAME)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: 700; color: #ffffff;")
        layout.addWidget(title)

        version = QLabel(f"v{CURRENT_VERSION}")
        version.setAlignment(Qt.AlignCenter)
        version.setStyleSheet("font-size: 12px; color: rgba(241, 240, 250, 140);")
        layout.addWidget(version)
        layout.addSpacing(22)

        self.status = QLabel("Spouštím…")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("font-size: 12px; color: rgba(241, 240, 250, 190);")
        layout.addWidget(self.status)
        layout.addSpacing(8)

        self.progress = GlassProgress()
        layout.addWidget(self.progress)
        layout.addSpacing(14)

        self._buttons = QWidget()
        buttons = QHBoxLayout(self._buttons)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(10)
        self.later_btn = QPushButton("Později")
        self.update_btn = QPushButton("Aktualizovat")
        self.update_btn.setObjectName("PrimaryButton")
        for btn in (self.later_btn, self.update_btn):
            btn.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(btn)
        self.later_btn.clicked.connect(self.update_declined.emit)
        self.update_btn.clicked.connect(self.update_accepted.emit)
        self._buttons.hide()
        layout.addWidget(self._buttons)

        self.setFixedSize(480, 420)
        self.setWindowOpacity(0.0)
        self._fade = None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - QPoint(self.width() // 2, self.height() // 2))
        self._animate_opacity(0.0, 1.0, 260)
        self.logo.start()

    def _animate_opacity(self, start: float, end: float, ms: int, done: Callable | None = None) -> None:
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(ms)
        self._fade.setStartValue(start)
        self._fade.setEndValue(end)
        if done is not None:
            self._fade.finished.connect(done)
        self._fade.start()

    # -- state helpers used by the startup flow --------------------------------
    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_progress(self, value: float) -> None:
        self.progress.set_value(value)

    def set_indeterminate(self) -> None:
        self.progress.set_indeterminate()

    def show_update_prompt(self, version: str) -> None:
        self.status.setText(f"Je dostupná nová verze v{version}")
        self.progress.set_value(100)
        self._buttons.show()

    def hide_update_prompt(self) -> None:
        self._buttons.hide()

    def finish(self, show_main: Callable) -> None:
        # Show the main window first so closing the splash never leaves Qt
        # without a visible window (which would quit the app), then fade out.
        show_main()
        self._animate_opacity(1.0, 0.0, 280, self.close)
