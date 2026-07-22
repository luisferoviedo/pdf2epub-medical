"""Minimal local GUI: drop a PDF, watch progress, download the EPUB.

No queue, no history — one job runs at a time, in-memory, for personal use
on a single machine (see README: v2 scope, not this one). A second upload
while one is running is rejected outright rather than queued.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import traceback
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from pdf2epub.errors import ConversionCancelled
from pdf2epub.pipeline import ConvertOptions, convert

app = FastAPI(title="pdf2epub")

WORK_DIR = Path(tempfile.mkdtemp(prefix="pdf2epub_web_"))
STATIC_DIR = Path(__file__).parent / "static"

_jobs: dict[str, dict] = {}
_cancel_events: dict[str, threading.Event] = {}
_jobs_lock = threading.Lock()


def _run_job(
    job_id: str, input_path: Path, output_path: Path, options: ConvertOptions, cancel_event: threading.Event
) -> None:
    def on_progress(stage: str, current: int, total: int) -> None:
        with _jobs_lock:
            _jobs[job_id]["stage"] = stage
            _jobs[job_id]["current"] = current
            _jobs[job_id]["total"] = total

    try:
        convert(input_path, output_path, options=options, on_progress=on_progress, cancel_event=cancel_event)
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
    except ConversionCancelled:
        with _jobs_lock:
            _jobs[job_id]["status"] = "cancelled"
    except subprocess.CalledProcessError as exc:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error_summary"] = f"Falló un paso externo ({exc.cmd[0] if exc.cmd else 'proceso'})."
            _jobs[job_id]["error_detail"] = exc.stderr or str(exc)
    except Exception as exc:  # surfaced to the UI; the job dict is the only channel back
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error_summary"] = f"{type(exc).__name__}: {exc}"
            _jobs[job_id]["error_detail"] = traceback.format_exc()
    finally:
        with _jobs_lock:
            _cancel_events.pop(job_id, None)


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
    with _jobs_lock:
        if any(job["status"] == "running" for job in _jobs.values()):
            return JSONResponse(
                {"error": "Ya hay una conversión en curso. Espera a que termine o cancélala."}, status_code=409
            )

    job_id = uuid.uuid4().hex
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True)

    # .name strips any directory components the client sent (e.g. "../../etc/foo")
    # — without this, a crafted filename can write outside job_dir entirely.
    safe_filename = Path(file.filename or "").name
    if not safe_filename or safe_filename in (".", ".."):
        safe_filename = "input.pdf"
    input_path = job_dir / safe_filename
    with input_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    output_path = job_dir / (input_path.stem + ".epub")
    options = ConvertOptions(lang=lang, max_image_size=max_image_size, jpeg_quality=jpeg_quality)
    cancel_event = threading.Event()

    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "stage": "queued",
            "current": 0,
            "total": 0,
            "output_path": str(output_path),
            "filename": output_path.name,
        }
        _cancel_events[job_id] = cancel_event

    thread = threading.Thread(
        target=_run_job, args=(job_id, input_path, output_path, options, cancel_event), daemon=True
    )
    thread.start()

    return JSONResponse({"job_id": job_id})


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> JSONResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return JSONResponse({"error": "job no encontrado"}, status_code=404)
    return JSONResponse({k: v for k, v in job.items() if k != "output_path"})


@app.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> JSONResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
        event = _cancel_events.get(job_id)
    if job is None:
        return JSONResponse({"error": "job no encontrado"}, status_code=404)
    if job["status"] != "running" or event is None:
        return JSONResponse({"error": "el job ya no está corriendo"}, status_code=409)
    event.set()
    return JSONResponse({"status": "cancelando"})


@app.get("/jobs/{job_id}/download", response_model=None)
def job_download(job_id: str) -> FileResponse | JSONResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None or job["status"] != "done":
        return JSONResponse({"error": "job no listo"}, status_code=404)
    return FileResponse(job["output_path"], filename=job["filename"], media_type="application/epub+zip")
