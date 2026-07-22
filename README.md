# pdf2epub-medical

[![CI](https://github.com/luisferoviedo/pdf2epub-medical/actions/workflows/ci.yml/badge.svg)](https://github.com/luisferoviedo/pdf2epub-medical/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**[Español](#español)** · **[English](#english)** · **[Português](#português)**

Convertidor de PDF a EPUB para libros grandes e ilustrados, con un pipeline
propio pensado para el caso que rompe a Calibre: manuales de medicina de
2500+ páginas, mezcla de texto digital y páginas escaneadas, columnas
múltiples, tablas de dosis. / PDF to EPUB converter built for the case that
breaks Calibre. / Conversor de PDF para EPUB feito para o caso que quebra o
Calibre.

---

## Español

Convertidor de PDF a EPUB para libros grandes e ilustrados (manuales de
medicina, 2500+ páginas, mezcla de páginas digitales y escaneadas). Uso
personal, publicado por si le sirve a alguien más.

Calibre (`ebook-convert`) hace un trabajo razonable en PDFs simples, pero
falla en libros con columnas múltiples y muchas ilustraciones: el texto
sale desordenado y las imágenes se pierden.

### Cómo funciona

El pipeline (`pipeline.py`) corre en etapas, cada una resuelta con un
heurístico simple y barato antes de considerar algo más caro:

1. **Clasificación por página** (`ocr.py`) — cada página se marca como
   "digital" o "escaneada" según cuánto texto extraíble tiene
   (`get_text()` < 20 caracteres → escaneada). Esto decide si hace falta
   OCR en absoluto, y cuáles páginas necesitan tabla/columna análisis.
2. **OCR selectivo** — si hay páginas escaneadas, se corre `ocrmypdf
   --skip-text` (solo toca las páginas sin capa de texto) con
   `--tesseract-timeout` y `--skip-big` como válvulas de seguridad: una
   página patológica (resolución gigante, imagen corrupta) no puede colgar
   un libro de 2000+ páginas indefinidamente.
3. **Detección de capítulos** (`outline.py`), tres estrategias en cascada:
   - Outline/bookmarks del PDF, si existen.
   - Si no: heurístico de tamaño de fuente — un span de texto con tamaño
     ≥1.2× el tamaño dominante del cuerpo se trata como encabezado. Tiene
     un **guard de plausibilidad**: si esto produce casi un "capítulo" por
     página (un encabezado de página o numeración ligeramente más grande
     que el cuerpo, común en libros reales), se descarta y cae al
     fallback siguiente — verificado con un libro real que producía 200
     "capítulos" para 200 páginas antes de este guard.
   - Si tampoco: corte fijo cada N páginas.
   - En cualquier caso, si el primer capítulo detectado no arranca en la
     página 0 (portada, prólogo, índice antes del primer bookmark — el
     caso común), se antepone un capítulo sintético para no perder ese
     contenido en silencio.
4. **Orden de lectura por columnas** (`extract.py`) — en vez de asumir
   una sola columna, los bloques de texto se agrupan por posición
   horizontal (clustering de `x0` con un umbral de espacio entre
   columnas) y se ordenan columna por columna, de arriba a abajo. Los
   bloques de ancho completo (títulos, pies de figura) anclan un nuevo
   punto de lectura en vez de mezclarse con las columnas.
5. **Encabezados/pies repetidos** — se muestrea el 10% superior/inferior
   de cada página en una muestra de páginas, se normalizan los números
   (dígitos → `#`) para que "Página 45" y "Página 46" cuenten como el
   mismo patrón, y cualquier texto que repita en ≥3% de la muestra (mín.
   3 veces) se excluye del contenido. El umbral es deliberadamente bajo:
   en un libro de varias Partes, el encabezado cambia por sección y nunca
   cubre la mayoría del libro completo — un umbral alto (como el 60%
   inicial de este proyecto) nunca los detecta.
6. **Tablas** — se detectan con `find_tables()` de PyMuPDF y se insertan
   siempre como imagen recomprimida, nunca como texto extraído. Se probó
   extracción real vía un modelo de layout ML, pero en tablas complejas de
   datos reales mezclaba el orden de las celdas — peor que una imagen,
   porque el lector no puede notar que los números están mal.
7. **Imágenes** — se recomprimen (JPEG, tamaño máximo configurable) y se
   deduplican por hash de contenido dentro de cada capítulo, para no
   repetir logos/marcas de agua en cada página.
8. **Planificador de extracción** — antes de extraer, un chequeo barato
   decide la estrategia: si el libro es mayormente digital (poca
   proporción de páginas escaneadas) y tiene varios capítulos, la
   extracción corre en paralelo con `ProcessPoolExecutor` (~2x medido);
   si el OCR ya va a dominar el tiempo total, se queda secuencial —
   más simple y con cancelación más fina. Es la misma idea que un motor
   de bases de datos eligiendo un plan de ejecución por costo estimado,
   no una estrategia fija.
9. **Ensamblado del EPUB** (`epub.py`) — capítulos como XHTML (partidos si
   superan ~250KB para no reventar el renderizador del lector), TOC nav +
   NCX, tipografía Literata embebida (diseñada para lectura en pantalla,
   en vez de depender de cuál "serif" tenga cada lector por defecto).

### Qué hace

- Detecta página por página si es texto digital o escaneada, y aplica OCR
  solo donde hace falta.
- Detecta capítulos por outline → heurístico de fuente (con guard de
  plausibilidad) → corte fijo, sin perder páginas de portada/prólogo.
- Ordena el texto en columnas en vez de mezclar líneas de columnas
  distintas.
- Detecta tablas y las inserta como imagen para preservar fidelidad
  visual.
- Recomprime y deduplica imágenes.
- Elimina headers/footers repetidos, incluso en libros de varias Partes
  con encabezados distintos por sección.
- Paraleliza la extracción cuando el costo estimado lo justifica.
- CLI (`pdf2epub convert`) y una GUI web local mínima (`pdf2epub serve`)
  con progreso en vivo, cancelación y guard de un solo trabajo a la vez.

### Qué NO hace (fuera de alcance v1)

- Tablas como HTML seleccionable (se insertan como imagen, a propósito:
  ver "Cómo funciona").
- Editor de tabla de contenidos o vista previa antes de convertir.
- Cola de trabajos / historial en la GUI web.
- Exportar a MOBI/KFX directamente (usa Send-to-Kindle o Calibre sobre el
  EPUB resultante).

### Piezas reutilizables para otros proyectos

Ninguna de estas depende de que el documento sea un libro médico —
podrían sacarse tal cual para otro tipo de proyecto:

| Pieza | Dónde | Útil para |
|---|---|---|
| Cascada de detección de secciones con fallback (outline → heurístico → fijo) + guard de plausibilidad | `outline.py` | Cualquier problema de "dividir un documento grande en secciones": reportes largos, actas, tesis. |
| Heurístico de orden de lectura por columnas (clustering de `x0`) | `extract.py::_order_blocks` | Extracción de texto de cualquier PDF/documento con layout multi-columna, no solo médico. |
| Detección de encabezados/pies repetidos con normalización de dígitos y umbral bajo consciente de secciones | `extract.py::detect_repeated_texts` | Cualquier documento largo con encabezados/pies de página corridos: informes, papers académicos, contratos. |
| Planificador de estrategia por costo estimado (paralelo vs. secuencial) | `pipeline.py::_should_parallelize_extraction` | Patrón general: medir una señal barata antes de decidir cómo ejecutar trabajo de costo variable. |
| Wrapper de subproceso a prueba de deadlock (log a archivo, nunca `PIPE` sin drenar) + cancelación cooperativa | `ocr.py::run_ocr` | Cualquier wrapper de Python sobre un subproceso de larga duración (ffmpeg, pandoc, herramientas CLI de otros). |
| Recompresión + deduplicación de imágenes por hash | `images.py` | Cualquier pipeline que procese muchas imágenes repetidas: scraping, procesamiento de documentos. |
| Patrón de job en background con polling para una GUI web local de un solo usuario (dict en memoria, thread, guard de concurrencia, cancelación) | `web/app.py` | Herramientas locales de un solo usuario con trabajos largos, sin necesitar Celery/Redis/colas reales. |
| Metodología de decisión por benchmark (medir antes de reescribir, `decision.log` con umbral de aceptación explícito) | `scripts/benchmark_memory.py` | Más una práctica que código: evita optimizaciones especulativas sin evidencia. |

### Requisitos

- macOS (probado en Apple Silicon, M1) o Linux.
- Python ≥ 3.11 y [`uv`](https://docs.astral.sh/uv/).
- Tesseract con los idiomas que uses, y Ghostscript (los usa `ocrmypdf`
  para la conversión y el OCR):

  ```bash
  brew install tesseract tesseract-lang ghostscript
  ```

### Instalación

```bash
git clone https://github.com/luisferoviedo/pdf2epub-medical.git
cd pdf2epub-medical
uv sync
```

### Uso

#### CLI

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

#### GUI web local

```bash
uv run pdf2epub serve
```

Abre `http://127.0.0.1:8765`, arrastra el PDF, espera la conversión y
descarga el EPUB. Sin cola ni historial: un trabajo a la vez, con log en
vivo y botón de cancelar, pensado para uso personal en tu propia máquina.

### Notas sobre Kindle

El EPUB resultante funciona directo en Apple Books y Kobo. Para Kindle,
Send-to-Kindle acepta EPUB hasta 650MB — por eso la recompresión de
imágenes viene activada por defecto. Si un libro de 2500+ páginas con
muchas ilustraciones sigue pesando demasiado, baja `--max-image-size` o
`--jpeg-quality`.

### Tests

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```

Si tienes `epubcheck` instalado (`brew install epubcheck`), los tests
también validan el EPUB generado contra el spec oficial. Los cuatro
comandos corren en CI (GitHub Actions) en cada push/PR.

### Licencia

MIT. Ver [LICENSE](LICENSE). La tipografía embebida (Literata) usa la SIL
Open Font License — ver [`src/pdf2epub/assets/fonts/OFL.txt`](src/pdf2epub/assets/fonts/OFL.txt).

---

## English

PDF → EPUB converter for large illustrated books (medical textbooks,
2500+ pages, mixed digital/scanned pages). Built for personal use on a
Mac Air M1, published in case it's useful to someone else.

Calibre's `ebook-convert` handles simple PDFs reasonably, but falls apart
on multi-column, image-heavy books — text comes out scrambled and images
get dropped.

### How it works

The pipeline (`pipeline.py`) runs in stages, each solved with a cheap
heuristic before reaching for anything more expensive:

1. **Per-page classification** (`ocr.py`) — every page is marked
   "digital" or "scanned" based on how much extractable text it has
   (`get_text()` < 20 chars → scanned). Decides whether OCR is needed at
   all, and which pages need table/column analysis.
2. **Selective OCR** — if there are scanned pages, `ocrmypdf --skip-text`
   runs (only touches pages with no text layer already), with
   `--tesseract-timeout` and `--skip-big` as safety valves: one
   pathological page (huge scan resolution, corrupted image) can't hang
   an entire 2000+ page book indefinitely.
3. **Chapter detection** (`outline.py`), three strategies in cascade:
   - The PDF's outline/bookmarks, if present.
   - Otherwise: a font-size heuristic — a text span sized ≥1.2× the
     dominant body size counts as a heading. Has a **plausibility
     guard**: if this produces roughly one "chapter" per page (a running
     header or page number marginally larger than body text, common in
     real books), it's rejected and falls through to the next
     fallback — verified against a real book that produced 200
     "chapters" for 200 pages before this guard existed.
   - Otherwise: a fixed page-count cut.
   - In every case, if the first detected chapter doesn't start on page
     0 (cover, foreword, table of contents before the first bookmark —
     the common case), a synthetic chapter is prepended so that content
     isn't silently dropped.
4. **Column-aware reading order** (`extract.py`) — instead of assuming a
   single column, text blocks are grouped by horizontal position
   (clustering `x0` with a column-gap threshold) and ordered column by
   column, top to bottom. Full-width blocks (headings, figure captions)
   anchor a fresh reading position instead of getting mixed into the
   columns.
5. **Repeated headers/footers** — the top/bottom 10% of a sample of pages
   is scanned, digits are normalized (`#`) so "Page 45" and "Page 46"
   count as the same pattern, and any text repeating on ≥3% of the sample
   (min 3 times) gets excluded. The threshold is deliberately low: in a
   multi-part book the running head changes per section and never covers
   a majority of the whole book — a high threshold (this project's
   original 60%) never catches any of them.
6. **Tables** — detected via PyMuPDF's `find_tables()` and always
   inserted as a recompressed image, never as extracted text. Real HTML
   table extraction via an ML layout model was tried, but on complex
   real-world data tables it silently scrambled cell order — worse than
   an image, since a reader can't tell the numbers are wrong.
7. **Images** — recompressed (JPEG, configurable max size) and
   deduplicated by content hash within each chapter, so repeated
   logos/watermarks don't show up on every page.
8. **Extraction planner** — before extracting, a cheap upfront check
   picks the strategy: a mostly-digital book with several chapters
   extracts in parallel via `ProcessPoolExecutor` (~2x measured); a book
   where OCR will dominate total time stays sequential — simpler, with
   finer-grained cancellation. Same idea as a database picking a query
   plan from estimated cost, not one fixed strategy.
9. **EPUB assembly** (`epub.py`) — chapters as XHTML (split above ~250KB
   so no single file overwhelms an e-reader's renderer), nav TOC + NCX,
   embedded Literata typeface (designed for on-screen reading, instead of
   relying on whichever "serif" each reader defaults to).

### What it does

- Per-page digital/scanned detection, OCR only where needed.
- Chapter detection via outline → font heuristic (with plausibility
  guard) → fixed cut, without dropping cover/foreword pages.
- Column-aware reading order instead of mixed-up lines.
- Tables detected and inserted as images for visual fidelity.
- Image recompression and deduplication.
- Repeated header/footer stripping, even in multi-part books with a
  different running head per section.
- Parallelizes extraction when the estimated cost justifies it.
- CLI (`pdf2epub convert`) and a minimal local web GUI (`pdf2epub serve`)
  with live progress, cancellation, and a single-job-at-a-time guard.

### What it doesn't do (out of v1 scope)

- Tables as selectable HTML (inserted as images, on purpose — see "How it
  works").
- TOC editor or preview before converting.
- Job queue / history in the web GUI.
- Direct MOBI/KFX export (use Send-to-Kindle or Calibre on the resulting
  EPUB).

### Reusable pieces for other projects

None of these depend on the document being a medical book — they could be
lifted as-is for a different kind of project:

| Piece | Where | Useful for |
|---|---|---|
| Fallback cascade for section detection (outline → heuristic → fixed) + plausibility guard | `outline.py` | Any "split a large document into sections" problem: long reports, meeting minutes, theses. |
| Column-aware reading-order heuristic (`x0` clustering) | `extract.py::_order_blocks` | Text extraction from any multi-column PDF/document layout, not just medical. |
| Repeated header/footer detection with digit normalization and a section-aware low threshold | `extract.py::detect_repeated_texts` | Any long document with running headers/footers: reports, academic papers, contracts. |
| Cost-estimate execution planner (parallel vs. sequential) | `pipeline.py::_should_parallelize_extraction` | General pattern: measure a cheap signal before deciding how to run variable-cost work. |
| Deadlock-safe subprocess wrapper (log to file, never an undrained `PIPE`) + cooperative cancellation | `ocr.py::run_ocr` | Any Python wrapper around a long-running subprocess (ffmpeg, pandoc, other CLI tools). |
| Image recompression + content-hash deduplication | `images.py` | Any pipeline processing many repeated images: scraping, document processing. |
| Background job + polling pattern for a single-user local web GUI (in-memory dict, thread, concurrency guard, cancellation) | `web/app.py` | Single-user local tools with long-running jobs, without needing Celery/Redis/real queues. |
| Benchmark-driven decision methodology (measure before rewriting, `decision.log` with an explicit accept threshold) | `scripts/benchmark_memory.py` | More a practice than code: avoids speculative optimization without evidence. |

### Requirements

- macOS (tested on Apple Silicon, M1) or Linux.
- Python ≥ 3.11 and [`uv`](https://docs.astral.sh/uv/).
- Tesseract with the languages you need, and Ghostscript (used by
  `ocrmypdf` for conversion and OCR):

  ```bash
  brew install tesseract tesseract-lang ghostscript
  ```

### Install

```bash
git clone https://github.com/luisferoviedo/pdf2epub-medical.git
cd pdf2epub-medical
uv sync
```

### Usage

```bash
uv run pdf2epub convert book.pdf -o book.epub --lang eng
uv run pdf2epub serve
```

Run `uv run pdf2epub convert --help` for the full flag list — see the
Spanish section above for the options table (same flags either way).

### Kindle notes

The resulting EPUB works directly in Apple Books and Kobo. For Kindle,
Send-to-Kindle accepts EPUBs up to 650MB — that's why image recompression
is on by default. If a heavily illustrated 2500+ page book is still too
big, lower `--max-image-size` or `--jpeg-quality`.

### Tests

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```

If `epubcheck` is installed (`brew install epubcheck`), tests also
validate the generated EPUB against the official spec. All four commands
run in CI on every push/PR.

### License

MIT. See [LICENSE](LICENSE). The embedded typeface (Literata) uses the
SIL Open Font License — see
[`src/pdf2epub/assets/fonts/OFL.txt`](src/pdf2epub/assets/fonts/OFL.txt).

---

## Português

Conversor de PDF para EPUB feito para livros grandes e ilustrados
(manuais de medicina, 2500+ páginas, mistura de páginas digitais e
escaneadas). Construído para uso pessoal em um Mac Air M1, publicado
caso seja útil para mais alguém.

O `ebook-convert` do Calibre funciona bem em PDFs simples, mas falha em
livros com múltiplas colunas e muitas ilustrações — o texto sai
desordenado e as imagens se perdem.

### Como funciona

O pipeline (`pipeline.py`) roda em etapas, cada uma resolvida com um
heurístico barato antes de recorrer a algo mais caro:

1. **Classificação por página** (`ocr.py`) — cada página é marcada como
   "digital" ou "escaneada" conforme a quantidade de texto extraível
   (`get_text()` < 20 caracteres → escaneada). Decide se é preciso OCR e
   quais páginas precisam de análise de tabela/coluna.
2. **OCR seletivo** — se há páginas escaneadas, roda `ocrmypdf
   --skip-text` (só toca páginas sem camada de texto), com
   `--tesseract-timeout` e `--skip-big` como válvulas de segurança: uma
   página patológica não pode travar um livro de 2000+ páginas
   indefinidamente.
3. **Detecção de capítulos** (`outline.py`), três estratégias em cascata:
   - Outline/marcadores do PDF, se existirem.
   - Senão: heurístico de tamanho de fonte — um trecho de texto ≥1.2× o
     tamanho dominante do corpo conta como título. Tem uma **verificação
     de plausibilidade**: se isso produzir quase um "capítulo" por
     página (um cabeçalho ou número de página um pouco maior que o
     corpo, comum em livros reais), é rejeitado e cai para o próximo
     fallback — verificado com um livro real que produzia 200
     "capítulos" para 200 páginas antes dessa verificação existir.
   - Senão: corte fixo a cada N páginas.
   - Em qualquer caso, se o primeiro capítulo detectado não começar na
     página 0 (capa, prefácio, sumário antes do primeiro marcador — o
     caso comum), um capítulo sintético é adicionado antes para não
     perder esse conteúdo silenciosamente.
4. **Ordem de leitura por colunas** (`extract.py`) — em vez de assumir
   uma única coluna, os blocos de texto são agrupados por posição
   horizontal (clustering de `x0`) e ordenados coluna por coluna, de
   cima para baixo. Blocos de largura total (títulos, legendas) ancoram
   um novo ponto de leitura em vez de se misturar às colunas.
5. **Cabeçalhos/rodapés repetidos** — os 10% superior/inferior de uma
   amostra de páginas são escaneados, dígitos são normalizados (`#`) para
   que "Página 45" e "Página 46" contem como o mesmo padrão, e qualquer
   texto que se repita em ≥3% da amostra (mín. 3 vezes) é excluído. O
   limiar é deliberadamente baixo: num livro com várias Partes, o
   cabeçalho muda por seção e nunca cobre a maioria do livro inteiro —
   um limiar alto (os 60% originais deste projeto) nunca os detecta.
6. **Tabelas** — detectadas com `find_tables()` do PyMuPDF e sempre
   inseridas como imagem recomprimida, nunca como texto extraído.
   Extração real via um modelo de layout de ML foi testada, mas em
   tabelas de dados complexas embaralhava a ordem das células — pior que
   uma imagem, já que o leitor não percebe que os números estão errados.
7. **Imagens** — recomprimidas (JPEG, tamanho máximo configurável) e
   deduplicadas por hash de conteúdo dentro de cada capítulo, para não
   repetir logos/marcas d'água em cada página.
8. **Planejador de extração** — antes de extrair, uma verificação barata
   escolhe a estratégia: um livro majoritariamente digital com vários
   capítulos extrai em paralelo via `ProcessPoolExecutor` (~2x medido);
   um livro em que o OCR vai dominar o tempo total permanece sequencial —
   mais simples, com cancelamento mais preciso. Mesma ideia de um banco
   de dados escolhendo um plano de execução pelo custo estimado, não uma
   estratégia fixa.
9. **Montagem do EPUB** (`epub.py`) — capítulos como XHTML (divididos
   acima de ~250KB para não sobrecarregar o renderizador do leitor), TOC
   nav + NCX, fonte Literata incorporada (projetada para leitura em
   tela, em vez de depender do "serif" padrão de cada leitor).

### O que faz

- Detecção digital/escaneada por página, OCR só onde necessário.
- Detecção de capítulos via outline → heurístico de fonte (com
  verificação de plausibilidade) → corte fixo, sem perder páginas de
  capa/prefácio.
- Ordem de leitura por colunas em vez de linhas misturadas.
- Tabelas detectadas e inseridas como imagens para preservar fidelidade
  visual.
- Recompressão e deduplicação de imagens.
- Remoção de cabeçalhos/rodapés repetidos, mesmo em livros de várias
  Partes com cabeçalho diferente por seção.
- Paraleliza a extração quando o custo estimado justifica.
- CLI (`pdf2epub convert`) e uma GUI web local mínima (`pdf2epub serve`)
  com progresso ao vivo, cancelamento e trava de um único job por vez.

### O que NÃO faz (fora do escopo v1)

- Tabelas como HTML selecionável (inseridas como imagem, de propósito —
  ver "Como funciona").
- Editor de sumário ou pré-visualização antes de converter.
- Fila de trabalhos / histórico na GUI web.
- Exportação direta para MOBI/KFX (use Send-to-Kindle ou Calibre sobre o
  EPUB resultante).

### Peças reutilizáveis para outros projetos

Nenhuma delas depende do documento ser um livro médico — podiam ser
aproveitadas como estão em outro tipo de projeto:

| Peça | Onde | Útil para |
|---|---|---|
| Cascata de detecção de seções com fallback (outline → heurístico → fixo) + verificação de plausibilidade | `outline.py` | Qualquer problema de "dividir um documento grande em seções": relatórios longos, atas, teses. |
| Heurístico de ordem de leitura por colunas (clustering de `x0`) | `extract.py::_order_blocks` | Extração de texto de qualquer PDF/documento com layout multi-coluna, não só médico. |
| Detecção de cabeçalhos/rodapés repetidos com normalização de dígitos e limiar baixo consciente de seções | `extract.py::detect_repeated_texts` | Qualquer documento longo com cabeçalhos/rodapés corridos: relatórios, artigos acadêmicos, contratos. |
| Planejador de estratégia por custo estimado (paralelo vs. sequencial) | `pipeline.py::_should_parallelize_extraction` | Padrão geral: medir um sinal barato antes de decidir como executar trabalho de custo variável. |
| Wrapper de subprocesso à prova de deadlock (log em arquivo, nunca `PIPE` sem drenar) + cancelamento cooperativo | `ocr.py::run_ocr` | Qualquer wrapper Python sobre um subprocesso de longa duração (ffmpeg, pandoc, outras ferramentas CLI). |
| Recompressão + deduplicação de imagens por hash | `images.py` | Qualquer pipeline que processe muitas imagens repetidas: scraping, processamento de documentos. |
| Padrão de job em background com polling para uma GUI web local de usuário único (dict em memória, thread, trava de concorrência, cancelamento) | `web/app.py` | Ferramentas locais de usuário único com jobs longos, sem precisar de Celery/Redis/filas reais. |
| Metodologia de decisão por benchmark (medir antes de reescrever, `decision.log` com limiar de aceitação explícito) | `scripts/benchmark_memory.py` | Mais uma prática que código: evita otimização especulativa sem evidência. |

### Requisitos

- macOS (testado em Apple Silicon, M1) ou Linux.
- Python ≥ 3.11 e [`uv`](https://docs.astral.sh/uv/).
- Tesseract com os idiomas que você usa, e Ghostscript (usados pelo
  `ocrmypdf` para conversão e OCR):

  ```bash
  brew install tesseract tesseract-lang ghostscript
  ```

### Instalação

```bash
git clone https://github.com/luisferoviedo/pdf2epub-medical.git
cd pdf2epub-medical
uv sync
```

### Uso

```bash
uv run pdf2epub convert livro.pdf -o livro.epub --lang por
uv run pdf2epub serve
```

Rode `uv run pdf2epub convert --help` para a lista completa de opções —
veja a seção em espanhol acima para a tabela de opções (as mesmas flags
de qualquer forma).

### Notas sobre Kindle

O EPUB resultante funciona direto no Apple Books e Kobo. Para Kindle, o
Send-to-Kindle aceita EPUB até 650MB — por isso a recompressão de
imagens vem ativada por padrão. Se um livro de 2500+ páginas muito
ilustrado ainda ficar pesado demais, reduza `--max-image-size` ou
`--jpeg-quality`.

### Tests

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src/
```

Se `epubcheck` estiver instalado (`brew install epubcheck`), os testes
também validam o EPUB gerado contra o spec oficial. Os quatro comandos
rodam no CI (GitHub Actions) em cada push/PR.

### Licença

MIT. Ver [LICENSE](LICENSE). A fonte incorporada (Literata) usa a SIL
Open Font License — ver
[`src/pdf2epub/assets/fonts/OFL.txt`](src/pdf2epub/assets/fonts/OFL.txt).
