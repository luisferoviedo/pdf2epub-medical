# pdf2epub-medical

Convertidor de PDF a EPUB para libros grandes e ilustrados (manuales de
medicina, 2500+ páginas, mezcla de páginas digitales y escaneadas). Uso
personal, publicado por si le sirve a alguien más.

Calibre (`ebook-convert`) hace un trabajo razonable en PDFs simples, pero
falla en libros con columnas múltiples y muchas ilustraciones: el texto
sale desordenado y las imágenes se pierden. `pdf2epub` construye el EPUB
con un pipeline propio pensado para ese caso.

## Qué hace

- Detecta página por página si es texto digital o escaneada, y aplica OCR
  (`ocrmypdf` + `tesseract`) solo donde hace falta.
- Detecta capítulos por el outline del PDF; si no hay, por tamaño de fuente
  de los encabezados; si tampoco, corta cada N páginas.
- Ordena el texto en columnas (común en libros médicos con layout a 2
  columnas) en vez de mezclar líneas de columnas distintas.
- Detecta tablas (dosis, valores de laboratorio) y las inserta como imagen
  en vez de intentar convertirlas a texto plano, que las destroza.
- Recomprime imágenes (JPEG, tamaño máximo configurable) para que el EPUB
  final no supere los límites de Kindle/Apple Books.
- Elimina headers/footers repetidos en cada página.
- CLI (`pdf2epub convert`) y una GUI web local mínima (`pdf2epub serve`).

## Qué NO hace (fuera de alcance v1)

- Tablas como HTML seleccionable (se insertan como imagen).
- Editor de tabla de contenidos o vista previa antes de convertir.
- Cola de trabajos / historial en la GUI web.
- Exportar a MOBI/KFX directamente (usa Send-to-Kindle o Calibre sobre el
  EPUB resultante).

## Requisitos

- macOS (probado en Apple Silicon, M1) o Linux.
- Python ≥ 3.11 y [`uv`](https://docs.astral.sh/uv/).
- Tesseract con los idiomas que uses, y Ghostscript (los usa `ocrmypdf`
  para la conversión y el OCR):

  ```bash
  brew install tesseract tesseract-lang ghostscript
  ```

## Instalación

```bash
git clone https://github.com/luisferoviedo/pdf2epub-medical.git
cd pdf2epub-medical
uv sync
```

## Uso

### CLI

```bash
uv run pdf2epub convert libro.pdf -o libro.epub
```

Opciones:

| Flag | Default | Descripción |
|---|---|---|
| `-o, --output` | `<input>.epub` | Ruta del EPUB de salida |
| `--lang` | `spa+eng+por` | Idiomas OCR (códigos de tesseract, `+` para varios) |
| `--no-ocr` | `false` | No hacer OCR aunque haya páginas escaneadas |
| `--max-image-size` | `1600` | Lado máximo en px de las imágenes |
| `--jpeg-quality` | `85` | Calidad JPEG (1-100) |
| `--split-every` | `50` | Páginas por capítulo si no hay outline ni encabezados detectables |
| `--cover` | (renderiza pág. 1) | Imagen de portada |
| `--title` / `--author` | metadata del PDF | Override de metadata |

### GUI web local

```bash
uv run pdf2epub serve
```

Abre `http://127.0.0.1:8765`, arrastra el PDF, espera la conversión y
descarga el EPUB. Sin cola ni historial: un trabajo a la vez, pensado para
uso personal en tu propia máquina.

## Notas sobre Kindle

El EPUB resultante funciona directo en Apple Books y Kobo. Para Kindle,
Send-to-Kindle acepta EPUB hasta 650MB — por eso la recompresión de
imágenes viene activada por defecto. Si un libro de 2500+ páginas con
muchas ilustraciones sigue pesando demasiado, baja `--max-image-size` o
`--jpeg-quality`.

## Tests

```bash
uv run pytest
```

Si tienes `epubcheck` instalado (`brew install epubcheck`), los tests
también validan el EPUB generado contra el spec oficial.

## Licencia

MIT. Ver [LICENSE](LICENSE).

---

## English

PDF → EPUB converter for large illustrated books (medical textbooks,
2500+ pages, mixed digital/scanned pages). Built for personal use on a
Mac Air M1, published in case it's useful to someone else.

Calibre's `ebook-convert` handles simple PDFs reasonably, but falls apart
on multi-column, image-heavy books — text comes out scrambled and images
get dropped. `pdf2epub` is a purpose-built pipeline for that case: per-page
digital/scanned detection with selective OCR (`ocrmypdf` + `tesseract`),
chapter splitting via PDF outline / font-size heuristic / fixed page count,
column-aware reading order, tables rendered as images instead of mangled
text, image recompression for Kindle/Apple Books size limits, and repeated
header/footer stripping. Ships a CLI (`pdf2epub convert`) and a minimal
local web GUI (`pdf2epub serve`).

### Install

```bash
brew install tesseract tesseract-lang ghostscript
git clone https://github.com/luisferoviedo/pdf2epub-medical.git
cd pdf2epub-medical
uv sync
```

### Usage

```bash
uv run pdf2epub convert book.pdf -o book.epub --lang eng
uv run pdf2epub serve
```

Run `uv run pdf2epub convert --help` for the full flag list. See the
Spanish section above for the options table, Kindle size notes, and v1
scope — the code is the same either way.

MIT licensed.
