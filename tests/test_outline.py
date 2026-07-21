import fitz

from pdf2epub import outline
from tests.fixtures import make_plain_pdf, make_two_column_pdf


def test_chapters_from_outline(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    make_two_column_pdf(pdf_path, pages=3, with_toc=True)

    doc = fitz.open(pdf_path)
    chapters = outline.detect_chapters(doc)

    assert len(chapters) == 3
    assert chapters[0].title == "Capitulo 1"
    assert chapters[0].start_page == 0
    assert chapters[0].end_page == 1
    assert chapters[-1].end_page == doc.page_count


def test_font_heuristic_fallback_when_no_outline(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    make_plain_pdf(pdf_path, pages=4, fallback_headings=True)

    doc = fitz.open(pdf_path)
    assert doc.get_toc(simple=True) == []

    chapters = outline.detect_chapters(doc)
    assert len(chapters) >= 1
    assert chapters[0].start_page == 0
    assert chapters[-1].end_page == doc.page_count


def test_fixed_size_fallback_when_nothing_else_works(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    make_plain_pdf(pdf_path, pages=10, fallback_headings=False)

    doc = fitz.open(pdf_path)
    chapters = outline.detect_chapters(doc, fallback_every=4)

    assert [c.title for c in chapters] == ["Parte 1", "Parte 2", "Parte 3"]
    assert chapters[0].start_page == 0
    assert chapters[0].end_page == 4
    assert chapters[-1].end_page == 10
