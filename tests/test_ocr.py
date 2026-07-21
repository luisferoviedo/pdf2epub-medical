import fitz

from pdf2epub import ocr
from tests.fixtures import make_scanned_pdf, make_two_column_pdf


def test_classify_pages_digital(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    make_two_column_pdf(pdf_path, pages=2, with_toc=False)

    doc = fitz.open(pdf_path)
    classification = ocr.classify_pages(doc)

    assert all(status == "digital" for status in classification.values())
    assert ocr.needs_ocr(classification) is False
    assert ocr.scanned_ratio(classification) == 0.0


def test_classify_pages_scanned(tmp_path):
    pdf_path = tmp_path / "scan.pdf"
    make_scanned_pdf(pdf_path, pages=3)

    doc = fitz.open(pdf_path)
    classification = ocr.classify_pages(doc)

    assert all(status == "scanned" for status in classification.values())
    assert ocr.needs_ocr(classification) is True
    assert ocr.scanned_ratio(classification) == 1.0


def test_classify_pages_mixed(tmp_path):
    digital_path = tmp_path / "digital.pdf"
    make_two_column_pdf(digital_path, pages=1, with_toc=False)

    # Append a blank (scanned-like, no text layer) page to the digital document.
    mixed = fitz.open(digital_path)
    page = mixed.new_page(width=400, height=600)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 600))
    pix.set_rect(pix.irect, (255, 255, 255))
    page.insert_image(fitz.Rect(0, 0, 400, 600), pixmap=pix)
    mixed_path = tmp_path / "mixed.pdf"
    mixed.save(mixed_path)
    mixed.close()

    doc = fitz.open(mixed_path)
    classification = ocr.classify_pages(doc)
    assert classification[0] == "digital"
    assert classification[1] == "scanned"
    assert 0.0 < ocr.scanned_ratio(classification) < 1.0
