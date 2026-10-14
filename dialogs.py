"""Message and confirmation popups in the app's own look (the same dimmed
overlay and glass panel as the image preview), replacing QMessageBox."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from splash import _Panel
from style import ACCENT_COLOR, ACCENT_LIGHT, DANGER_COLOR

MESSAGE_WIDTH = 360
_ICON_COLORS = {"info": ACCENT_COLOR, "warning": "#f5a524", "danger": DANGER_COLOR}


class _Icon(QWidget):
    """A coloured disc with "i" (info) or "!" (warning, danger)."""

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.setFixedSize(40, 40)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(_ICON_COLORS.get(self.kind, ACCENT_COLOR))
        halo = QColor(color)
        halo.setAlpha(60)
        painter.setPen(Qt.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(QRectF(self.rect()))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(self.rect()).adjusted(5, 5, -5, -5))
        c = QRectF(self.rect()).center()
        painter.setPen(QPen(QColor(255, 255, 255), 2.6, Qt.SolidLine, Qt.RoundCap))
        if self.kind == "info":
            painter.drawPoint(QPointF(c.x(), c.y() - 6))
            painter.drawLine(QPointF(c.x(), c.y() - 1), QPointF(c.x(), c.y() + 7))
        else:
            painter.drawLine(QPointF(c.x(), c.y() - 7), QPointF(c.x(), c.y() + 2))
            painter.drawPoint(QPointF(c.x(), c.y() + 7))


class _Overlay(QDialog):
    """Dims the parent window and centres a glass panel on it; subclasses
    fill `self.content`. Esc or a click on the dim margin closes it."""

    def __init__(self, parent: QWidget | None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        panel = _Panel()
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(34)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 170))
        panel.setGraphicsEffect(shadow)
        outer.addStretch(1)
        outer.addWidget(panel, alignment=Qt.AlignCenter)
        outer.addStretch(1)

        self.content = QVBoxLayout(panel)
        self.content.setContentsMargins(24, 22, 24, 20)
        self.content.setSpacing(18)

        window = parent.window() if parent is not None else None
        if window is not None:
            self.setGeometry(window.frameGeometry())
        else:
            self.resize(QApplication.primaryScreen().availableGeometry().size() * 0.5)

        self.setWindowOpacity(0.0)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(160)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)

    @staticmethod
    def _button(text: str, handler, object_name: str = "") -> QPushButton:
        btn = QPushButton(text)
        if object_name:
            btn.setObjectName(object_name)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumWidth(96)
        btn.clicked.connect(handler)
        return btn

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(8, 6, 24, 140))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fade.start()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        # a click on the dim margin dismisses (= cancel), like the preview
        if not self.childAt(event.position().toPoint()):
            self.reject()
            return
        super().mousePressEvent(event)


class GlassDialog(_Overlay):
    def __init__(self, parent: QWidget | None, title: str, text: str, kind: str = "info",
                 confirm_text: str | None = None, cancel_text: str = "Zrušit"):
        super().__init__(parent)
        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(_Icon(kind), alignment=Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(6)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 15px; font-weight: 700; color: #ffffff;")
        texts.addWidget(heading)
        message = QLabel(text)
        message.setWordWrap(True)
        message.setFixedWidth(MESSAGE_WIDTH)  # fixed, so wrapped text gets its full height
        message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        message.setStyleSheet("font-size: 13px; color: rgba(241, 240, 250, 200);")
        texts.addWidget(message)
        body.addLayout(texts, stretch=1)
        self.content.addLayout(body)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        if confirm_text:
            cancel = self._button(cancel_text, self.reject)
            confirm = self._button(confirm_text, self.accept, "DangerSolidButton" if kind == "danger" else "PrimaryButton")
            buttons.addWidget(cancel)
            buttons.addWidget(confirm)
            cancel.setDefault(True)  # Enter must not destroy anything by accident
            cancel.setFocus()
        else:
            ok = self._button("OK", self.accept, "PrimaryButton")
            buttons.addWidget(ok)
            ok.setDefault(True)
            ok.setFocus()
        self.content.addLayout(buttons)


class WhatsNewDialog(_Overlay):
    """ "Co je nového": the changelog entries of one or more versions."""

    WIDTH = 440

    def __init__(self, parent: QWidget | None, entries: list[tuple[str, list[str]]]):
        super().__init__(parent)
        header = QHBoxLayout()
        header.setSpacing(10)
        heading = QLabel("Co je nového")
        heading.setStyleSheet("font-size: 17px; font-weight: 700; color: #ffffff;")
        header.addWidget(heading)
        header.addStretch(1)
        if entries:
            version = QLabel(f"v{entries[0][0]}")
            version.setObjectName("Badge")
            version.setProperty("active", True)
            header.addWidget(version)
        self.content.addLayout(header)

        body = QWidget()
        body.setObjectName("Transparent")
        rows = QVBoxLayout(body)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(10)
        for index, (number, items) in enumerate(entries):
            if index:  # older versions, when several updates were skipped
                older = QLabel(f"Verze {number}")
                older.setObjectName("SectionTitle")
                rows.addSpacing(6)
                rows.addWidget(older)
            for item in items:
                rows.addLayout(self._item(item))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(body)
        body.adjustSize()
        limit = int((parent.window().height() if parent is not None else 700) * 0.6)
        scroll.setFixedSize(self.WIDTH + 14, min(body.sizeHint().height() + 4, limit))
        self.content.addWidget(scroll)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = self._button("Rozumím", self.accept, "PrimaryButton")
        buttons.addWidget(ok)
        ok.setDefault(True)
        ok.setFocus()
        self.content.addLayout(buttons)

    def _item(self, text: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        dot = QLabel("•")
        dot.setStyleSheet(f"color: {ACCENT_LIGHT}; font-size: 15px; font-weight: 700;")
        dot.setFixedWidth(10)
        row.addWidget(dot, alignment=Qt.AlignTop)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFixedWidth(self.WIDTH - 20)
        label.setStyleSheet("font-size: 13px; color: rgba(241, 240, 250, 215);")
        row.addWidget(label)
        row.addStretch(1)
        return row


def information(parent: QWidget | None, title: str, text: str) -> None:
    GlassDialog(parent, title, text, "info").exec()


def warning(parent: QWidget | None, title: str, text: str) -> None:
    GlassDialog(parent, title, text, "warning").exec()


def confirm(parent: QWidget | None, title: str, text: str, confirm_text: str, danger: bool = False) -> bool:
    dialog = GlassDialog(parent, title, text, "danger" if danger else "info", confirm_text)
    return dialog.exec() == QDialog.Accepted


def whats_new(parent: QWidget | None, entries: list[tuple[str, list[str]]]) -> None:
    if entries:
        WhatsNewDialog(parent, entries).exec()


class Toast(QWidget):
    """A short message that slides in at the bottom of the window and fades
    out by itself - for results the user should notice but not dismiss."""

    MARGIN_BOTTOM = 64

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 18, 10)
        layout.setSpacing(12)
        self._icon = _Icon("info")
        self._icon.setFixedSize(26, 26)
        layout.addWidget(self._icon)
        self._label = QLabel()
        self._label.setStyleSheet("font-size: 13px; color: #ffffff; background: transparent;")
        layout.addWidget(self._label)

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.finished.connect(self._after_fade)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text: str, kind: str = "info", ms: int = 4500) -> None:
        self._icon.kind = kind
        self._label.setText(text)
        self.adjustSize()
        window = self.parentWidget()
        self.move((window.width() - self.width()) // 2, window.height() - self.height() - self.MARGIN_BOTTOM)
        self.raise_()
        self.show()
        self._fade.stop()
        self._fade.setDuration(160)
        self._fade.setStartValue(self._opacity.opacity() if self.isVisible() else 0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(ms)

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setDuration(300)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _after_fade(self) -> None:
        if self._opacity.opacity() <= 0.01:
            self.hide()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(255, 255, 255, 70), 1))
        painter.setBrush(QColor(36, 28, 78, 240))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)


def toast(window: QWidget, text: str, kind: str = "info") -> None:
    """Shows `text` as a toast on `window` (one shared toast per window)."""
    existing = window.findChild(Toast)
    (existing or Toast(window)).show_message(text, kind)
