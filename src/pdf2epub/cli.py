from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from pdf2epub import deps
from pdf2epub.pipeline import ConvertOptions, convert

app = typer.Typer(add_completion=False, help="Convertidor de PDF a EPUB para libros grandes e ilustrados.")
console = Console()

STAGE_LABELS = {
    "ocr": "OCR (páginas escaneadas)",
    "extract": "Extrayendo contenido",
    "build_epub": "Ensamblando EPUB",
}


@app.command("convert")
def convert_cmd(
    input_pdf: Annotated[Path, typer.Argument(help="Ruta al PDF de entrada")],
    output: Annotated[Path, typer.Option("-o", "--output", help="Ruta del EPUB de salida")] = None,
    lang: Annotated[str, typer.Option("--lang", help="Idiomas OCR (código tesseract)")] = "spa+eng+por",
    no_ocr: Annotated[bool, typer.Option("--no-ocr", help="Desactivar OCR aunque haya páginas escaneadas")] = False,
    max_image_size: Annotated[int, typer.Option("--max-image-size", help="Lado máximo en px de las imágenes")] = 1600,
    jpeg_quality: Annotated[int, typer.Option("--jpeg-quality", help="Calidad JPEG (1-100)")] = 85,
    split_every: Annotated[int, typer.Option("--split-every", help="Páginas por capítulo si no hay outline/heurística")] = 50,
    cover: Annotated[Path, typer.Option("--cover", help="Imagen de portada; por defecto renderiza la página 1")] = None,
    title: Annotated[str, typer.Option("--title", help="Título; por defecto metadata del PDF")] = None,
    author: Annotated[str, typer.Option("--author", help="Autor; por defecto metadata del PDF")] = None,
) -> None:
    """Convierte un PDF a EPUB."""
    deps.check_or_exit(console)

    if not input_pdf.exists():
        console.print(f"[bold red]No existe el archivo:[/bold red] {input_pdf}")
        raise typer.Exit(1)

    output_path = output or input_pdf.with_suffix(".epub")
    options = ConvertOptions(
        lang=lang,
        no_ocr=no_ocr,
        max_image_size=max_image_size,
        jpeg_quality=jpeg_quality,
        split_every=split_every,
        cover_path=cover,
        title=title,
        author=author,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Iniciando...", total=None)

        def on_progress(stage: str, current: int, total: int) -> None:
            label = STAGE_LABELS.get(stage, stage)
            progress.update(task_id, description=label, completed=current, total=total or None)

        convert(input_pdf, output_path, options=options, on_progress=on_progress)

    console.print(f"[bold green]Listo:[/bold green] {output_path}")


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Host de la GUI web local")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Puerto de la GUI web local")] = 8765,
) -> None:
    """Levanta la GUI web local (uso: arrastrar PDF, convertir, descargar)."""
    deps.check_or_exit(console)
    import uvicorn

    console.print(f"[bold green]GUI en:[/bold green] http://{host}:{port}")
    uvicorn.run("pdf2epub.web.app:app", host=host, port=port, log_level="warning")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
