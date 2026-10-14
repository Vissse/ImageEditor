"""Reading files into QImage, with a Pillow/PyMuPDF fallback for formats Qt
cannot decode itself (PDF, HEIC, PSD...). Safe to call from worker threads."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader

from core.processing import load_preview_image, to_rgb


def pil_to_qimage(image) -> QImage:
    rgb = to_rgb(image)
    data = rgb.tobytes("raw", "RGB")
    return QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format_RGB888).copy()


def _too_big(size: QSize, max_size: QSize) -> bool:
    return size.width() > max_size.width() or size.height() > max_size.height()


def read_image(path: str, max_size: QSize, upscale: bool = False) -> QImage:
    """The file scaled to fit `max_size` (smaller images are enlarged only
    with `upscale`), upright; a null image on failure."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 0 and size.height() > 0:
        if upscale or _too_big(size, max_size):
            reader.setScaledSize(size.scaled(max_size, Qt.KeepAspectRatio))
    image = reader.read()
    if not image.isNull():
        return image
    try:
        image = pil_to_qimage(load_preview_image(path, max(max_size.width(), max_size.height())))
    except Exception:  # noqa: BLE001 - unreadable or still being written
        return QImage()
    if upscale or _too_big(image.size(), max_size):
        image = image.scaled(max_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image
