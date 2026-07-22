"""Orchestrates the full PDF -> EPUB conversion, chapter by chapter.

Extraction is streamed one chapter at a time (never the whole PDF's text at
once) to keep memory bounded on a 2500-page book on an 8GB M1 Air. The OCR
pre-pass, when needed, runs once up front since ocrmypdf operates on the
whole file.

Extraction itself picks between two execution strategies based on a cheap
upfront cost estimate — a small planner, in the spirit of how a database
picks a query plan from estimated cost rather than always using one fixed
strategy: benchmarked at ~2x with a process pool, but only worth the
process-pool overhead (and its coarser progress/cancellation granularity)
when extraction is actually a meaningful share of total time. On a heavily
scanned book, OCR dominates by minutes-to-hours and a 25s extraction saving
is noise — so sequential (simpler, per-chapter cancellable) is kept there.
"""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from pdf2epub import extract, ocr, outline
from pdf2epub.epub import build_epub
from pdf2epub.errors import ConversionCancelled
from pdf2epub.images import recompress
from pdf2epub.models import Chapter, ChapterContent

ProgressCallback = Callable[[str, int, int], None]

# Below this fraction of scanned pages, OCR won't dominate total wall-clock
# time, so parallel extraction's ~2x is worth the process-pool overhead.
PARALLEL_SCANNED_RATIO_THRESHOLD = 0.10
MIN_CHAPTERS_FOR_PARALLEL = 2


@dataclass
class ConvertOptions:
    lang: str = "spa+eng+por"
    no_ocr: bool = False
    max_image_size: int = 1600
    jpeg_quality: int = 85
    split_every: int = 50
    cover_path: Path | None = None
    title: str | None = None
    author: str | None = None


def _noop_progress(stage: str, current: int, total: int) -> None:
    pass


def _should_parallelize_extraction(page_count: int, scanned_pages: set[int], n_chapters: int) -> bool:
    if page_count == 0 or n_chapters < MIN_CHAPTERS_FOR_PARALLEL:
        return False
    return (len(scanned_pages) / page_count) < PARALLEL_SCANNED_RATIO_THRESHOLD


def _extract_chapter_worker(
    args: tuple[str, Chapter, set[str], set[int], int, int],
) -> ChapterContent:
    doc_path, chapter, repeated_texts, scanned_pages, max_image_size, jpeg_quality = args
    doc = fitz.open(doc_path)
    try:
        # Each worker process dedupes repeated images only within its own
        # chapter — cross-chapter logo/watermark dedup needs a shared
        # seen-hash set, which separate processes don't share. An occasional
        # repeated logo across a chapter boundary is an acceptable trade for
        # real wall-clock parallelism.
        return extract.extract_chapter_content(
            doc,
            chapter,
            repeated_texts=repeated_texts,
            seen_image_hashes=set(),
            max_image_size=max_image_size,
            jpeg_quality=jpeg_quality,
            scanned_pages=scanned_pages,
        )
    finally:
        doc.close()


def _extract_sequential(
    doc: fitz.Document,
    chapters: list[Chapter],
    repeated_texts: set[str],
    scanned_pages: set[int],
    options: ConvertOptions,
    on_progress: ProgressCallback,
    check_cancelled: Callable[[], None],
) -> list[ChapterContent]:
    total_pages = doc.page_count
    seen_image_hashes: set[str] = set()
    chapter_contents: list[ChapterContent] = []
    for chapter in chapters:
        check_cancelled()
        content = extract.extract_chapter_content(
            doc,
            chapter,
            repeated_texts=repeated_texts,
            seen_image_hashes=seen_image_hashes,
            max_image_size=options.max_image_size,
            jpeg_quality=options.jpeg_quality,
            scanned_pages=scanned_pages,
        )
        chapter_contents.append(content)
        on_progress("extract", chapter.end_page, total_pages)
    return chapter_contents


def _extract_parallel(
    doc_path: Path,
    total_pages: int,
    chapters: list[Chapter],
    repeated_texts: set[str],
    scanned_pages: set[int],
    options: ConvertOptions,
    on_progress: ProgressCallback,
    check_cancelled: Callable[[], None],
) -> list[ChapterContent]:
    check_cancelled()  # last clean checkpoint: once submitted, workers run to completion
    args = [
        (str(doc_path), chapter, repeated_texts, scanned_pages, options.max_image_size, options.jpeg_quality)
        for chapter in chapters
    ]
    results: dict[int, ChapterContent] = {}
    pages_done = 0
    with ProcessPoolExecutor() as pool:
        futures = {pool.submit(_extract_chapter_worker, a): i for i, a in enumerate(args)}
        for future in as_completed(futures):
            i = futures[future]
            content = future.result()
            results[i] = content
            pages_done += chapters[i].end_page - chapters[i].start_page
            on_progress("extract_parallel", pages_done, total_pages)
    return [results[i] for i in range(len(chapters))]


def convert(
    input_path: Path,
    output_path: Path,
    options: ConvertOptions | None = None,
    on_progress: ProgressCallback = _noop_progress,
    cancel_event: threading.Event | None = None,
) -> None:
    options = options or ConvertOptions()

    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise ConversionCancelled

    with tempfile.TemporaryDirectory(prefix="pdf2epub_") as tmp_dir:
        doc = fitz.open(input_path)
        current_path = input_path
        try:
            classification = ocr.classify_pages(doc, on_progress=on_progress, cancel_event=cancel_event)
            scanned_pages = {i for i, status in classification.items() if status == "scanned"}

            if not options.no_ocr and ocr.needs_ocr(classification):
                # Benchmarked splitting the PDF to OCR only the scanned pages
                # against OCR-ing the whole file: no meaningful difference
                # (ocrmypdf's own --skip-text already skips digital pages
                # cheaply), so the whole-file path is kept — it's simpler and
                # has no page-reordering risk.
                ocr_output = Path(tmp_dir) / "ocr.pdf"
                doc.close()
                doc = None  # if run_ocr raises below, `finally` must not double-close
                ocr.run_ocr(
                    input_path,
                    ocr_output,
                    lang=options.lang,
                    on_progress=on_progress,
                    cancel_event=cancel_event,
                )
                doc = fitz.open(ocr_output)
                current_path = ocr_output
                on_progress("ocr", 1, 1)

            chapters = outline.detect_chapters(doc, fallback_every=options.split_every)
            total_pages = doc.page_count

            repeated_texts = extract.detect_repeated_texts(doc)

            check_cancelled()
            if _should_parallelize_extraction(total_pages, scanned_pages, len(chapters)):
                chapter_contents = _extract_parallel(
                    current_path,
                    total_pages,
                    chapters,
                    repeated_texts,
                    scanned_pages,
                    options,
                    on_progress,
                    check_cancelled,
                )
            else:
                chapter_contents = _extract_sequential(
                    doc, chapters, repeated_texts, scanned_pages, options, on_progress, check_cancelled
                )

            check_cancelled()
            cover_bytes = _load_cover(doc, options)

            meta = doc.metadata or {}
            title = options.title or meta.get("title") or input_path.stem
            author = options.author or meta.get("author") or ""

            on_progress("build_epub", 0, 1)
            build_epub(
                output_path=output_path,
                title=title,
                author=author,
                lang=options.lang.split("+")[0],
                chapters=chapter_contents,
                cover_bytes=cover_bytes,
            )
            on_progress("build_epub", 1, 1)
        finally:
            if doc is not None:
                doc.close()


def _load_cover(doc: fitz.Document, options: ConvertOptions) -> bytes | None:
    if options.cover_path:
        return options.cover_path.read_bytes()
    if doc.page_count == 0:
        return None
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
    data, _mime = recompress(pix.tobytes("png"), max_side=1600, jpeg_quality=options.jpeg_quality)
    return data
