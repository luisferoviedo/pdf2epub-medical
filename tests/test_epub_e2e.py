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
