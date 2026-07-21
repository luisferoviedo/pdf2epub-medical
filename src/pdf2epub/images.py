"""Image recompression so a 2500-page illustrated EPUB stays under e-reader size limits."""

from __future__ import annotations

import hashlib
import io

from PIL import Image


def recompress(
    data: bytes,
    max_side: int = 1600,
    jpeg_quality: int = 85,
) -> tuple[bytes, str]:
    """Downscale and re-encode an image as JPEG. Returns (bytes, mime_type).

    Images with an alpha channel are flattened onto white before encoding,
    since EPUB readers vary in transparency support and JPEG has none.
    """
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        if img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        width, height = img.size
        longest = max(width, height)
        if longest > max_side:
            scale = max_side / longest
            img = img.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=jpeg_quality, optimize=True)
        return out.getvalue(), "image/jpeg"


def content_hash(data: bytes) -> str:
    """Stable hash used to deduplicate images repeated across pages (e.g. logos)."""
    return hashlib.sha256(data).hexdigest()
