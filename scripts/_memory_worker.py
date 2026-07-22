"""Runs one convert() call in an isolated process and reports its own peak
RSS on stdout as JSON. Isolated so the measurement reflects only this
conversion's memory, not the driver script's own baseline usage.
"""

from __future__ import annotations

import json
import resource
import sys
import time
from pathlib import Path

from pdf2epub.pipeline import ConvertOptions, convert


def main() -> None:
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    t0 = time.perf_counter()
    convert(input_path, output_path, options=ConvertOptions(no_ocr=True))
    elapsed = time.perf_counter() - t0

    # ru_maxrss is bytes on macOS, KB on Linux.
    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak_kb / (1024 * 1024) if sys.platform == "darwin" else peak_kb / 1024

    print(json.dumps({"elapsed_s": elapsed, "peak_rss_mb": peak_mb}))


if __name__ == "__main__":
    main()
