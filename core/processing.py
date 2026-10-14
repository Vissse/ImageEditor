"""Image operations: resize, black border, JPEG conversion, crop.

Each operation takes a PIL.Image and returns a new PIL.Image. The pipeline
is applied in a fixed, sensible order regardless of which combination of
checkboxes the user picked: resize -> border -> (format conversion happens
at save time, since it only affects how the file is written to disk).

Besides the usual image formats the app reads documents and formats Pillow
cannot write back (PDF, HEIC, PSD...). Those are always converted to JPEG
when processed; a multi-page PDF becomes one JPEG per page.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from PIL import Image, ImageOps

try:  # HEIC/HEIF photos from iPhones
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover - optional dependency
    pillow_heif = None

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - optional dependency
    fitz = None

# Formats that are edited in place (saved back in their own format).
NATIVE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp"}
# Formats that can only be read: processing always turns them into JPEG.
CONVERT_ONLY_EXTENSIONS = {".pdf", ".jfif", ".ico", ".tga", ".psd", ".pcx", ".ppm", ".dib"}
if pillow_heif is not None:
    CONVERT_ONLY_EXTENSIONS |= {".heic", ".heif"}
if fitz is None:
    CONVERT_ONLY_EXTENSIONS.discard(".pdf")

SUPPORTED_EXTENSIONS = NATIVE_EXTENSIONS | CONVERT_ONLY_EXTENSIONS
JPEG_EXTENSIONS = (".jpg", ".jpeg")

RESIZE_MAX_EDGE = 1024
BORDER_PX = 1
BORDER_COLOR = (0, 0, 0)
JPEG_QUALITY = 92
PDF_DPI = 150  # A4 page -> ~1240 x 1754 px, enough for the 1024 px resize


@dataclass
class Operations:
    resize: bool = False
    border: bool = False
    to_jpeg: bool = False

    @property
    def any(self) -> bool:
        return self.resize or self.border or self.to_jpeg


def is_convert_only(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in CONVERT_ONLY_EXTENSIONS


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


def has_black_border(image: Image.Image, dark: int = 48, share: float = 0.97) -> bool:
    """True when the outermost pixel ring is (almost) all black - the image
    already has a border, or black edges where another one would not show.
    Tolerant of JPEG noise, so it also catches borders added by older versions."""
    gray = to_rgb(image).convert("L")
    width, height = gray.size
    if width < 3 or height < 3:
        return False
    edges = [
        gray.crop((0, 0, width, 1)), gray.crop((0, height - 1, width, height)),
        gray.crop((0, 0, 1, height)), gray.crop((width - 1, 0, width, height)),
    ]
    total = sum(e.width * e.height for e in edges)
    black = sum(sum(e.histogram()[: dark + 1]) for e in edges)
    return black >= total * share


@dataclass
class ProcessResult:
    paths: list[str]                                  # resulting file(s)
    applied: list[str] = field(default_factory=list)  # operation ids, see core.state
    skipped_border: bool = False                      # border asked for, image already had one


def to_rgb(image: Image.Image) -> Image.Image:
    """RGB for JPEG; transparent areas become white instead of black."""
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _render_pdf_pages(path: str, dpi: int = PDF_DPI, first_only: bool = False) -> list[Image.Image]:
    if fitz is None:
        raise RuntimeError("Chybí podpora PDF (PyMuPDF)")
    pages = []
    with fitz.open(path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            pages.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            if first_only:
                break
    if not pages:
        raise RuntimeError("PDF neobsahuje žádnou stránku")
    return pages


def load_preview_image(path: str, max_edge: int) -> Image.Image:
    """A display copy of the file (first page of a PDF), upright and at most
    `max_edge` px on its longer side. Used where Qt cannot decode the format."""
    if os.path.splitext(path)[1].lower() == ".pdf":
        image = _render_pdf_pages(path, dpi=72, first_only=True)[0]
        if max(image.size) < max_edge:  # small pages: render sharper
            scale = max_edge / max(image.size)
            image = _render_pdf_pages(path, dpi=int(72 * scale), first_only=True)[0]
    else:
        with Image.open(path) as img:
            img.draft("RGB", (max_edge, max_edge))  # fast JPEG downscale while decoding
            image = ImageOps.exif_transpose(img)
            image.load()
    image.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return image


def _unique(path: str, own: str) -> str:
    """`path`, or "name (2).jpg" etc. when another file already uses it."""
    if not os.path.exists(path) or os.path.normcase(path) == os.path.normcase(own):
        return path
    root, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{root} ({n}){ext}"):
        n += 1
    return f"{root} ({n}){ext}"


def _save_jpeg(image: Image.Image, path: str, exif: bytes | None) -> None:
    save_kwargs = {"quality": JPEG_QUALITY}
    if exif:
        save_kwargs["exif"] = exif
    to_rgb(image).save(path, "JPEG", **save_kwargs)


def process_file(path: str, ops: Operations, has_border: bool = False) -> ProcessResult:
    """Applies the requested operations to the file at `path`, overwriting it
    in place. The result lists the resulting file paths (one for an image, one
    per page inside a new subfolder for a multi-page PDF; a different name when
    the format changed) and what was actually done.

    Nothing is applied twice: resizing and JPEG conversion are naturally
    idempotent, and the border is skipped when `has_border` (known from the
    folder state) or when the image's edge is already black.
    """
    root, ext = os.path.splitext(path)
    ext = ext.lower()
    to_jpeg = ops.to_jpeg or ext in CONVERT_ONLY_EXTENSIONS

    if ext == ".pdf":
        pages, exif = _render_pdf_pages(path), None
    else:
        with Image.open(path) as img:
            img.load()
            exif = img.info.get("exif")
            pages = [img.copy()]

    applied = ["pdf"] if ext == ".pdf" else []
    if ops.resize:
        applied.append("resize")
    skipped_border = False
    results = []
    for page in pages:
        bordered = has_border or has_black_border(page)
        if ops.resize:
            # an existing border sits on top of the 1024 px, so reprocessing
            # does not shrink 1026 -> 1024 and blur the border away
            page = resize_to_max_edge(page, RESIZE_MAX_EDGE + (2 * BORDER_PX if bordered else 0))
        if ops.border:
            if bordered:
                skipped_border = True
            else:
                page = add_black_border(page)
        results.append(page)
    if ops.border and not skipped_border:
        applied.append("border")

    if to_jpeg and ext not in JPEG_EXTENSIONS:
        applied.append("jpeg")
        if len(results) == 1:
            new_path = _unique(f"{root}.jpg", path)
            _save_jpeg(results[0], new_path, exif)
            os.remove(path)
            return ProcessResult([new_path], applied, skipped_border)
        # A multi-page document gets its own subfolder, so its pages do not
        # flood the grid: "doc.pdf" -> "doc/doc_1.jpg", "doc/doc_2.jpg"...
        folder = _unique(root, path)
        os.makedirs(folder)
        stem = os.path.basename(root)
        new_paths = []
        for number, page in enumerate(results, start=1):
            new_path = os.path.join(folder, f"{stem}_{number}.jpg")
            _save_jpeg(page, new_path, exif)
            new_paths.append(new_path)
        os.remove(path)
        return ProcessResult(new_paths, applied, skipped_border)

    result = results[0]
    if ext in JPEG_EXTENSIONS:
        _save_jpeg(result, path, exif)
    else:
        result.save(path)
    return ProcessResult([path], applied, skipped_border)


def crop_file(path: str, box: tuple[float, float, float, float]) -> None:
    """Crops the image at `path` in place. `box` is (left, top, right, bottom)
    as fractions of the upright image (the way it is shown on screen)."""
    with Image.open(path) as img:
        img.load()
        upright = ImageOps.exif_transpose(img)  # also drops the orientation tag
    width, height = upright.size
    left, top, right, bottom = box
    pixels = (
        max(0, round(left * width)), max(0, round(top * height)),
        min(width, round(right * width)), min(height, round(bottom * height)),
    )
    if pixels[2] - pixels[0] < 1 or pixels[3] - pixels[1] < 1:
        raise ValueError("Výřez je příliš malý")
    cropped = upright.crop(pixels)
    exif = upright.getexif()
    exif_bytes = exif.tobytes() if len(exif) else None

    if os.path.splitext(path)[1].lower() in JPEG_EXTENSIONS:
        _save_jpeg(cropped, path, exif_bytes)
    elif exif_bytes and os.path.splitext(path)[1].lower() in (".png", ".webp", ".tiff", ".tif"):
        cropped.save(path, exif=exif_bytes)
    else:
        cropped.save(path)
