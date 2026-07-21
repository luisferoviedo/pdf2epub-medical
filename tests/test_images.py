import io

from PIL import Image

from pdf2epub.images import content_hash, recompress


def _make_png(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), (200, 50, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_recompress_downscales_large_images():
    data = _make_png(3000, 1500)
    out, mime = recompress(data, max_side=1600, jpeg_quality=85)

    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) <= 1600
        assert img.format == "JPEG"


def test_recompress_leaves_small_images_unscaled():
    data = _make_png(400, 300)
    out, _mime = recompress(data, max_side=1600, jpeg_quality=85)

    with Image.open(io.BytesIO(out)) as img:
        assert img.size == (400, 300)


def test_recompress_flattens_alpha():
    img = Image.new("RGBA", (100, 100), (10, 20, 30, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    out, mime = recompress(buf.getvalue())
    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(out)) as decoded:
        assert decoded.mode == "RGB"


def test_content_hash_is_stable_and_distinguishes_content():
    a = _make_png(100, 100)
    b = _make_png(100, 101)
    assert content_hash(a) == content_hash(a)
    assert content_hash(a) != content_hash(b)
