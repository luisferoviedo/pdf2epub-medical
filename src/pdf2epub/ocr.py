"""Per-page digital/scanned classification and the OCR pre-pass.

Medical textbooks are frequently a mix: a digitally-typeset chapter next to
a scanned insert (an old plate, a photocopied appendix). Running OCR on the
whole book would be slow and would mangle the digital pages, so we classify
first and let ocrmypdf's ``--skip-text`` only touch pages that need it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import fitz  # PyMuPDF

MIN_CHARS_FOR_DIGITAL = 20  # pages with less extractable text than this are treated as scanned


def classify_pages(doc: fitz.Document) -> dict[int, str]:
    """Returns {page_index: "digital" | "scanned"}."""
    classification: dict[int, str] = {}
    for page_index in range(doc.page_count):
        text = doc[page_index].get_text("text").strip()
        classification[page_index] = "digital" if len(text) >= MIN_CHARS_FOR_DIGITAL else "scanned"
    return classification


def needs_ocr(classification: dict[int, str]) -> bool:
    return any(status == "scanned" for status in classification.values())


def scanned_ratio(classification: dict[int, str]) -> float:
    if not classification:
        return 0.0
    scanned = sum(1 for status in classification.values() if status == "scanned")
    return scanned / len(classification)


def run_ocr(input_path: Path, output_path: Path, lang: str = "spa+eng+por") -> None:
    """Runs ocrmypdf, adding a text layer only to pages that don't already have one.

    Raises subprocess.CalledProcessError on failure (e.g. unsupported language pack).
    """
    subprocess.run(
        [
            "ocrmypdf",
            "--skip-text",
            "-l",
            lang,
            "--output-type",
            "pdf",
            str(input_path),
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
