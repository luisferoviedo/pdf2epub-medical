import zipfile

import fitz

from pdf2epub.pipeline import ConvertOptions, _should_parallelize_extraction, convert


def test_should_parallelize_when_mostly_digital():
    assert _should_parallelize_extraction(page_count=100, scanned_pages=set(), n_chapters=4) is True


def test_should_not_parallelize_when_heavily_scanned():
    scanned = set(range(50))  # 50% scanned, well above the 10% threshold
    assert _should_parallelize_extraction(page_count=100, scanned_pages=scanned, n_chapters=4) is False


def test_should_not_parallelize_with_too_few_chapters():
    assert _should_parallelize_extraction(page_count=100, scanned_pages=set(), n_chapters=1) is False


def test_should_not_parallelize_empty_document():
    assert _should_parallelize_extraction(page_count=0, scanned_pages=set(), n_chapters=0) is False


def test_parallel_extraction_preserves_chapter_order(tmp_path):
    """A mostly-digital book with several chapters triggers the parallel
    extraction path. ProcessPoolExecutor + as_completed() finishes chapters
    out of order — the pipeline must still reassemble them in original page
    order, or a real book would come out with scrambled chapters."""
    pdf_path = tmp_path / "book.pdf"
    doc = fitz.open()
    n_chapters = 4
    pages_per_chapter = 3
    for c in range(n_chapters):
        for p in range(pages_per_chapter):
            page = doc.new_page(width=400, height=533)
            page.insert_text((50, 50), f"CHAPTER-{c}-PAGE-{p}", fontsize=14)
    doc.save(pdf_path)
    doc.close()

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count
    doc.close()
    assert total_pages == n_chapters * pages_per_chapter

    output_path = tmp_path / "book.epub"
    options = ConvertOptions(no_ocr=True, split_every=pages_per_chapter)
    convert(pdf_path, output_path, options=options)

    with zipfile.ZipFile(output_path) as zf:
        xhtml_files = sorted(n for n in zf.namelist() if "chap_" in n)
        combined = "".join(zf.read(n).decode("utf-8", errors="replace") for n in xhtml_files)

    markers = [f"CHAPTER-{c}-PAGE-{p}" for c in range(n_chapters) for p in range(pages_per_chapter)]
    positions = [combined.index(m) for m in markers]
    assert positions == sorted(positions), f"chapter order scrambled: {positions}"
