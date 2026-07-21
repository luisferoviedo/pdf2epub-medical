"""Assembles extracted chapter content into a single EPUB3 file.

Each chapter becomes one or more XHTML documents (split above
``split_bytes`` so no single file overwhelms an e-reader's renderer on a
2500-page book), linked from both a nav TOC (EPUB3) and an NCX (for older
readers), with a minimal stylesheet tuned for reflow.
"""

from __future__ import annotations

import html as html_lib
import uuid
from pathlib import Path

from ebooklib import epub

from pdf2epub.models import ChapterContent, ImageBlock, TextBlock

DEFAULT_CSS = """
body { font-family: serif; line-height: 1.4; margin: 1em; }
h1, h2 { line-height: 1.2; margin-top: 1.5em; }
p { margin: 0 0 0.8em 0; text-align: justify; }
img { max-width: 100%; height: auto; display: block; margin: 1em auto; }
figcaption { font-size: 0.85em; text-align: center; color: #444; }
"""


def _item_to_fragment(item: TextBlock | ImageBlock) -> tuple[str, int]:
    if isinstance(item, TextBlock):
        text = html_lib.escape(item.text)
        tag = "h2" if item.kind == "heading" else "p"
        fragment = f"<{tag}>{text}</{tag}>\n"
    else:
        ext = "jpg" if item.mime == "image/jpeg" else "png"
        fragment = f'<img src="images/{item.image_id}.{ext}" alt=""/>\n'
    return fragment, len(fragment.encode("utf-8"))


def _split_fragments(items: list[TextBlock | ImageBlock], split_bytes: int) -> list[list[TextBlock | ImageBlock]]:
    parts: list[list[TextBlock | ImageBlock]] = []
    current: list[TextBlock | ImageBlock] = []
    current_size = 0
    for item in items:
        _, size = _item_to_fragment(item)
        if current and current_size + size > split_bytes:
            parts.append(current)
            current, current_size = [], 0
        current.append(item)
        current_size += size
    if current:
        parts.append(current)
    return parts or [[]]


def build_epub(
    output_path: Path,
    title: str,
    author: str,
    lang: str,
    chapters: list[ChapterContent],
    cover_bytes: bytes | None = None,
    split_bytes: int = 250_000,
) -> None:
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language(lang)
    if author:
        book.add_author(author)

    if cover_bytes:
        book.set_cover("cover.jpg", cover_bytes)

    style = epub.EpubItem(
        uid="style_main",
        file_name="style/main.css",
        media_type="text/css",
        content=DEFAULT_CSS,
    )
    book.add_item(style)

    added_image_ids: set[str] = set()
    spine: list = ["nav"]
    toc: list = []

    for chapter_index, chapter_content in enumerate(chapters):
        chapter = chapter_content.chapter
        parts = _split_fragments(chapter_content.items, split_bytes)
        part_htmls = []

        for part_index, part_items in enumerate(parts):
            body_html = []
            for item in part_items:
                fragment, _ = _item_to_fragment(item)
                body_html.append(fragment)
                if isinstance(item, ImageBlock) and item.image_id not in added_image_ids:
                    ext = "jpg" if item.mime == "image/jpeg" else "png"
                    img_item = epub.EpubItem(
                        uid=item.image_id,
                        file_name=f"images/{item.image_id}.{ext}",
                        media_type=item.mime,
                        content=item.data,
                    )
                    book.add_item(img_item)
                    added_image_ids.add(item.image_id)

            suffix = "" if len(parts) == 1 else f" ({part_index + 1}/{len(parts)})"
            part_title = f"{chapter.title}{suffix}"
            file_name = f"chap_{chapter_index:04d}_{part_index:02d}.xhtml"

            xhtml = epub.EpubHtml(title=part_title, file_name=file_name, lang=lang)
            xhtml.content = (
                f"<h1>{html_lib.escape(part_title)}</h1>\n" + "".join(body_html)
                if part_index == 0
                else "".join(body_html)
            )
            xhtml.add_item(style)
            book.add_item(xhtml)
            spine.append(xhtml)
            part_htmls.append(xhtml)

        if part_htmls:
            toc.append(epub.Link(part_htmls[0].file_name, chapter.title, f"chap_{chapter_index:04d}"))

    book.toc = tuple(toc)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    output_path.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output_path), book)
