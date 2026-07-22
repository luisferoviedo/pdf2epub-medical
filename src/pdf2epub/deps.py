"""Checks for external system binaries pdf2epub shells out to (OCR, PDF rendering)."""

from __future__ import annotations

import shutil

REQUIRED_BINARIES = {
    "tesseract": "brew install tesseract tesseract-lang",
    "gs": "brew install ghostscript",
}


def missing_binaries() -> dict[str, str]:
    return {name: install_hint for name, install_hint in REQUIRED_BINARIES.items() if shutil.which(name) is None}


def check_or_exit(console) -> None:
    missing = missing_binaries()
    if not missing:
        return
    console.print("[bold red]Faltan dependencias del sistema:[/bold red]")
    for name, install_hint in missing.items():
        console.print(f"  - [yellow]{name}[/yellow]: instala con [cyan]{install_hint}[/cyan]")
    raise SystemExit(1)
