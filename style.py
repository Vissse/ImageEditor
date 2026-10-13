"""Glassmorphism styling: a QSS theme plus an optional real backdrop-blur
("acrylic") effect behind the window on Windows 10/11, so panels painted as
translucent "glass" by the QSS actually sit over a blurred desktop instead
of a flat gradient.
"""
from __future__ import annotations

import ctypes
import sys

ACCENT_COLOR = "#7F5AF0"
ACCENT_COLOR_2 = "#2CB1BC"
DANGER_COLOR = "#ff6b6b"
SUCCESS_COLOR = "#2ecc71"

STYLE_SHEET = f"""
QWidget {{
    font-family: "Segoe UI", sans-serif;
    color: #f1f0fa;
    font-size: 13px;
}}

QWidget#Background {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:1,
        stop:0 #241b4e,
        stop:0.45 #342a66,
        stop:1 #163a52
    );
}}

QFrame#GlassPanel {{
    background-color: rgba(255, 255, 255, 24);
    border: 1px solid rgba(255, 255, 255, 60);
    border-radius: 16px;
}}

QScrollArea, QScrollArea > QWidget > QWidget {{
    background: transparent;
    border: none;
}}

QWidget#Transparent {{
    background: transparent;
}}

QLabel {{
    background: transparent;
    color: #f1f0fa;
}}

QLabel#Title {{
    font-size: 18px;
    font-weight: 600;
    color: #ffffff;
}}

QLabel#StatusGood {{
    color: {SUCCESS_COLOR};
    font-weight: 600;
}}

QLineEdit {{
    background-color: rgba(255, 255, 255, 18);
    border: 1px solid rgba(255, 255, 255, 55);
    border-radius: 9px;
    padding: 6px 10px;
    color: #ffffff;
    selection-background-color: {ACCENT_COLOR};
}}

QLineEdit:disabled {{
    color: rgba(255, 255, 255, 140);
}}

QPushButton {{
    background-color: rgba(255, 255, 255, 26);
    border: 1px solid rgba(255, 255, 255, 65);
    border-radius: 10px;
    padding: 8px 16px;
    color: #ffffff;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: rgba(255, 255, 255, 45);
}}

QPushButton:pressed {{
    background-color: rgba(255, 255, 255, 15);
}}

QPushButton:disabled {{
    color: rgba(255, 255, 255, 110);
    background-color: rgba(255, 255, 255, 12);
}}

QPushButton#PrimaryButton {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT_COLOR}, stop:1 {ACCENT_COLOR_2}
    );
    border: 1px solid rgba(255, 255, 255, 90);
    color: #ffffff;
    font-weight: 700;
    padding: 9px 20px;
}}

QPushButton#PrimaryButton:hover {{
    border: 1px solid rgba(255, 255, 255, 160);
}}

QPushButton#PrimaryButton:disabled {{
    background: rgba(255, 255, 255, 25);
    color: rgba(255, 255, 255, 130);
}}

QPushButton#AccentButton {{
    background-color: rgba(127, 90, 240, 70);
    border: 1px solid rgba(127, 90, 240, 190);
}}

QPushButton#AccentButton:hover {{
    background-color: rgba(127, 90, 240, 120);
}}

QPushButton#AccentButton:disabled {{
    background-color: rgba(255, 255, 255, 12);
    border: 1px solid rgba(255, 255, 255, 40);
}}

QPushButton#GhostButton {{
    background: transparent;
    border: none;
    color: rgba(241, 240, 250, 170);
    font-weight: 400;
    padding: 4px 8px;
}}

QPushButton#GhostButton:hover {{
    color: #ffffff;
    background-color: rgba(255, 255, 255, 18);
}}

QFrame#Section {{
    background-color: rgba(255, 255, 255, 14);
    border: 1px solid rgba(255, 255, 255, 34);
    border-radius: 12px;
}}

QLabel#SectionTitle {{
    font-size: 11px;
    font-weight: 700;
    color: rgba(241, 240, 250, 150);
}}

QLabel#Badge {{
    font-size: 11px;
    padding: 2px 9px;
    border-radius: 9px;
    background-color: rgba(255, 255, 255, 22);
    color: rgba(241, 240, 250, 170);
}}

QLabel#Badge[active="true"] {{
    background-color: rgba(127, 90, 240, 150);
    color: #ffffff;
}}

QCheckBox {{
    spacing: 8px;
    background: transparent;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1.5px solid rgba(255, 255, 255, 110);
    background: rgba(255, 255, 255, 20);
}}

QCheckBox::indicator:checked {{
    background-color: {ACCENT_COLOR};
    border: 1.5px solid {ACCENT_COLOR};
}}

QCheckBox:disabled {{
    color: rgba(241, 240, 250, 215);
}}

QCheckBox::indicator:checked:disabled {{
    background-color: rgba(127, 90, 240, 170);
    border: 1.5px solid rgba(127, 90, 240, 200);
}}

QCheckBox::indicator:hover {{
    border: 1.5px solid rgba(255, 255, 255, 200);
}}

QStatusBar {{
    background: transparent;
    color: rgba(255, 255, 255, 190);
}}

QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 4px 2px 4px 0;
    border: none;
}}

QScrollBar::handle:vertical {{
    background: rgba(255, 255, 255, 65);
    border-radius: 4px;
    min-height: 32px;
}}

QScrollBar::handle:vertical:hover {{
    background: rgba(255, 255, 255, 115);
}}

QScrollBar::handle:vertical:pressed {{
    background: {ACCENT_COLOR};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
    width: 0px;
    background: transparent;
    border: none;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    border: none;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
    margin: 0 4px 2px 4px;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background: rgba(255, 255, 255, 65);
    border-radius: 4px;
    min-width: 32px;
}}

QScrollBar::handle:horizontal:hover {{
    background: rgba(255, 255, 255, 115);
}}

QScrollBar::handle:horizontal:pressed {{
    background: {ACCENT_COLOR};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    height: 0px;
    width: 0px;
    background: transparent;
    border: none;
}}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
    border: none;
}}

QScrollBar::corner {{
    background: transparent;
    border: none;
}}

QToolTip {{
    background-color: #241b4e;
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 80);
    padding: 4px;
}}
"""


def enable_windows_acrylic_blur(hwnd: int) -> bool:
    """Turns on a real frosted-glass blur of the desktop behind the window.

    Windows-only (10 1803+/11), via the undocumented but long-stable
    SetWindowCompositionAttribute API. Silently does nothing anywhere else
    or if the call fails - the QSS gradient background is the fallback.
    """
    if sys.platform != "win32":
        return False
    try:
        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int),
            ]

        class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.POINTER(ACCENT_POLICY)),
                ("SizeOfData", ctypes.c_size_t),
            ]

        ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
        WCA_ACCENT_POLICY = 19

        red, green, blue, alpha = 0x24, 0x1b, 0x4e, 0x99
        gradient_color = (alpha << 24) | (blue << 16) | (green << 8) | red

        accent = ACCENT_POLICY()
        accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 2
        accent.GradientColor = gradient_color
        accent.AnimationId = 0

        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = WCA_ACCENT_POLICY
        data.SizeOfData = ctypes.sizeof(accent)
        data.Data = ctypes.pointer(accent)

        set_attr = ctypes.windll.user32.SetWindowCompositionAttribute
        result = set_attr(ctypes.c_int(hwnd), ctypes.pointer(data))
        return bool(result)
    except Exception:  # noqa: BLE001
        return False


def set_windows_titlebar(
    hwnd: int,
    caption_rgb: tuple[int, int, int] = (0x24, 0x1b, 0x4e),
    text_rgb: tuple[int, int, int] = (255, 255, 255),
) -> bool:
    """Colours the native title bar (Windows 11 only; a no-op elsewhere)."""
    if sys.platform != "win32":
        return False
    try:
        dwm_set = ctypes.windll.dwmapi.DwmSetWindowAttribute

        def colorref(rgb: tuple[int, int, int]) -> int:
            r, g, b = rgb
            return r | (g << 8) | (b << 16)

        def set_attr(attribute: int, value: int) -> int:
            val = ctypes.c_int(value)
            return dwm_set(ctypes.c_void_p(hwnd), ctypes.c_uint(attribute), ctypes.byref(val), ctypes.sizeof(val))

        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_BORDER_COLOR = 34
        DWMWA_CAPTION_COLOR = 35
        DWMWA_TEXT_COLOR = 36

        # Dark caption => light min/max/close glyphs (and the other way round).
        luminance = 0.299 * caption_rgb[0] + 0.587 * caption_rgb[1] + 0.114 * caption_rgb[2]
        set_attr(DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if luminance < 128 else 0)
        ok = set_attr(DWMWA_CAPTION_COLOR, colorref(caption_rgb)) == 0
        set_attr(DWMWA_TEXT_COLOR, colorref(text_rgb))
        set_attr(DWMWA_BORDER_COLOR, -2)  # DWMWA_COLOR_NONE: no coloured frame
        return ok
    except Exception:  # noqa: BLE001
        return False
