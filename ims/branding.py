"""Logo validation, default monograms and private, institution-scoped file storage."""
from __future__ import annotations

import base64
import io
import uuid
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import db
from .profiles import ACCENTS

MAX_LOGO_BYTES = 2 * 1024 * 1024
LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
LOGO_FORMATS = {"PNG", "JPEG", "WEBP"}

MAX_DOC_BYTES = 5 * 1024 * 1024
DOC_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp"}

Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs early


class UploadError(ValueError):
    pass


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_image(filename: str, data: bytes, max_bytes: int = MAX_LOGO_BYTES,
                   max_side: int = 512) -> bytes:
    """Check extension, size and real content; return a clean re-encoded PNG.

    Re-encoding strips metadata and anything appended to the file, so the stored
    file is always a plain image no matter what was uploaded.
    """
    if _ext(filename) not in LOGO_EXTENSIONS:
        raise UploadError("Only PNG, JPG/JPEG or WebP images are allowed.")
    if not data:
        raise UploadError("The file is empty.")
    if len(data) > max_bytes:
        raise UploadError(f"The image is larger than {max_bytes // (1024 * 1024)} MB.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            probe.verify()
        if fmt not in LOGO_FORMATS:
            raise UploadError("The file content is not a PNG, JPEG or WebP image.")
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            if min(img.size) < 16:
                raise UploadError("The image is too small (minimum 16×16 pixels).")
            img = img.convert("RGBA")
            img.thumbnail((max_side, max_side))
            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except UploadError:
        raise
    except Exception as exc:  # Pillow raises many different errors for bad files
        raise UploadError("The file is not a valid image.") from exc


def validate_logo(filename: str, data: bytes) -> bytes:
    return validate_image(filename, data, MAX_LOGO_BYTES, 512)


def validate_document(filename: str, data: bytes) -> tuple[bytes, str, str]:
    """Return (content, extension, mime) for an allowed document upload."""
    ext = _ext(filename)
    if ext not in DOC_EXTENSIONS:
        raise UploadError("Allowed document types: PDF, PNG, JPG/JPEG, WebP.")
    if len(data) > MAX_DOC_BYTES:
        raise UploadError("Documents must be 5 MB or smaller.")
    if ext == "pdf":
        if not data.startswith(b"%PDF-"):
            raise UploadError("The file content is not a PDF document.")
        return data, "pdf", "application/pdf"
    png = validate_image(filename, data, MAX_DOC_BYTES, 2000)
    return png, "png", "image/png"


# --------------------------------------------------------------------------- #
# Private storage: media/institutions/<id>/<kind>/<random>.<ext>
# --------------------------------------------------------------------------- #
def _tenant_dir(iid: int) -> Path:
    return (db.media_root() / "institutions" / str(int(iid))).resolve()


def save_file(iid: int, kind: str, content: bytes, ext: str) -> str:
    if kind not in ("logo", "uploads", "photos"):
        raise ValueError("unknown storage kind")
    rel = Path("institutions") / str(int(iid)) / kind / f"{uuid.uuid4().hex}.{ext}"
    full = db.media_root() / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(content)
    return rel.as_posix()


def read_file(iid: int, rel_path: str | None) -> bytes | None:
    """Read a stored file only if it lives inside this institution's folder."""
    if not rel_path:
        return None
    full = (db.media_root() / rel_path).resolve()
    tenant = _tenant_dir(iid)
    if tenant not in full.parents or not full.is_file():
        return None
    return full.read_bytes()


def delete_file(iid: int, rel_path: str | None):
    if not rel_path:
        return
    full = (db.media_root() / rel_path).resolve()
    if _tenant_dir(iid) in full.parents and full.is_file():
        full.unlink()


# --------------------------------------------------------------------------- #
# Default monogram when no logo was uploaded
# --------------------------------------------------------------------------- #
def initials(name: str) -> str:
    stop = {"of", "the", "and", "&", "for", "de"}
    words = [w for w in name.replace("-", " ").split() if w.lower() not in stop and w[0].isalnum()]
    if not words:
        return "IM"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


@lru_cache(maxsize=64)
def monogram_png(name: str, accent: str = "Indigo", size: int = 256) -> bytes:
    a, b = (_hex(x) for x in ACCENTS.get(accent, ACCENTS["Indigo"]))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGBA", (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=size // 4, fill=255)
    img.paste(grad, (0, 0), mask)
    draw = ImageDraw.Draw(img)
    text = initials(name)
    font = ImageFont.load_default(size=int(size * 0.42))
    box = draw.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    draw.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), text, font=font, fill="white")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def logo_bytes(inst: dict, accent: str = "Indigo") -> bytes:
    """Institution logo, or the generated monogram if none was uploaded."""
    data = read_file(inst["id"], inst.get("logo_path"))
    return data or monogram_png(inst["name"], accent)


def data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()
