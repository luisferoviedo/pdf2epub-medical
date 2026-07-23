from unittest.mock import patch

import fitz

from pdf2epub import extract
from pdf2epub.models import Chapter, ImageBlock, TextBlock
from tests.fixtures import make_mixed_scan_digital_pdf, make_two_column_pdf


def test_two_column_reading_order_keeps_columns_intact(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    make_two_column_pdf(pdf_path, pages=1, with_toc=False)

    doc = fitz.open(pdf_path)
    chapter = Chapter(title="Capitulo 1", start_page=0, end_page=1)

    content = extract.extract_chapter_content(doc, chapter, repeated_texts=set(), seen_image_hashes=set())

    texts = [item.text for item in content.items if isinstance(item, TextBlock)]
    left_idx = next(i for i, t in enumerate(texts) if "Columna izquierda" in t)
    right_idx = next(i for i, t in enumerate(texts) if "Columna derecha" in t)

    # The left column's paragraph must be fully ordered before the right
    # column's, not interleaved line-by-line.
    assert left_idx < right_idx


def test_repeated_header_footer_is_excluded(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    doc = fitz.open()
    for i in range(6):
        page = doc.new_page(width=400, height=600)
        page.insert_text((50, 20), "Manual de Medicina - Capitulo X", fontsize=8)
        page.insert_textbox(fitz.Rect(30, 90, 370, 550), f"Contenido pagina {i}. " * 10, fontsize=9)
    doc.save(pdf_path)
    doc.close()

    doc = fitz.open(pdf_path)
    repeated = extract.detect_repeated_texts(doc, sample_every=1)
    assert "Manual de Medicina - Capitulo X" in repeated

    chapter = Chapter(title="C1", start_page=0, end_page=doc.page_count)
    content = extract.extract_chapter_content(doc, chapter, repeated_texts=repeated, seen_image_hashes=set())
    texts = [item.text for item in content.items if isinstance(item, TextBlock)]
    assert all("Manual de Medicina" not in t for t in texts)


def test_repeated_header_with_embedded_page_number_is_excluded(tmp_path):
    """A header like "Capitulo 3 - Pagina 45" changes on every page (the page
    number), so exact-string matching never sees it repeat and it leaks into
    every chapter. Digit-run normalization must still recognize the pattern."""
    pdf_path = tmp_path / "book.pdf"
    doc = fitz.open()
    for i in range(6):
        page = doc.new_page(width=400, height=600)
        page.insert_text((50, 20), f"Capitulo 3 - Pagina {45 + i}", fontsize=8)
        page.insert_textbox(fitz.Rect(30, 90, 370, 550), f"Contenido pagina {i}. " * 10, fontsize=9)
    doc.save(pdf_path)
    doc.close()

    doc = fitz.open(pdf_path)
    repeated = extract.detect_repeated_texts(doc, sample_every=1)
    assert "Capitulo # - Pagina #" in repeated

    chapter = Chapter(title="C1", start_page=0, end_page=doc.page_count)
    content = extract.extract_chapter_content(doc, chapter, repeated_texts=repeated, seen_image_hashes=set())
    texts = [item.text for item in content.items if isinstance(item, TextBlock)]
    assert all("Pagina 4" not in t and "Pagina 5" not in t for t in texts)


def test_per_section_running_header_is_excluded_in_multipart_book(tmp_path):
    """Regression test for a real bug found converting the actual Nelson
    Textbook of Pediatrics: a multi-part book's running head changes per
    Part (e.g. "Part I ..." for 300 pages, then "Part II ..." for the next
    400), so no single header text ever covers a majority of the *whole*
    book. The old >=60%-of-book threshold never caught any of them; each
    part's header must still be recognized as repeated within its own span.
    """
    pdf_path = tmp_path / "book.pdf"
    doc = fitz.open()
    # Three parts of 8 pages each with genuinely different titles (like real
    # roman-numeral part headers with distinct section names) — no single
    # header reaches 60% of the 24-page book (each is exactly 33%), but each
    # is clearly repeating within its own span.
    part_titles = ["The Field of Pediatrics", "Infectious Diseases", "Metabolic Disorders"]
    for part, title in enumerate(part_titles):
        for i in range(8):
            page = doc.new_page(width=400, height=600)
            page.insert_text((40, 20), f"Part {part + 1}  u  {title}", fontsize=8)
            page.insert_textbox(fitz.Rect(30, 90, 370, 550), f"Contenido parte {part} pagina {i}. " * 10, fontsize=9)
    doc.save(pdf_path)
    doc.close()

    doc = fitz.open(pdf_path)
    repeated = extract.detect_repeated_texts(doc, sample_every=1)
    for title in part_titles:
        assert f"Part #  u  {title}" in repeated

    chapter = Chapter(title="C1", start_page=0, end_page=doc.page_count)
    content = extract.extract_chapter_content(doc, chapter, repeated_texts=repeated, seen_image_hashes=set())
    texts = [item.text for item in content.items if isinstance(item, TextBlock)]
    assert all(title not in t for t in texts for title in part_titles)


def test_find_tables_skipped_on_scanned_pages(tmp_path):
    """A scanned page's "table" is just part of its one full-page raster
    image — running the vector table-structure heuristic against it is
    pure cost for zero benefit, so extract_chapter_content must not call it
    on pages listed in scanned_pages."""
    pdf_path = tmp_path / "mixed.pdf"
    make_mixed_scan_digital_pdf(pdf_path, [False, True])  # page 0 digital, page 1 scanned

    doc = fitz.open(pdf_path)
    chapter = Chapter(title="C1", start_page=0, end_page=2)

    original_find_tables = fitz.Page.find_tables
    called_on_pages = []

    def spy(self, *args, **kwargs):
        called_on_pages.append(self.number)
        return original_find_tables(self, *args, **kwargs)

    with patch.object(fitz.Page, "find_tables", spy):
        extract.extract_chapter_content(doc, chapter, repeated_texts=set(), seen_image_hashes=set(), scanned_pages={1})

    assert called_on_pages == [0]


def test_page_image_rects_computed_once_per_page(tmp_path):
    """Regression test: xref lookup used to call get_images()/get_image_rects()
    once per image block on the page, making extraction O(images^2) on
    illustration-heavy pages. It must now scan the page's images exactly once."""
    import io

    from PIL import Image

    pdf_path = tmp_path / "many_images.pdf"
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for row in range(4):
        for col in range(4):
            img = Image.new("RGB", (20, 20), (row * 10, col * 10, 100))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            x, y = 20 + col * 60, 20 + row * 60
            page.insert_image(fitz.Rect(x, y, x + 40, y + 40), stream=buf.getvalue())
    doc.save(pdf_path)
    doc.close()

    doc = fitz.open(pdf_path)
    chapter = Chapter(title="C1", start_page=0, end_page=1)

    original_get_images = fitz.Page.get_images
    call_count = 0

    def spy(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return original_get_images(self, *args, **kwargs)

    with patch.object(fitz.Page, "get_images", spy):
        content = extract.extract_chapter_content(doc, chapter, repeated_texts=set(), seen_image_hashes=set())

    assert call_count == 1, f"get_images() called {call_count} times for 1 page — should be exactly 1"
    n_images = sum(1 for item in content.items if not isinstance(item, TextBlock))
    assert n_images == 16


def _make_table_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 30), "Tabla de dosis", fontsize=14)
    rows = [["Medicamento", "Dosis"], ["Paracetamol", "10mg/kg"]]
    y = 80
    for row in rows:
        x = 60
        for cell in row:
            page.draw_rect(fitz.Rect(x, y, x + 150, y + 30))
            page.insert_text((x + 5, y + 20), cell, fontsize=10)
            x += 150
        y += 30
    doc.save(path)
    doc.close()


def test_table_always_rendered_as_image(tmp_path):
    """Tried extracting tables as real HTML text via an ML layout model, but
    on complex multi-column data tables it silently scrambled cell order —
    worse than an image, since a reader can't tell the numbers are wrong.
    Tables always render as images now, no text-extraction attempt at all."""
    pdf_path = tmp_path / "table.pdf"
    _make_table_pdf(pdf_path)

    doc = fitz.open(pdf_path)
    chapter = Chapter(title="C1", start_page=0, end_page=1)
    content = extract.extract_chapter_content(doc, chapter, repeated_texts=set(), seen_image_hashes=set())

    assert any(isinstance(item, ImageBlock) for item in content.items)


def test_table_image_is_padded_and_rendered_at_higher_zoom(tmp_path):
    """Regression test for a real bug: find_tables() can miss the table's
    true edge outright (a whole last column, in one real book, not just a
    few points) — a table image must be rendered padded beyond the raw
    detected bbox, and at a high enough zoom to stay legible, not the bare
    bbox at 2x."""
    import io

    from PIL import Image

    pdf_path = tmp_path / "table.pdf"
    _make_table_pdf(pdf_path)

    doc = fitz.open(pdf_path)
    chapter = Chapter(title="C1", start_page=0, end_page=1)
    content = extract.extract_chapter_content(doc, chapter, repeated_texts=set(), seen_image_hashes=set())

    table_images = [item for item in content.items if isinstance(item, ImageBlock)]
    assert len(table_images) == 1
    with Image.open(io.BytesIO(table_images[0].data)) as img:
        width, height = img.size

    # Raw table bbox is ~300x60 (two 150x30 cells per row, two rows). A bare
    # 2x-zoom, zero-padding render would be exactly 600x120 — the fixed
    # bug. Padded + rendered at TABLE_RENDER_ZOOM must come out larger.
    assert width > 600
    assert height > 120
