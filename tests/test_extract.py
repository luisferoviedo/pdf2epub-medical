import fitz

from pdf2epub import extract
from pdf2epub.models import Chapter, TextBlock
from tests.fixtures import make_two_column_pdf


def test_two_column_reading_order_keeps_columns_intact(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    make_two_column_pdf(pdf_path, pages=1, with_toc=False)

    doc = fitz.open(pdf_path)
    chapter = Chapter(title="Capitulo 1", start_page=0, end_page=1)

    content = extract.extract_chapter_content(
        doc, chapter, repeated_texts=set(), seen_image_hashes=set()
    )

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
    content = extract.extract_chapter_content(
        doc, chapter, repeated_texts=repeated, seen_image_hashes=set()
    )
    texts = [item.text for item in content.items if isinstance(item, TextBlock)]
    assert all("Manual de Medicina" not in t for t in texts)
