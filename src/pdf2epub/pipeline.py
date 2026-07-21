"""Orchestrates the full PDF -> EPUB conversion, chapter by chapter.

Extraction is streamed one chapter at a time (never the whole PDF's text at
once) to keep memory bounded on a 2500-page book on an 8GB M1 Air. The OCR
pre-pass, when needed, runs once up front since ocrmypdf operates on the
whole file.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from pdf2epub import extract, ocr, outline
from pdf2epub.epub import build_epub
from pdf2epub.images import recompress
from pdf2epub.models import ChapterContent

ProgressCallback = Callable[[str, int, int], None]


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


def convert(
    input_path: Path,
    output_path: Path,
    options: ConvertOptions | None = None,
    on_progress: ProgressCallback = _noop_progress,
) -> None:
    options = options or ConvertOptions()

    with tempfile.TemporaryDirectory(prefix="pdf2epub_") as tmp_dir:
        working_path = input_path

        doc = fitz.open(input_path)
        classification = ocr.classify_pages(doc)

        if not options.no_ocr and ocr.needs_ocr(classification):
            ratio = ocr.scanned_ratio(classification)
            on_progress("ocr", 0, 1)
            ocr_output = Path(tmp_dir) / "ocr.pdf"
            doc.close()
            ocr.run_ocr(input_path, ocr_output, lang=options.lang)
            working_path = ocr_output
            doc = fitz.open(working_path)
            on_progress("ocr", 1, 1)
            _ = ratio  # available for callers that want to show an ETA hint

        chapters = outline.detect_chapters(doc, fallback_every=options.split_every)
        total_pages = doc.page_count

        repeated_texts = extract.detect_repeated_texts(doc)
        seen_image_hashes: set[str] = set()

        chapter_contents: list[ChapterContent] = []
        for i, chapter in enumerate(chapters):
            content = extract.extract_chapter_content(
                doc,
                chapter,
                repeated_texts=repeated_texts,
                seen_image_hashes=seen_image_hashes,
                max_image_size=options.max_image_size,
                jpeg_quality=options.jpeg_quality,
            )
            chapter_contents.append(content)
            on_progress("extract", chapter.end_page, total_pages)
            _ = i

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

        doc.close()


def _load_cover(doc: fitz.Document, options: ConvertOptions) -> bytes | None:
    if options.cover_path:
        return options.cover_path.read_bytes()
    if doc.page_count == 0:
        return None
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
    data, _mime = recompress(pix.tobytes("png"), max_side=1600, jpeg_quality=options.jpeg_quality)
    return data
