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

from pdf2epub.images import content_hash, recompress
from pdf2epub.models import Chapter, ChapterContent, ImageBlock, TextBlock

HEADER_FOOTER_ZONE_RATIO = 0.10  # top/bottom 10% of page height
HEADER_FOOTER_MIN_FREQUENCY = 0.03  # must repeat on >=3% of sampled pages
HEADER_FOOTER_MIN_OCCURRENCES = 3  # ...and at least this many times outright
FULL_WIDTH_RATIO = 0.60  # blocks wider than this fraction of page count as "full width"
COLUMN_GAP_RATIO = 0.08  # min horizontal gap (as fraction of page width) to split columns

TABLE_RENDER_ZOOM = 3  # 2x (144dpi) was legible but soft for dense small-text data tables
# find_tables() can miss the table's true edge outright — verified on a real book where it
# dropped an entire last column (no border style it recognized) rather than just clipping a
# few points. A fixed few-point pad doesn't fix that; padding proportional to the table's own
# size does (confirmed empirically: ~20% recovered a full missing column in that case).
TABLE_BBOX_PADDING_RATIO = 0.20
TABLE_MAX_IMAGE_SIDE = 2400  # tables need to stay legible even at the cost of a bigger file

# A diagram/flowchart (boxes + connector lines, native vector drawing) has no
# raster image to extract and isn't a table either — get_text() still returns
# each box's text label as its own small block, and our column/row reading
# order heuristic (built for paragraphs) scrambles them into nonsense. Render
# the whole region as one image instead, like a table. Three independent
# signals, all required, calibrated against a real book: a real diagram page
# had 13 non-table drawing shapes covering 9% of the page with 16 short text
# labels inside; ordinary pages (including ones already claimed by a table)
# had at most 1 leftover shape after excluding table gridlines.
FIGURE_MIN_DRAWING_COUNT = 4
FIGURE_MIN_AREA_RATIO = 0.05
FIGURE_MIN_TEXT_BLOCKS = 4
FIGURE_MAX_LABEL_WORDS = 12  # a diagram label is short; a real paragraph inside the region isn't
FIGURE_TABLE_OVERLAP_RATIO = 0.3  # drop drawings that are mostly a table's own gridlines

_DIGIT_RUN_RE = re.compile(r"\d+")


def _normalize_repeat_key(text: str) -> str:
    """Collapses digit runs to '#' so "Capitulo 3 - Pagina 45" and "Capitulo 3
    - Pagina 46" are recognized as the same repeating header/footer instead
    of two headers that each show up on only one page (below the frequency
    threshold) and slip through unfiltered."""
    return _DIGIT_RUN_RE.sub("#", text)


def detect_repeated_texts(doc: fitz.Document, sample_every: int = 2) -> set[str]:
    """Finds text patterns that repeat near the top/bottom margin across
    sampled pages. Returns normalized keys (see _normalize_repeat_key) —
    callers must normalize candidate text the same way before checking
    membership.

    The frequency bar is deliberately low (3% of sampled pages, min 3
    occurrences) rather than a high one like ">=60% of the whole book": a
    multi-part book's running head changes per Part/Chapter, so no single
    header text ever covers a majority of the *entire* book — a real running
    head for a 300-page Part in a 2500-page book might be under 15% of all
    sampled pages. Body text essentially never repeats verbatim at the exact
    same header/footer-zone position across multiple pages by coincidence,
    so a low bar here doesn't risk false positives the way it would for
    ordinary body paragraphs.

    ``sample_every=2`` (not 5): a real book showed a *chapter*-level running
    head (changes every ~15-20 pages, shorter-lived than a Part-level one)
    landing right at the MIN_OCCURRENCES boundary with sparser sampling —
    caught on some chapters and not others depending on where the sample
    points happened to fall. Denser sampling costs more time but is cheap
    relative to OCR/extraction, and reliability matters more here.
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
    threshold = max(HEADER_FOOTER_MIN_OCCURRENCES, int(sampled * HEADER_FOOTER_MIN_FREQUENCY))
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


def _detect_figure_bbox(page: fitz.Page, table_bboxes: list[fitz.Rect], text_blocks: list[dict]) -> fitz.Rect | None:
    """Finds a likely diagram/flowchart region: several vector drawing shapes
    (boxes, connector lines) clustered together, overlapping several short,
    disconnected text labels — as opposed to a normal paragraph (long,
    contiguous text) or an already-detected table (excluded via its own
    gridline drawings). Returns the union bbox to render as one image, or
    None if the page doesn't look like it has a diagram.
    """
    try:
        drawings = page.get_drawings()
    except Exception:
        return None
    if not drawings:
        return None

    rects: list[fitz.Rect] = []
    for d in drawings:
        raw_rect = d.get("rect")
        if not raw_rect:
            continue
        rect = fitz.Rect(raw_rect)
        if rect.get_area() <= 0:
            continue
        if any(_overlaps(tuple(rect), tb, min_overlap=FIGURE_TABLE_OVERLAP_RATIO) for tb in table_bboxes):
            continue  # a table's own cell borders, not a separate diagram
        rects.append(rect)

    if len(rects) < FIGURE_MIN_DRAWING_COUNT:
        return None

    union = rects[0]
    for r in rects[1:]:
        union |= r

    page_area = page.rect.width * page.rect.height
    if page_area <= 0 or union.get_area() / page_area < FIGURE_MIN_AREA_RATIO:
        return None

    label_count = 0
    for b in text_blocks:
        bbox = fitz.Rect(b["bbox"])
        if bbox.get_area() <= 0 or not _overlaps(tuple(bbox), union, min_overlap=0.5):
            continue
        text = "".join(span["text"] for line in b.get("lines", []) for span in line.get("spans", [])).strip()
        if text and len(text.split()) <= FIGURE_MAX_LABEL_WORDS:
            label_count += 1

    if label_count < FIGURE_MIN_TEXT_BLOCKS:
        return None

    return union


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

        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])
        text_blocks_raw = [b for b in blocks if b.get("type") == 0]
        image_blocks_raw = [b for b in blocks if b.get("type") == 1]

        table_bboxes: list[fitz.Rect] = []
        figure_bbox: fitz.Rect | None = None
        if page_index not in scanned_pages:
            # A scanned page's "table"/"figure" is just part of its one
            # full-page raster image — there's no vector structure to find,
            # and running these (expensive) heuristics against a page full of
            # small OCR word-boxes is pure cost for zero benefit.
            try:
                found_tables = page.find_tables()
                for table in found_tables.tables:
                    table_bboxes.append(fitz.Rect(table.bbox))
            except Exception:
                pass  # table detection is best-effort; never fail the whole page over it
            figure_bbox = _detect_figure_bbox(page, table_bboxes, text_blocks_raw)

        # Always render as image, never as extracted HTML text: tried an ML
        # layout model for real selectable table text, but on complex
        # multi-column data tables (real medical textbook content, not
        # synthetic tests) it silently scrambled cell order — worse than an
        # image, since a reader can't tell the numbers are wrong. Visual
        # fidelity beats "sometimes searchable, sometimes garbled".
        for table_bbox in table_bboxes:
            # find_tables() sometimes underestimates the table's true right/
            # bottom edge (no visible border on the last column/row) and
            # clips real content — pad the crop proportionally, then clamp
            # back to the page.
            pad_x = table_bbox.width * TABLE_BBOX_PADDING_RATIO
            pad_y = table_bbox.height * TABLE_BBOX_PADDING_RATIO
            padded_bbox = (
                fitz.Rect(
                    table_bbox.x0 - pad_x,
                    table_bbox.y0 - pad_y,
                    table_bbox.x1 + pad_x,
                    table_bbox.y1 + pad_y,
                )
                & page.rect
            )
            pix = page.get_pixmap(clip=padded_bbox, matrix=fitz.Matrix(TABLE_RENDER_ZOOM, TABLE_RENDER_ZOOM))
            data, mime = recompress(pix.tobytes("png"), max_side=TABLE_MAX_IMAGE_SIDE, jpeg_quality=jpeg_quality)
            h = content_hash(data)
            image_id = f"table_{page_index}_{h[:12]}"
            content.items.append(ImageBlock(data=data, mime=mime, image_id=image_id, caption=""))

        if figure_bbox is not None:
            # A diagram/flowchart: native vector drawing (boxes + connector
            # lines), no raster image to extract, and not a table either.
            # Render the whole detected region as one image, same as tables.
            pad_x = figure_bbox.width * TABLE_BBOX_PADDING_RATIO
            pad_y = figure_bbox.height * TABLE_BBOX_PADDING_RATIO
            padded_figure_bbox = (
                fitz.Rect(
                    figure_bbox.x0 - pad_x,
                    figure_bbox.y0 - pad_y,
                    figure_bbox.x1 + pad_x,
                    figure_bbox.y1 + pad_y,
                )
                & page.rect
            )
            pix = page.get_pixmap(clip=padded_figure_bbox, matrix=fitz.Matrix(TABLE_RENDER_ZOOM, TABLE_RENDER_ZOOM))
            data, mime = recompress(pix.tobytes("png"), max_side=TABLE_MAX_IMAGE_SIDE, jpeg_quality=jpeg_quality)
            h = content_hash(data)
            image_id = f"figure_{page_index}_{h[:12]}"
            content.items.append(ImageBlock(data=data, mime=mime, image_id=image_id, caption=""))

        text_blocks = [
            b
            for b in text_blocks_raw
            if not any(_overlaps(b["bbox"], tb) for tb in table_bboxes)
            and not (figure_bbox is not None and _overlaps(b["bbox"], figure_bbox))
        ]
        if figure_bbox is not None:
            # Any raster sub-image inside the diagram (an icon, say) is
            # already part of the whole-figure render — don't extract it a
            # second time as its own separate image.
            image_blocks_raw = [b for b in image_blocks_raw if not _overlaps(b["bbox"], figure_bbox)]

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
