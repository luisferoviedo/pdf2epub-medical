"""Exercises the actual FastAPI app, not just the pipeline underneath it.

Importing the app module registers every route via decorators — a route
whose return-type annotation FastAPI can't turn into a response model (e.g.
a Union of two Response subclasses without response_model=None) fails right
there at import time. No other test in this suite imports pdf2epub.web.app,
so that class of bug had zero coverage before this file existed.
"""

import time

from fastapi.testclient import TestClient

from pdf2epub.web.app import WORK_DIR, app
from tests.fixtures import make_two_column_pdf


def test_app_imports_and_registers_expected_routes():
    paths = {route.path for route in app.routes}
    assert "/" in paths
    assert "/jobs" in paths
    assert "/jobs/{job_id}" in paths
    assert "/jobs/{job_id}/cancel" in paths
    assert "/jobs/{job_id}/download" in paths


def test_index_serves_html():
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    assert "pdf2epub" in res.text


def test_job_status_not_found_returns_404():
    client = TestClient(app)
    res = client.get("/jobs/does-not-exist")
    assert res.status_code == 404


def test_download_before_ready_returns_404():
    client = TestClient(app)
    res = client.get("/jobs/does-not-exist/download")
    assert res.status_code == 404


def test_cancel_unknown_job_returns_404():
    client = TestClient(app)
    res = client.post("/jobs/does-not-exist/cancel")
    assert res.status_code == 404


def test_full_job_lifecycle_via_http(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    make_two_column_pdf(pdf_path, pages=2, with_toc=False)

    client = TestClient(app)
    with pdf_path.open("rb") as f:
        res = client.post("/jobs", files={"file": ("book.pdf", f, "application/pdf")}, data={"lang": "eng"})
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    deadline = time.monotonic() + 30
    status = None
    while time.monotonic() < deadline:
        status = client.get(f"/jobs/{job_id}").json()
        if status["status"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.2)

    assert status is not None and status["status"] == "done", status

    download = client.get(f"/jobs/{job_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/epub+zip"
    assert len(download.content) > 0


def test_upload_filename_path_traversal_is_contained(tmp_path):
    """A crafted filename like "../../etc/whatever" must not let the upload
    write outside its own job directory under WORK_DIR."""
    pdf_path = tmp_path / "book.pdf"
    make_two_column_pdf(pdf_path, pages=1, with_toc=False)

    escape_target = WORK_DIR.parent / "escaped_by_test.txt"
    escape_target.unlink(missing_ok=True)

    client = TestClient(app)
    traversal_name = f"../../{escape_target.name}"
    with pdf_path.open("rb") as f:
        res = client.post("/jobs", files={"file": (traversal_name, f, "application/pdf")})
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    assert not escape_target.exists(), "upload escaped its job directory"
    saved_files = list((WORK_DIR / job_id).iterdir())
    assert len(saved_files) == 1
    assert saved_files[0].parent == WORK_DIR / job_id

    # Drain the job so it doesn't leak into other tests.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = client.get(f"/jobs/{job_id}").json()
        if status["status"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.2)


def test_concurrent_upload_rejected_while_job_running(tmp_path):
    pdf_path = tmp_path / "book.pdf"
    make_two_column_pdf(pdf_path, pages=1, with_toc=False)

    client = TestClient(app)
    with pdf_path.open("rb") as f:
        first = client.post("/jobs", files={"file": ("book.pdf", f, "application/pdf")})
    assert first.status_code == 200
    job_id = first.json()["job_id"]

    with pdf_path.open("rb") as f:
        second = client.post("/jobs", files={"file": ("book.pdf", f, "application/pdf")})
    assert second.status_code == 409

    # Drain the first job so it doesn't leak a running background thread into other tests.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = client.get(f"/jobs/{job_id}").json()
        if status["status"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.2)
