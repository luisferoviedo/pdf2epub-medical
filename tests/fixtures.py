"""Synthetic PDF generator used across tests instead of shipping real book files."""

from __future__ import annotations

from pathlib import Path

import fitz


def make_two_column_pdf(path: Path, pages: int = 3, with_toc: bool = True) -> None:
    doc = fitz.open()
    left = "Columna izquierda. " * 30
    right = "Columna derecha. " * 30

    for i in range(pages):
        page = doc.new_page(width=400, height=600)
        page.insert_text((50, 50), f"Capitulo {i + 1}", fontsize=18)
        page.insert_textbox(fitz.Rect(30, 90, 190, 550), left, fontsize=9)
        page.insert_textbox(fitz.Rect(210, 90, 370, 550), right, fontsize=9)

    if with_toc:
        toc = [[1, f"Capitulo {i + 1}", i + 1] for i in range(pages)]
        doc.set_toc(toc)

    doc.save(path)
    doc.close()


def make_scanned_pdf(path: Path, pages: int = 2) -> None:
    """A PDF with pages that carry no extractable text layer (simulated scans)."""
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=400, height=600)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 600))
        pix.set_rect(pix.irect, (255, 255, 255))
        page.insert_image(fitz.Rect(0, 0, 400, 600), pixmap=pix)
    doc.save(path)
    doc.close()


def make_plain_pdf(path: Path, pages: int = 5, fallback_headings: bool = False) -> None:
    """A PDF with no outline, for testing font-heuristic and fixed-size fallbacks."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=400, height=600)
        if fallback_headings:
            page.insert_text((50, 50), f"Titulo {i + 1}", fontsize=20)
        page.insert_textbox(fitz.Rect(30, 90, 370, 550), "Texto de cuerpo. " * 20, fontsize=9)
    doc.save(path)
    doc.close()
