"""Mod B benchmark: measures peak RSS memory of the current (control-only,
no streaming) pipeline on a representative illustrated book, at two sizes,
to extrapolate what a full 2500-page book would need — and decide, with
numbers, whether rewriting EPUB assembly to stream is justified.

Usage: uv run python scripts/benchmark_memory.py
Writes scripts/decision.log with the verdict.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).parent.parent
WORK_DIR = REPO_ROOT / "scripts" / "_bench_tmp"

# A book with a real image on ~70% of pages (representative of a "muy
# ilustrado" medical textbook), sized like a real scan/diagram before our
# own recompression — not a trivial thumbnail.
IMAGE_EVERY_N_PAGES = 10  # skip 3 of every 10 pages (no image)
IMAGE_SIZE = (1400, 1800)

# Full target size from the project's stated use case.
TARGET_PAGE_COUNT = 2500

# If the peak RSS extrapolated to TARGET_PAGE_COUNT pages exceeds this, the
# in-memory chapter accumulation is a real risk on an 8GB M1 Air (leaving
# room for the OS + other apps) and streaming EPUB assembly is justified.
ACCEPT_THRESHOLD_MB = 1500


def build_test_pdf(path: Path, n_pages: int) -> None:
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=420, height=595)  # A5-ish
        page.insert_text((40, 40), f"Pagina {i}", fontsize=11)
        page.insert_textbox(
            fitz.Rect(40, 70, 380, 400),
            "Contenido clinico de ejemplo con texto suficiente para simular densidad real. " * 12,
            fontsize=9,
        )
        if i % 10 < 7:  # ~70% of pages carry an image
            img = Image.new("RGB", IMAGE_SIZE, (30 + i % 200, 60, 120))
            draw = ImageDraw.Draw(img)
            draw.text((50, 50), f"Figura pagina {i}", fill="white")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            page.insert_image(fitz.Rect(40, 420, 380, 560), stream=buf.getvalue())
    doc.save(path)
    doc.close()


def run_worker(input_path: Path, output_path: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "_memory_worker.py"), str(input_path), str(output_path)],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    sizes = [150, 300]
    measurements = []

    for n in sizes:
        pdf_path = WORK_DIR / f"bench_{n}.pdf"
        epub_path = WORK_DIR / f"bench_{n}.epub"
        print(f"Building {n}-page test book...")
        build_test_pdf(pdf_path, n)
        print(f"Converting ({n} pages)...")
        metrics = run_worker(pdf_path, epub_path)
        metrics["pages"] = n
        measurements.append(metrics)
        print(f"  {n} pages: {metrics['elapsed_s']:.1f}s, peak RSS {metrics['peak_rss_mb']:.0f}MB")

    # Linear extrapolation: fit peak_rss_mb = a * pages + b from the two
    # measured points, then project to TARGET_PAGE_COUNT.
    (p1, m1), (p2, m2) = [(m["pages"], m["peak_rss_mb"]) for m in measurements]
    slope = (m2 - m1) / (p2 - p1)
    intercept = m1 - slope * p1
    projected_mb = slope * TARGET_PAGE_COUNT + intercept

    decision = "ACEPTAR" if projected_mb > ACCEPT_THRESHOLD_MB else "RECHAZAR"

    log_lines = [
        "=== Mod B: benchmark de memoria pico (EPUB en memoria vs streaming) ===",
        "",
        "Mediciones (grupo de control, arquitectura actual sin cambios):",
    ]
    for m in measurements:
        log_lines.append(f"  {m['pages']:>5} paginas: {m['elapsed_s']:6.1f}s, pico RSS {m['peak_rss_mb']:7.1f} MB")
    log_lines += [
        "",
        f"Pendiente estimada: {slope:.3f} MB/pagina",
        f"Proyeccion a {TARGET_PAGE_COUNT} paginas (tamano objetivo del proyecto): {projected_mb:.0f} MB",
        f"Umbral de aceptacion (streaming se justifica si se supera): {ACCEPT_THRESHOLD_MB} MB",
        "",
        f"DECISION: {decision}",
    ]
    if decision == "RECHAZAR":
        log_lines.append(
            "Motivo: la proyeccion queda comodamente por debajo del umbral en un M1 Air de 8GB "
            "(deja margen de sobra para el SO y otras apps). Reescribir el ensamblado del EPUB a "
            "streaming resolveria un problema que los datos no muestran que exista. No se implementa."
        )
    else:
        log_lines.append(
            "Motivo: la proyeccion supera el umbral seguro para un M1 Air de 8GB. Proceder a "
            "prototipar el ensamblado en streaming y re-benchmarkear como tratamiento (B) contra este control (A)."
        )

    log_text = "\n".join(log_lines)
    print("\n" + log_text)
    (REPO_ROOT / "scripts" / "decision.log").write_text(log_text + "\n")


if __name__ == "__main__":
    main()
