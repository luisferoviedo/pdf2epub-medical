import fitz

from pdf2epub import outline
from pdf2epub.models import Chapter
from tests.fixtures import make_plain_pdf, make_two_column_pdf


def _covered_pages(chapters: list[Chapter]) -> set[int]:
    return {p for ch in chapters for p in range(ch.start_page, ch.end_page)}


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
    """Headings on only some pages (a realistic chapter-break pattern) —
    the font heuristic should fire and detect_chapters should use it."""
    pdf_path = tmp_path / "book.pdf"
    doc = fitz.open()
    for i in range(12):
        page = doc.new_page(width=400, height=600)
        if i in (0, 4, 8):  # 3 chapters of 4 pages each, not one-per-page
            page.insert_text((50, 50), f"Titulo {i + 1}", fontsize=20)
        page.insert_textbox(fitz.Rect(30, 90, 370, 550), "Texto de cuerpo. " * 20, fontsize=9)
    doc.save(pdf_path)
    doc.close()

    doc = fitz.open(pdf_path)
    assert doc.get_toc(simple=True) == []

    chapters = outline.detect_chapters(doc)
    assert len(chapters) == 3
    assert chapters[0].start_page == 0
    assert chapters[-1].end_page == doc.page_count


def test_font_heuristic_rejects_one_heading_per_page(tmp_path):
    """A running header/page-number marginally larger than body text on
    EVERY page must not turn into one 1-page "chapter" per page — it should
    be rejected as implausible and fall through to the fixed-size fallback."""
    pdf_path = tmp_path / "book.pdf"
    make_plain_pdf(pdf_path, pages=10, fallback_headings=True)  # heading on every page

    doc = fitz.open(pdf_path)
    chapters = outline.detect_chapters(doc, fallback_every=4)

    assert [c.title for c in chapters] == ["Parte 1", "Parte 2", "Parte 3"]


def test_fixed_size_fallback_when_nothing_else_works(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    make_plain_pdf(pdf_path, pages=10, fallback_headings=False)

    doc = fitz.open(pdf_path)
    chapters = outline.detect_chapters(doc, fallback_every=4)

    assert [c.title for c in chapters] == ["Parte 1", "Parte 2", "Parte 3"]
    assert chapters[0].start_page == 0
    assert chapters[0].end_page == 4
    assert chapters[-1].end_page == 10


def test_outline_not_starting_at_page_one_gets_front_matter_chapter(tmp_path):
    """Regression test: a PDF whose outline's first bookmark isn't on page 1
    (cover, copyright page, foreword before chapter 1 — the common case)
    must not silently drop those leading pages."""
    pdf_path = tmp_path / "book.pdf"
    doc = fitz.open()
    for i in range(10):
        page = doc.new_page(width=400, height=600)
        page.insert_text((50, 50), f"Pagina {i}", fontsize=10)
    doc.set_toc([[1, "Capitulo 1", 5], [1, "Capitulo 2", 8]])  # 1-based; starts mid-book
    doc.save(pdf_path)
    doc.close()

    doc = fitz.open(pdf_path)
    chapters = outline.detect_chapters(doc)

    assert _covered_pages(chapters) == set(range(doc.page_count))
    assert chapters[0].start_page == 0
    assert chapters[0].title == "Introducción"


def test_all_strategies_cover_every_page(tmp_path):
    """Whatever strategy wins, no page should be silently dropped."""
    # Outline path
    outline_pdf = tmp_path / "outline.pdf"
    doc = fitz.open()
    for i in range(10):
        doc.new_page(width=400, height=600).insert_text((50, 50), f"p{i}", fontsize=10)
    doc.set_toc([[1, "Cap 1", 3], [1, "Cap 2", 7]])
    doc.save(outline_pdf)
    doc.close()

    # Fixed-size fallback path
    plain_pdf = tmp_path / "plain.pdf"
    make_plain_pdf(plain_pdf, pages=10, fallback_headings=False)

    for path in (outline_pdf, plain_pdf):
        doc = fitz.open(path)
        chapters = outline.detect_chapters(doc, fallback_every=4)
        assert _covered_pages(chapters) == set(range(doc.page_count)), f"{path}: pages dropped"
