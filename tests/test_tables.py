from unittest.mock import patch

import fitz

from pdf2epub import tables


def _make_table_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 30), "Tabla de dosis", fontsize=14)
    rows = [
        ["Medicamento", "Dosis", "Frecuencia"],
        ["Paracetamol", "10mg/kg", "c/8h"],
        ["Ibuprofeno", "5mg/kg", "c/6h"],
    ]
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
    return doc


def test_extract_table_html_returns_real_selectable_text(tmp_path):
    pdf_path = tmp_path / "table.pdf"
    _make_table_pdf(pdf_path)

    doc = fitz.open(pdf_path)
    page = doc[0]
    result = tables.extract_table_html(page, expected_count=1)

    assert result is not None
    assert len(result) == 1
    html = result[0]
    assert "<table>" in html
    assert "Paracetamol" in html
    assert "10mg/kg" in html


def test_extract_table_html_returns_none_on_count_mismatch(tmp_path):
    pdf_path = tmp_path / "table.pdf"
    _make_table_pdf(pdf_path)

    doc = fitz.open(pdf_path)
    page = doc[0]
    # Deliberately wrong expected count — caller's cheap detector and the ML
    # model disagreeing must fall back, not guess which table is which.
    result = tables.extract_table_html(page, expected_count=5)

    assert result is None


def test_extract_table_html_returns_none_on_model_error(tmp_path):
    pdf_path = tmp_path / "table.pdf"
    _make_table_pdf(pdf_path)

    doc = fitz.open(pdf_path)
    page = doc[0]

    with patch.object(tables, "_get_model", side_effect=RuntimeError("boom")):
        result = tables.extract_table_html(page, expected_count=1)

    assert result is None
