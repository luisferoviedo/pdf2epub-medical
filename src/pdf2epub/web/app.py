"""Minimal local GUI: drop a PDF, watch progress, download the EPUB.

No queue, no history — one job runs at a time, in-memory, for personal use
on a single machine (see README: v2 scope, not this one).
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from pdf2epub.pipeline import ConvertOptions, convert

app = FastAPI(title="pdf2epub")

WORK_DIR = Path(tempfile.mkdtemp(prefix="pdf2epub_web_"))
STATIC_DIR = Path(__file__).parent / "static"

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _run_job(job_id: str, input_path: Path, output_path: Path, options: ConvertOptions) -> None:
    def on_progress(stage: str, current: int, total: int) -> None:
        with _jobs_lock:
            _jobs[job_id]["stage"] = stage
            _jobs[job_id]["current"] = current
            _jobs[job_id]["total"] = total

    try:
        convert(input_path, output_path, options=options, on_progress=on_progress)
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
    except Exception as exc:  # surfaced to the UI; the job dict is the only channel back
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/jobs")
async def create_job(
    file: Annotated[UploadFile, File()],
    lang: Annotated[str, Form()] = "spa+eng+por",
    max_image_size: Annotated[int, Form()] = 1600,
    jpeg_quality: Annotated[int, Form()] = 85,
) -> JSONResponse:
    job_id = uuid.uuid4().hex
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True)

    input_path = job_dir / (file.filename or "input.pdf")
    with input_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    output_path = job_dir / (input_path.stem + ".epub")
    options = ConvertOptions(lang=lang, max_image_size=max_image_size, jpeg_quality=jpeg_quality)

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "stage": "queued",
            "current": 0,
            "total": 0,
            "output_path": str(output_path),
            "filename": output_path.name,
        }

    thread = threading.Thread(target=_run_job, args=(job_id, input_path, output_path, options), daemon=True)
    thread.start()

    return JSONResponse({"job_id": job_id})


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return JSONResponse({"error": "job no encontrado"}, status_code=404)
    return JSONResponse({k: v for k, v in job.items() if k != "output_path"})


@app.get("/jobs/{job_id}/download")
def job_download(job_id: str) -> FileResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None or job["status"] != "done":
        return JSONResponse({"error": "job no listo"}, status_code=404)
    return FileResponse(job["output_path"], filename=job["filename"], media_type="application/epub+zip")
