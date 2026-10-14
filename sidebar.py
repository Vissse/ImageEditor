"""The right-hand control panel: processing options, selection and export.

It owns only the widgets and exposes intent through signals, so MainWindow
holds the logic and this file holds the layout.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QRectF, QSize, Qt, Signal, Property
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from core.processing import Operations
from export_preview import ExportPreview
from style import ACCENT_COLOR, ACCENT_LIGHT

PANEL_WIDTH = 300
CONTROL_HEIGHT = 36


def glass_shadow(blur: int = 24, alpha: int = 90, y_offset: int = 6) -> QGraphicsDropShadowEffect:
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(0, 0, 0, alpha))
    return effect


class ToggleSwitch(QCheckBox):
    """A checkbox drawn as a label on the left and a sliding switch on the
    right. Behaves like a normal QCheckBox (isChecked, setChecked, toggled)."""

    TRACK_W, TRACK_H, KNOB_PAD = 38, 22, 3

    def __init__(self, text: str):
        super().__init__(text)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setCursor(Qt.PointingHandCursor)
        self.toggled.connect(self._animate)

    def _animate(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = Property(float, get_knob, set_knob)

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        self._pos = 1.0 if checked else 0.0

    def sizeHint(self) -> QSize:
        return QSize(220, max(30, self.TRACK_H + 8))

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        enabled = self.isEnabled()
        h = self.height()
        track = QRectF(self.width() - self.TRACK_W, (h - self.TRACK_H) / 2, self.TRACK_W, self.TRACK_H)

        off = QColor(255, 255, 255, 40)
        on = QColor(ACCENT_COLOR)
        t = self._pos
        color = QColor(
            round(off.red() + (on.red() - off.red()) * t),
            round(off.green() + (on.green() - off.green()) * t),
            round(off.blue() + (on.blue() - off.blue()) * t),
            round(off.alpha() + (255 - off.alpha()) * t),
        )
        if not enabled:
            color.setAlpha(int(color.alpha() * 0.65))
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)

        d = self.TRACK_H - 2 * self.KNOB_PAD
        x = track.left() + self.KNOB_PAD + (self.TRACK_W - 2 * self.KNOB_PAD - d) * t
        painter.setBrush(QColor(255, 255, 255, 255 if enabled else 200))
        painter.drawEllipse(QRectF(x, track.top() + self.KNOB_PAD, d, d))

        painter.setPen(QColor(241, 240, 250, 235 if enabled else 190))
        text_rect = QRectF(0, 0, track.left() - 10, h)
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())


class FolderPicker(QPushButton):
    """The export target as one clickable row: folder icon, a small
    "Cílová složka" caption above the folder name, and "Změnit" on the right."""

    HEIGHT = 50

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFixedHeight(self.HEIGHT)
        self._name = ""

    def set_folder(self, folder: str) -> None:
        self._name = os.path.basename(os.path.normpath(folder)) if folder else ""
        self.setToolTip((folder + "\n\n" if folder else "") + "Kliknutím vyberete cílovou složku")
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        hover = self.underMouse()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(255, 255, 255, 60 if hover else 30), 1))
        painter.setBrush(QColor(255, 255, 255, 22 if hover else 10))
        painter.drawRoundedRect(rect, 10, 10)

        # folder icon: a tab and a body, in the accent colour
        accent = QColor(ACCENT_LIGHT)
        x, y = 14, (self.height() - 18) / 2
        icon = QPainterPath()
        icon.moveTo(x, y + 3)
        icon.lineTo(x + 7, y + 3)
        icon.lineTo(x + 9, y + 5.5)
        icon.lineTo(x + 22, y + 5.5)
        icon.lineTo(x + 22, y + 18)
        icon.lineTo(x, y + 18)
        icon.closeSubpath()
        fill = QColor(accent)
        fill.setAlpha(70)
        painter.setBrush(fill)
        painter.setPen(QPen(accent, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(icon)

        action = "Změnit" if self._name else "Vybrat"
        font = painter.font()
        font.setPixelSize(12)
        font.setBold(False)
        painter.setFont(font)
        action_w = painter.fontMetrics().horizontalAdvance(action)
        painter.setPen(QColor(255, 255, 255) if hover else accent)
        action_rect = QRectF(self.width() - action_w - 14, 0, action_w, self.height())
        painter.drawText(action_rect, Qt.AlignVCenter | Qt.AlignRight, action)

        text_left = x + 34
        text_w = action_rect.left() - 10 - text_left
        font.setPixelSize(10)
        painter.setFont(font)
        painter.setPen(QColor(241, 240, 250, 120))
        painter.drawText(QRectF(text_left, 8, text_w, 14), Qt.AlignLeft | Qt.AlignVCenter, "CÍLOVÁ SLOŽKA")

        font.setPixelSize(13)
        font.setBold(bool(self._name))
        painter.setFont(font)
        name = self._name or "nevybrána"
        painter.setPen(QColor(255, 255, 255) if self._name else QColor(241, 240, 250, 140))
        elided = painter.fontMetrics().elidedText(name, Qt.ElideMiddle, int(text_w))
        painter.drawText(QRectF(text_left, 23, text_w, 20), Qt.AlignLeft | Qt.AlignVCenter, elided)


class Section(QWidget):
    """A titled group without a box: small caption, optional widgets on the
    right of it (badge, links), and a body that callers fill through `body`."""

    def __init__(self, title: str):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        self.header = QHBoxLayout()
        self.header.setContentsMargins(0, 0, 0, 0)
        self.header.setSpacing(4)
        caption = QLabel(title.upper())
        caption.setObjectName("SectionTitle")
        self.header.addWidget(caption)
        self.header.addStretch(1)
        outer.addLayout(self.header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        outer.addLayout(self.body)


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("Separator")
    line.setFixedHeight(1)
    return line


def _button(text: str, handler, object_name: str = "", tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    if object_name:
        btn.setObjectName(object_name)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    btn.clicked.connect(handler)
    return btn


def _arrow_pixmap(mirror: bool, alpha: int, size: int = 48) -> QPixmap:
    """A rounded "back" arrow: filled head on the left, a stroke that runs
    right and curls down. Mirrored, it points forward (redo). Drawn at 3x."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    if mirror:
        painter.translate(size, 0)
        painter.scale(-1, 1)
    s = size
    color = QColor(255, 255, 255, alpha)
    painter.setPen(QPen(color, s * 0.105, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    curl = QPainterPath()
    curl.moveTo(s * 0.30, s * 0.36)
    curl.lineTo(s * 0.58, s * 0.36)
    curl.arcTo(QRectF(s * 0.36, s * 0.36, s * 0.46, s * 0.46), 90, -180)
    curl.lineTo(s * 0.38, s * 0.82)
    painter.drawPath(curl)
    head = QPainterPath()
    head.moveTo(s * 0.10, s * 0.36)
    head.lineTo(s * 0.34, s * 0.16)
    head.lineTo(s * 0.34, s * 0.56)
    head.closeSubpath()
    painter.setPen(QPen(color, s * 0.04, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(color)
    painter.drawPath(head)
    painter.end()
    pixmap.setDevicePixelRatio(3)
    return pixmap


def _arrow_icon(mirror: bool = False) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_arrow_pixmap(mirror, 255), QIcon.Normal)
    icon.addPixmap(_arrow_pixmap(mirror, 70), QIcon.Disabled)
    return icon


def _link(text: str, handler, tooltip: str = "", danger: bool = False) -> QPushButton:
    return _button(text, handler, "LinkDanger" if danger else "LinkButton", tooltip)


class SidebarPanel(QFrame):
    process_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    select_all_requested = Signal()
    select_none_requested = Signal()
    clear_marks_requested = Signal()
    delete_requested = Signal()
    choose_export_folder_requested = Signal()
    export_requested = Signal()
    open_export_folder_requested = Signal()
    export_item_clicked = Signal(str)

    PROCESS_TEXT = "Zpracovat vybrané"
    EXPORT_TEXT = "Odeslat vybrané"

    def __init__(self, export_folder: str = ""):
        super().__init__()
        self.setObjectName("GlassPanel")
        self.setFixedWidth(PANEL_WIDTH)
        self.setGraphicsEffect(glass_shadow())
        self._selected = 0
        self._total = 0
        self._busy = {"process": False, "export": False}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(18)
        layout.addWidget(self._build_operations())
        layout.addWidget(_separator())
        layout.addWidget(self._build_selection())
        layout.addWidget(_separator())
        layout.addWidget(self._build_export(export_folder))
        layout.addStretch(1)
        self._refresh_actions()

    # -- sections ---------------------------------------------------------
    def _build_operations(self) -> Section:
        section = Section("Úpravy")
        history = QFrame()
        history.setObjectName("HistoryGroup")
        row = QHBoxLayout(history)
        row.setContentsMargins(2, 2, 2, 2)
        row.setSpacing(2)
        self.undo_btn = _button("", self.undo_requested.emit, "HistoryButton")
        self.redo_btn = _button("", self.redo_requested.emit, "HistoryButton")
        for btn, mirror in ((self.undo_btn, False), (self.redo_btn, True)):
            btn.setIcon(_arrow_icon(mirror))
            btn.setIconSize(QSize(16, 16))
            btn.setFixedSize(32, 24)
            row.addWidget(btn)
        section.header.addWidget(history)
        self.set_history(None, None)
        self.op_border = ToggleSwitch("Černý rámeček")
        self.op_jpeg = ToggleSwitch("Převést na JPEG")
        self.op_jpeg.setToolTip("PDF, HEIC a další formáty se na JPEG převedou vždy\n(vícestránkové PDF = jeden JPEG na stránku)")
        for box in (self.op_border, self.op_jpeg):
            section.body.addWidget(box)

        self.process_btn = _button(self.PROCESS_TEXT, self.process_requested.emit, "PrimaryButton",
                                   "Převede na 1024 px a použije zapnuté úpravy")
        section.body.addSpacing(2)
        section.body.addWidget(self.process_btn)

        hint_row = QHBoxLayout()
        hint = QLabel("vždy převede na 1024 px")
        hint.setObjectName("Hint")
        hint_row.addWidget(hint)
        hint_row.addStretch(1)
        hint_row.addWidget(_link("Vymazat značky", self.clear_marks_requested.emit,
                                 "Odstraní zelené odznaky „zpracováno“ ze všech fotek"))
        section.body.addLayout(hint_row)
        return section

    def _build_selection(self) -> Section:
        section = Section("Výběr")
        self.selection_count = QLabel()
        self.selection_count.setObjectName("SelectionCount")
        section.header.addWidget(self.selection_count)

        row = QHBoxLayout()
        row.setSpacing(8)
        # "Vše | Nic" as one segmented control, delete set apart on the right
        segmented = QFrame()
        segmented.setObjectName("Segmented")
        segmented.setFixedHeight(CONTROL_HEIGHT)
        seg = QHBoxLayout(segmented)
        seg.setContentsMargins(3, 3, 3, 3)
        seg.setSpacing(2)
        self.select_all_btn = _button("Vybrat vše", self.select_all_requested.emit, "SegmentButton", "Ctrl+A")
        self.select_none_btn = _button("Zrušit", self.select_none_requested.emit, "SegmentButton", "Zrušit výběr")
        for btn in (self.select_all_btn, self.select_none_btn):
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            seg.addWidget(btn)
        row.addWidget(segmented, stretch=1)

        self.delete_btn = _button("Smazat", self.delete_requested.emit, "QuietDangerButton",
                                  "Přesune vybrané soubory ze zdrojové složky do Koše (Delete)")
        self.delete_btn.setFixedHeight(CONTROL_HEIGHT)
        row.addWidget(self.delete_btn)
        section.body.addLayout(row)
        return section

    def _build_export(self, export_folder: str) -> Section:
        section = Section("Export")
        self.open_export_btn = _link("Otevřít", self.open_export_folder_requested.emit,
                                     "Otevře cílovou složku v Průzkumníku")
        section.header.addWidget(self.open_export_btn)

        self.export_folder_btn = FolderPicker()
        self.export_folder_btn.clicked.connect(self.choose_export_folder_requested.emit)
        section.body.addWidget(self.export_folder_btn)

        self.export_btn = _button(self.EXPORT_TEXT, self.export_requested.emit, "AccentButton",
                                  "Přesune vybrané fotky do cílové složky (ze zdrojové zmizí)")
        section.body.addWidget(self.export_btn)

        self.export_preview = ExportPreview()
        self.export_preview.item_clicked.connect(self.export_item_clicked.emit)
        section.body.addWidget(self.export_preview)

        self.set_export_folder(export_folder)
        return section

    # -- state exposed to MainWindow ---------------------------------------
    def operations(self) -> Operations:
        return Operations(
            resize=True,
            border=self.op_border.isChecked(),
            to_jpeg=self.op_jpeg.isChecked(),
        )

    def set_export_folder(self, folder: str) -> None:
        self.export_folder_btn.set_folder(folder)
        self.show_export_preview(folder, [])

    def show_export_preview(self, folder: str, recent: list[str]) -> None:
        """`recent`: names just moved there, newest first (highlighted)."""
        self.export_preview.show_folder(folder, recent)
        self.open_export_btn.setVisible(bool(folder))

    def set_selected_count(self, count: int, total: int = 0) -> None:
        self._selected = count
        self._total = total
        if count:
            self.selection_count.setText(f"{count} z {total}" if total else str(count))
        else:
            self.selection_count.setText("nic nevybráno")
        self.selection_count.setProperty("active", count > 0)
        self.selection_count.style().unpolish(self.selection_count)
        self.selection_count.style().polish(self.selection_count)
        self._refresh_actions()

    def set_history(self, undo: str | None, redo: str | None) -> None:
        """Labels of the steps undo / redo would affect; None = not available."""
        self.undo_btn.setEnabled(undo is not None)
        self.undo_btn.setToolTip(f"Zpět: {undo} (Ctrl+Z)" if undo else "Zpět – není co vrátit")
        self.redo_btn.setEnabled(redo is not None)
        self.redo_btn.setToolTip(f"Znovu: {redo} (Ctrl+Y)" if redo else "Znovu – není co zopakovat")

    def set_processing(self, busy: bool) -> None:
        self._busy["process"] = busy
        self.process_btn.setText("Zpracovávám…" if busy else self.PROCESS_TEXT)
        self._refresh_actions()

    def set_exporting(self, busy: bool) -> None:
        self._busy["export"] = busy
        self.export_btn.setText("Odesílám…" if busy else self.EXPORT_TEXT)
        self._refresh_actions()

    def _refresh_actions(self) -> None:
        has = self._selected > 0
        self.process_btn.setEnabled(has and not self._busy["process"])
        self.export_btn.setEnabled(has and not self._busy["export"])
        self.delete_btn.setEnabled(has and not any(self._busy.values()))
        self.select_all_btn.setEnabled(self._total > 0 and self._selected < self._total)
        self.select_none_btn.setEnabled(has)
