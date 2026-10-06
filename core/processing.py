"""Image operations: resize, black border, JPEG conversion.

Each operation takes a PIL.Image and returns a new PIL.Image. The pipeline
is applied in a fixed, sensible order regardless of which combination of
checkboxes the user picked: resize -> border -> (format conversion happens
at save time, since it only affects how the file is written to disk).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from PIL import Image, ImageOps

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".webp"}

RESIZE_MAX_EDGE = 1024
BORDER_PX = 1
BORDER_COLOR = (0, 0, 0)


@dataclass
class Operations:
    resize: bool = False
    border: bool = False
    to_jpeg: bool = False

    @property
    def any(self) -> bool:
        return self.resize or self.border or self.to_jpeg


def resize_to_max_edge(image: Image.Image, max_edge: int = RESIZE_MAX_EDGE) -> Image.Image:
    width, height = image.size
    if max(width, height) <= max_edge:
        return image
    if width >= height:
        new_width = max_edge
        new_height = round(height * (max_edge / width))
    else:
        new_height = max_edge
        new_width = round(width * (max_edge / height))
    return image.resize((new_width, new_height), Image.LANCZOS)


def add_black_border(image: Image.Image, px: int = BORDER_PX) -> Image.Image:
    return ImageOps.expand(image, border=px, fill=BORDER_COLOR)


def process_file(path: str, ops: Operations) -> str:
    """Applies the requested operations to the image at `path`, overwriting
    it in place. Returns the (possibly new, if format changed) file path.
    """
    with Image.open(path) as img:
        img.load()
        exif = img.info.get("exif")
        result = img.convert("RGB") if (ops.to_jpeg and img.mode in ("RGBA", "P", "LA")) else img.copy()

        if ops.resize:
            result = resize_to_max_edge(result)
        if ops.border:
            result = add_black_border(result)

        root, ext = os.path.splitext(path)
        if ops.to_jpeg and ext.lower() not in (".jpg", ".jpeg"):
            new_path = root + ".jpg"
            if result.mode != "RGB":
                result = result.convert("RGB")
            save_kwargs = {"quality": 92}
            if exif:
                save_kwargs["exif"] = exif
            result.save(new_path, "JPEG", **save_kwargs)
            os.remove(path)
            return new_path

        if ext.lower() in (".jpg", ".jpeg"):
            if result.mode != "RGB":
                result = result.convert("RGB")
            save_kwargs = {"quality": 92}
            if exif:
                save_kwargs["exif"] = exif
            result.save(path, "JPEG", **save_kwargs)
        else:
            result.save(path)
        return path
