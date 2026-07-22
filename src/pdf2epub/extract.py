"""Pulls chapter content out of a PDF in reading order.

Handles the three things that break naive `page.get_text()` extraction on
medical textbooks: multi-column layouts, tables (dosage charts, lab values)
that must not be flattened into garbled running text, and headers/footers
that repeat on every page and would otherwise pollute every chapter.
"""

from __future__ import annotations

import re
from collections import Counter

import fitz  # PyMuPDF

from pdf2epub import tables
from pdf2epub.images import content_hash, recompress
from pdf2epub.models import Chapter, ChapterContent, ImageBlock, TableBlock, TextBlock

HEADER_FOOTER_ZONE_RATIO = 0.10  # top/bottom 10% of page height
HEADER_FOOTER_MIN_FREQUENCY = 0.60  # must repeat on >=60% of sampled pages
FULL_WIDTH_RATIO = 0.60  # blocks wider than this fraction of page count as "full width"
COLUMN_GAP_RATIO = 0.08  # min horizontal gap (as fraction of page width) to split columns

_DIGIT_RUN_RE = re.compile(r"\d+")


def _normalize_repeat_key(text: str) -> str:
    """Collapses digit runs to '#' so "Capitulo 3 - Pagina 45" and "Capitulo 3
    - Pagina 46" are recognized as the same repeating header/footer instead
    of two headers that each show up on only one page (below the frequency
    threshold) and slip through unfiltered."""
    return _DIGIT_RUN_RE.sub("#", text)


def detect_repeated_texts(doc: fitz.Document, sample_every: int = 5) -> set[str]:
    """Finds text patterns that repeat near the top/bottom margin across
    sampled pages. Returns normalized keys (see _normalize_repeat_key) —
    callers must normalize candidate text the same way before checking
    membership.
    """
    counts: Counter[str] = Counter()
    sampled = 0
    for page_index in range(0, doc.page_count, max(sample_every, 1)):
        page = doc[page_index]
        height = page.rect.height
        top_cut = height * HEADER_FOOTER_ZONE_RATIO
        bottom_cut = height * (1 - HEADER_FOOTER_ZONE_RATIO)
        sampled += 1
        for block in page.get_text("dict").get("blocks", []):
            bbox = block.get("bbox")
            if not bbox:
                continue
            y0, y1 = bbox[1], bbox[3]
            if y1 > top_cut and y0 < bottom_cut:
                continue  # not in header/footer zone
            text = "".join(span["text"] for line in block.get("lines", []) for span in line.get("spans", [])).strip()
            if text:
                counts[_normalize_repeat_key(text)] += 1

    if sampled == 0:
        return set()
    threshold = max(2, int(sampled * HEADER_FOOTER_MIN_FREQUENCY))
    return {key for key, n in counts.items() if n >= threshold}


def _cluster_columns(x_starts: list[float], page_width: float) -> list[float]:
    """Returns sorted column boundary starts found via gaps in block x0 positions."""
    if not x_starts:
        return [0.0]
    uniq = sorted(set(x_starts))
    columns = [uniq[0]]
    gap_threshold = page_width * COLUMN_GAP_RATIO
    for x in uniq[1:]:
        if x - columns[-1] > gap_threshold:
            columns.append(x)
    return columns


def _column_index(x0: float, columns: list[float]) -> int:
    best_i, best_dist = 0, float("inf")
    for i, col_x in enumerate(columns):
        dist = abs(x0 - col_x)
        if dist < best_dist:
            best_i, best_dist = i, dist
    return best_i


def _order_blocks(blocks: list[dict], page_width: float) -> list[dict]:
    """Sorts blocks into reading order: cluster by column (x0), then top-to-bottom.

    Full-width blocks (headings, captions spanning the page) are excluded from
    column clustering and instead anchor a fresh reading-order boundary — text
    before them and after them isn't reshuffled across the heading.
    """
    narrow = [b for b in blocks if (b["bbox"][2] - b["bbox"][0]) < page_width * FULL_WIDTH_RATIO]
    columns = _cluster_columns([b["bbox"][0] for b in narrow], page_width)

    def sort_key(b: dict) -> tuple[int, int, float]:
        width = b["bbox"][2] - b["bbox"][0]
        is_full_width = width >= page_width * FULL_WIDTH_RATIO
        col = -1 if is_full_width else _column_index(b["bbox"][0], columns)
        # Full-width blocks (-1) still need to interleave by vertical position
        # relative to columns, so we bucket by a coarse y-band first.
        y_band = int(b["bbox"][1] // 50)
        return (y_band, col, b["bbox"][1])

    return sorted(blocks, key=sort_key)


def _overlaps(bbox_a: tuple[float, float, float, float], bbox_b: fitz.Rect, min_overlap: float = 0.5) -> bool:
    rect_a = fitz.Rect(bbox_a)
    inter = rect_a & bbox_b
    if inter.is_empty:
        return False
    return (inter.get_area() / rect_a.get_area()) >= min_overlap if rect_a.get_area() else False


def extract_chapter_content(
    doc: fitz.Document,
    chapter: Chapter,
    repeated_texts: set[str],
    seen_image_hashes: set[str],
    max_image_size: int = 1600,
    jpeg_quality: int = 85,
    scanned_pages: set[int] | None = None,
) -> ChapterContent:
    content = ChapterContent(chapter=chapter)
    scanned_pages = scanned_pages or set()

    for page_index in range(chapter.start_page, chapter.end_page):
        page = doc[page_index]
        page_width = page.rect.width

        table_bboxes: list[fitz.Rect] = []
        if page_index not in scanned_pages:
            # A scanned page's "table" is just part of its one full-page raster
            # image — there's no vector structure to find, and running the
            # (expensive) table-structure heuristic against a page full of
            # small OCR word-boxes is pure cost for zero benefit.
            try:
                found_tables = page.find_tables()
                for table in found_tables.tables:
                    table_bboxes.append(fitz.Rect(table.bbox))
            except Exception:
                pass  # table detection is best-effort; never fail the whole page over it

        table_html = tables.extract_table_html(page, len(table_bboxes)) if table_bboxes else None

        if table_html is not None:
            # Real, searchable text — the ML layout model recognized exactly
            # as many tables as our own cheap detector, so we trust the match.
            for html in table_html:
                content.items.append(TableBlock(html=html))
        else:
            # Fallback: model unavailable, errored, or its table count didn't
            # match ours — render each region as an image rather than risk
            # silently dropping or misplacing a dosage table.
            for table_bbox in table_bboxes:
                pix = page.get_pixmap(clip=table_bbox, matrix=fitz.Matrix(2, 2))
                data, mime = recompress(pix.tobytes("png"), max_side=max_image_size, jpeg_quality=jpeg_quality)
                h = content_hash(data)
                image_id = f"table_{page_index}_{h[:12]}"
                content.items.append(ImageBlock(data=data, mime=mime, image_id=image_id, caption=""))

        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])

        text_blocks = [b for b in blocks if b.get("type") == 0]
        image_blocks_raw = [b for b in blocks if b.get("type") == 1]

        text_blocks = [b for b in text_blocks if not any(_overlaps(b["bbox"], tb) for tb in table_bboxes)]

        ordered = _order_blocks(text_blocks + image_blocks_raw, page_width)

        seen_xrefs_this_page: set[int] = set()
        page_image_rects = _page_image_rects(page)  # computed once, not once per image block

        for block in ordered:
            if block.get("type") == 0:
                text = "".join(
                    span["text"] for line in block.get("lines", []) for span in line.get("spans", [])
                ).strip()
                if not text or _normalize_repeat_key(text) in repeated_texts:
                    continue
                sizes = [span["size"] for line in block.get("lines", []) for span in line.get("spans", [])]
                avg_size = sum(sizes) / len(sizes) if sizes else 0
                kind = "heading" if avg_size >= 14 and len(text) < 120 else "text"
                content.items.append(TextBlock(kind=kind, text=text))
            else:
                bbox = fitz.Rect(block["bbox"])
                xref = _xref_for_bbox(page_image_rects, bbox)
                if xref is None or xref in seen_xrefs_this_page:
                    continue
                seen_xrefs_this_page.add(xref)
                try:
                    raw = doc.extract_image(xref)
                except Exception:
                    continue
                data, mime = recompress(raw["image"], max_side=max_image_size, jpeg_quality=jpeg_quality)
                h = content_hash(data)
                if h in seen_image_hashes:
                    continue  # skip repeated logos/watermarks
                seen_image_hashes.add(h)
                image_id = f"img_{page_index}_{h[:12]}"
                content.items.append(ImageBlock(data=data, mime=mime, image_id=image_id))

    return content


def _page_image_rects(page: fitz.Page) -> list[tuple[int, fitz.Rect]]:
    """(xref, rect) pairs for every image placement on the page, computed once.

    A page with N images calling get_images()+get_image_rects() once per
    image block (instead of once for the page) turns extraction into an
    O(N^2) scan — pages with dozens of figures (common in illustrated
    textbooks) made this the dominant cost.
    """
    pairs: list[tuple[int, fitz.Rect]] = []
    for img in page.get_images(full=True):
        xref = img[0]
        for rect in page.get_image_rects(xref):
            pairs.append((xref, rect))
    return pairs


def _xref_for_bbox(page_image_rects: list[tuple[int, fitz.Rect]], bbox: fitz.Rect) -> int | None:
    for xref, rect in page_image_rects:
        if rect.intersects(bbox):
            return xref
    return None
