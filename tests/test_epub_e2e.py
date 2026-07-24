import shutil
import subprocess
import zipfile

import pytest

from pdf2epub.pipeline import ConvertOptions, convert
from tests.fixtures import make_two_column_pdf


def test_convert_produces_valid_epub_structure(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    make_two_column_pdf(pdf_path, pages=5, with_toc=True)

    output_path = tmp_path / "book.epub"
    options = ConvertOptions(no_ocr=True)

    events = []
    convert(pdf_path, output_path, options=options, on_progress=lambda *args: events.append(args))

    assert output_path.exists()
    assert any(stage == "build_epub" for stage, _c, _t in events)

    with zipfile.ZipFile(output_path) as zf:
        names = zf.namelist()
        assert names[0] == "mimetype"
        assert zf.read("mimetype") == b"application/epub+zip"
        assert "META-INF/container.xml" in names
        assert any(n.endswith("content.opf") for n in names)
        assert any(n.endswith("nav.xhtml") for n in names)
        assert any(n.endswith("toc.ncx") for n in names)
        chapter_files = [n for n in names if "chap_" in n]
        assert len(chapter_files) == 5


def test_convert_returns_summary_with_real_counts(tmp_path):
    """The summary returned by convert() (and the on_stats live callback)
    must reflect what's actually in the finished EPUB — this is what the
    CLI printout and the web GUI's result card show the user instead of a
    bare "done", so the numbers have to be trustworthy, not just present."""
    import fitz

    pdf_path = tmp_path / "book.pdf"
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 30), "Tabla", fontsize=14)
    for row in range(2):
        for col in range(2):
            x, y = 60 + col * 150, 80 + row * 30
            page.draw_rect(fitz.Rect(x, y, x + 150, y + 30))
            page.insert_text((x + 5, y + 20), f"r{row}c{col}", fontsize=10)
    doc.save(pdf_path)
    doc.close()

    output_path = tmp_path / "book.epub"
    stats_calls: list[dict] = []
    summary = convert(
        pdf_path,
        output_path,
        options=ConvertOptions(no_ocr=True),
        on_stats=lambda s: stats_calls.append(dict(s)),
    )

    assert summary.pages == 1
    assert summary.chapters >= 1
    assert summary.tables == 1
    assert summary.output_bytes == output_path.stat().st_size
    assert summary.output_bytes > 0
    assert summary.elapsed_s >= 0

    # Live callback must have fired at least once, and its final call must
    # agree with the summary — no drift between "live" and "final" counts.
    assert stats_calls
    assert stats_calls[-1]["tables"] == summary.tables


@pytest.mark.skipif(shutil.which("epubcheck") is None, reason="epubcheck no está instalado")
def test_convert_passes_epubcheck(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    make_two_column_pdf(pdf_path, pages=3, with_toc=True)

    output_path = tmp_path / "book.epub"
    convert(pdf_path, output_path, options=ConvertOptions(no_ocr=True))

    result = subprocess.run(
        ["epubcheck", str(output_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
