"""Splits a PDF into chapters for the EPUB table of contents.

Three strategies, tried in order, because a 2500-page book with no chapter
breaks produces one giant XHTML file that crashes e-readers:

1. PDF outline (bookmarks), top-level entries.
2. Heuristic: treat any text span whose font size clearly exceeds the
   dominant (body-text) font size as a heading, and start a new chapter
   there.
3. Fallback: cut every ``fallback_every`` pages into a "Parte N".
"""

from __future__ import annotations

from collections import Counter

import fitz  # PyMuPDF

from pdf2epub.models import Chapter


def chapters_from_outline(doc: fitz.Document) -> list[Chapter]:
    toc = doc.get_toc(simple=True)  # [[level, title, page1based], ...]
    top_level = [entry for entry in toc if entry[0] == 1]
    if not top_level:
        return []

    chapters: list[Chapter] = []
    for i, (_level, title, page1based) in enumerate(top_level):
        start = max(page1based - 1, 0)
        end = (top_level[i + 1][2] - 1) if i + 1 < len(top_level) else doc.page_count
        if end <= start:
            continue
        chapters.append(Chapter(title=title.strip() or f"Capítulo {i + 1}", start_page=start, end_page=end))
    return chapters


def chapters_from_font_heuristic(doc: fitz.Document, size_ratio: float = 1.2) -> list[Chapter]:
    """A heading is a span whose font size is >= size_ratio times the body
    (most common) font size. Percentile-based cutoffs break down when there
    are only a couple of distinct sizes on the page — the cutoff can land
    exactly on the heading size itself. Comparing against the dominant size
    avoids that: a book with no real headings has one dominant size and
    nothing exceeds it, so it correctly yields no chapters here.
    """
    sizes: list[float] = []
    headings: list[tuple[int, str, float]] = []  # (page_index, text, size)

    # get_text("dict") is the expensive call here; cache each page's result
    # instead of parsing every page twice (once for sizes, once for headings).
    page_dicts: list[dict] = []
    for page_index in range(doc.page_count):
        page_dict = doc[page_index].get_text("dict")
        page_dicts.append(page_dict)
        for block in page_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span["text"].strip()
                    if not text:
                        continue
                    sizes.append(round(span["size"], 1))

    if not sizes:
        return []

    body_size, _count = Counter(sizes).most_common(1)[0]
    cutoff = body_size * size_ratio

    for page_index, page_dict in enumerate(page_dicts):
        for block in page_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span["text"].strip()
                    if text and span["size"] >= cutoff and len(text) < 120:
                        headings.append((page_index, text, span["size"]))
                        break  # one heading candidate per line is enough

    if not headings:
        return []

    # Collapse headings that land on the same page into one chapter start.
    seen_pages: set[int] = set()
    deduped: list[tuple[int, str]] = []
    for page_index, text, _size in headings:
        if page_index in seen_pages:
            continue
        seen_pages.add(page_index)
        deduped.append((page_index, text))

    chapters: list[Chapter] = []
    for i, (page_index, title) in enumerate(deduped):
        end = deduped[i + 1][0] if i + 1 < len(deduped) else doc.page_count
        if end <= page_index:
            continue
        chapters.append(Chapter(title=title, start_page=page_index, end_page=end))
    return chapters


def chapters_by_fixed_size(doc: fitz.Document, fallback_every: int = 50) -> list[Chapter]:
    chapters: list[Chapter] = []
    for i, start in enumerate(range(0, doc.page_count, fallback_every)):
        end = min(start + fallback_every, doc.page_count)
        chapters.append(Chapter(title=f"Parte {i + 1}", start_page=start, end_page=end))
    return chapters


def detect_chapters(doc: fitz.Document, fallback_every: int = 50) -> list[Chapter]:
    chapters = chapters_from_outline(doc)
    if chapters:
        return chapters

    chapters = chapters_from_font_heuristic(doc)
    if chapters:
        return chapters

    return chapters_by_fixed_size(doc, fallback_every=fallback_every)
