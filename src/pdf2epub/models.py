"""Shared data structures passed between pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Chapter:
    title: str
    start_page: int  # 0-indexed, inclusive
    end_page: int  # 0-indexed, exclusive


@dataclass
class TextBlock:
    kind: str = "text"  # "text" | "heading"
    text: str = ""


@dataclass
class ImageBlock:
    kind: str = "image"
    data: bytes = b""
    mime: str = "image/jpeg"
    image_id: str = ""
    caption: str = ""


ContentItem = TextBlock | ImageBlock


@dataclass
class ChapterContent:
    chapter: Chapter
    items: list[ContentItem] = field(default_factory=list)
