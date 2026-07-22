"""Table extraction via pymupdf-layout's ML model — real, selectable HTML
tables instead of a flattened image, for the dosage/lab-value tables medical
textbooks are full of.

Benchmarked at ~270ms/page for the full layout model, which is too slow to
run on every page of a 2500-page book. So this is only invoked on pages
where PyMuPDF's cheap `find_tables()` already found a candidate region —
the ML model refines a small, pre-filtered subset instead of scanning
everything itself.
"""

from __future__ import annotations

import re
import threading

import fitz  # PyMuPDF
from lxml import html as lxml_html

_TABLE_RE = re.compile(r"<table>.*?</table>", re.DOTALL)

_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                import pymupdf.layout as layout

                _model = layout.DocumentLayoutAnalyzer.get_model()
    return _model


def _normalize_html(raw_html: str) -> str:
    """Re-serializes as well-formed XML: EPUB's XHTML is strict, and the
    model's raw HTML isn't guaranteed to have escaped entities or closed
    tags the way lxml/ebooklib require."""
    fragment = lxml_html.fromstring(raw_html)
    return lxml_html.tostring(fragment, encoding="unicode", method="xml")


def extract_table_html(page: fitz.Page, expected_count: int) -> list[str] | None:
    """Returns one normalized <table> HTML string per table on the page, in
    document order, or None if the model didn't find exactly as many tables
    as the caller's own (cheaper) detection expected — callers should fall
    back to their own rendering in that case rather than guess at a mismatch.
    """
    try:
        raw = _get_model().to_markdown_html_table(page)
        matches = _TABLE_RE.findall(raw)
        if len(matches) != expected_count:
            return None
        return [_normalize_html(m) for m in matches]
    except Exception:
        return None
