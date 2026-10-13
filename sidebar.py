"""The right-hand control panel: processing options, selection and export.

It owns only the widgets and exposes intent through signals, so MainWindow
holds the logic and this file holds the layout.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from core.processing import Operations

PANEL_WIDTH = 300


def glass_shadow(blur: int = 24, alpha: int = 90, y_offset: int = 6) -> QGraphicsDropShadowEffect:
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(0, 0, 0, alpha))
    return effect


class Section(QFrame):
    """A titled group: small caption (with an optional badge on the right)
    above a body that callers fill through `body`."""

    def __init__(self, title: str, with_badge: bool = False):
        super().__init__()
        self.setObjectName("Section")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        caption = QLabel(title.upper())
        caption.setObjectName("SectionTitle")
        header.addWidget(caption)
        header.addStretch(1)
        self.badge: QLabel | None = None
        if with_badge:
            self.badge = QLabel()
            self.badge.setObjectName("Badge")
            header.addWidget(self.badge)
        outer.addLayout(header)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(8)
        outer.addLayout(self.body)


def _button(text: str, handler, object_name: str = "", tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    if object_name:
        btn.setObjectName(object_name)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    btn.clicked.connect(handler)
    return btn


class SidebarPanel(QFrame):
    process_requested = Signal()
    select_all_requested = Signal()
    select_none_requested = Signal()
    clear_marks_requested = Signal()
    choose_export_folder_requested = Signal()
    export_requested = Signal()

    PROCESS_TEXT = "Zpracovat vybrané"
    EXPORT_TEXT = "Odeslat vybrané"

    def __init__(self, export_folder: str = ""):
        super().__init__()
        self.setObjectName("GlassPanel")
        self.setFixedWidth(PANEL_WIDTH)
        self.setGraphicsEffect(glass_shadow())
        self._selected = 0
        self._busy = {"process": False, "export": False}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self._build_operations())
        layout.addWidget(self._build_selection())
        layout.addWidget(self._build_export(export_folder))
        layout.addStretch(1)
        self._refresh_actions()

    # -- sections ---------------------------------------------------------
    def _build_operations(self) -> Section:
        section = Section("Operace")
        self.op_resize = QCheckBox("Změnit velikost na 1024 px")
        self.op_resize.setChecked(True)
        self.op_resize.setEnabled(False)
        self.op_resize.setToolTip("Vždy zapnuto")
        self.op_border = QCheckBox("Přidat černý rámeček (1 px)")
        self.op_jpeg = QCheckBox("Převést na JPEG")
        for box in (self.op_resize, self.op_border, self.op_jpeg):
            section.body.addWidget(box)

        self.process_btn = _button(self.PROCESS_TEXT, self.process_requested.emit, "PrimaryButton")
        self.process_btn.setGraphicsEffect(glass_shadow(blur=28, alpha=110, y_offset=4))
        section.body.addSpacing(4)
        section.body.addWidget(self.process_btn)
        return section

    def _build_selection(self) -> Section:
        section = Section("Výběr", with_badge=True)
        self.selection_badge = section.badge

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_button("Vybrat vše", self.select_all_requested.emit))
        row.addWidget(_button("Zrušit výběr", self.select_none_requested.emit))
        section.body.addLayout(row)

        section.body.addWidget(_button(
            "Vymazat značky zpracování", self.clear_marks_requested.emit, "GhostButton",
            "Odstraní zelené odznaky „zpracováno“ ze všech fotek",
        ))
        return section

    def _build_export(self, export_folder: str) -> Section:
        section = Section("Export")

        row = QHBoxLayout()
        row.setSpacing(8)
        self.export_folder_edit = QLineEdit()
        self.export_folder_edit.setReadOnly(True)
        self.export_folder_edit.setPlaceholderText("Cílová složka")
        row.addWidget(self.export_folder_edit, stretch=1)
        choose = _button("Vybrat…", self.choose_export_folder_requested.emit,
                         tooltip="Vybrat cílovou složku")
        row.addWidget(choose)
        section.body.addLayout(row)

        self.export_btn = _button(self.EXPORT_TEXT, self.export_requested.emit, "AccentButton")
        section.body.addWidget(self.export_btn)

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
        self.export_folder_edit.setText(folder)
        self.export_folder_edit.setToolTip(folder)

    def set_selected_count(self, count: int) -> None:
        self._selected = count
        self.selection_badge.setText(f"{count} vybráno")
        self.selection_badge.setProperty("active", count > 0)
        self.selection_badge.style().unpolish(self.selection_badge)
        self.selection_badge.style().polish(self.selection_badge)
        self._refresh_actions()

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
