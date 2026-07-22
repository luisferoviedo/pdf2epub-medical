"""Per-page digital/scanned classification and the OCR pre-pass.

Medical textbooks are frequently a mix: a digitally-typeset chapter next to
a scanned insert (an old plate, a photocopied appendix). Running OCR on the
whole book would be slow and would mangle the digital pages, so we classify
first and let ocrmypdf's ``--skip-text`` only touch pages that need it.
"""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

import fitz  # PyMuPDF

from pdf2epub.errors import ConversionCancelled

MIN_CHARS_FOR_DIGITAL = 20  # pages with less extractable text than this are treated as scanned

ProgressCallback = Callable[[str, int, int], None]


def classify_pages(
    doc: fitz.Document,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[int, str]:
    """Returns {page_index: "digital" | "scanned"}.

    Reports progress per page: on a 2500-page book this loop alone can take
    long enough that a caller with no feedback in between looks frozen.
    """
    classification: dict[int, str] = {}
    for page_index in range(doc.page_count):
        if cancel_event is not None and cancel_event.is_set():
            raise ConversionCancelled
        text = doc[page_index].get_text("text").strip()
        classification[page_index] = "digital" if len(text) >= MIN_CHARS_FOR_DIGITAL else "scanned"
        if on_progress:
            on_progress("classify", page_index + 1, doc.page_count)
    return classification


def needs_ocr(classification: dict[int, str]) -> bool:
    return any(status == "scanned" for status in classification.values())


def scanned_ratio(classification: dict[int, str]) -> float:
    if not classification:
        return 0.0
    scanned = sum(1 for status in classification.values() if status == "scanned")
    return scanned / len(classification)


def run_ocr(
    input_path: Path,
    output_path: Path,
    lang: str = "spa+eng+por",
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Runs ocrmypdf, adding a text layer only to pages that don't already have one.

    ocrmypdf doesn't expose per-page progress through a simple API, so while it
    runs we report elapsed seconds instead (stage="ocr", total=0 means
    indeterminate) — enough for a caller to show "still working" rather than
    going silent for the minutes/hours a large scanned book can take.

    stdout/stderr are redirected to a log file, never to a pipe we don't drain:
    ocrmypdf's own progress bar + logging can write more than the OS pipe
    buffer (64KB) over a long run, and a caller that only polls ``proc.poll()``
    without reading the pipe will deadlock the child process permanently —
    it blocks on the write() syscall and never makes progress again.

    ``--optimize 0`` skips ocrmypdf's own image recompression pass: we
    recompress images ourselves later when building the EPUB, so doing it
    twice would just burn CPU for no benefit.

    ``--tesseract-timeout`` and ``--skip-big`` are safety valves, not quality
    trade-offs on normal pages: one pathological page (huge scan resolution,
    corrupted image) can otherwise stall tesseract indefinitely, silently
    hanging the whole multi-hour job. With these set, that one page is
    skipped — copied through un-OCR'd — instead of blocking the entire book.

    Raises subprocess.CalledProcessError on failure (e.g. unsupported language
    pack) with the captured log as ``.stderr``. Raises ConversionCancelled if
    ``cancel_event`` is set while running.
    """
    log_path = output_path.with_suffix(".ocr.log")
    with open(log_path, "w") as log_file:
        proc = subprocess.Popen(
            [
                "ocrmypdf",
                "--skip-text",
                "--optimize",
                "0",
                "--tesseract-timeout",
                "180",
                "--skip-big",
                "60",
                "-l",
                lang,
                "--output-type",
                "pdf",
                str(input_path),
                str(output_path),
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        start = time.monotonic()
        try:
            while proc.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    raise ConversionCancelled
                if on_progress:
                    on_progress("ocr", int(time.monotonic() - start), 0)
                time.sleep(1)
        except BaseException:
            # Covers ConversionCancelled and e.g. KeyboardInterrupt (Ctrl+C in
            # the CLI) — never leave ocrmypdf running as an orphaned process.
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            raise

    if proc.returncode != 0:
        log_text = log_path.read_text(errors="replace") if log_path.exists() else ""
        raise subprocess.CalledProcessError(proc.returncode, proc.args, output=log_text, stderr=log_text)
