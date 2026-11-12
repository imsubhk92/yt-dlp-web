import io
import sqlite3
import time
import zipfile
from contextlib import closing
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Health
from tests.conftest import create_job, inspect, wait_job


def test_preview_selection_and_validation(configured):
    client, _, _, _ = configured
    preview = inspect(client, playlist=True)
    assert preview["kind"] == "playlist"
    assert preview["entries"][-1]["available"] is False
    job = create_job(client, preview, ["2", "1"])
    assert [i["position"] for i in job["items"]] == [1, 2]
    for entries in (["4"], ["absent"], ["1", "1"], []):
        response = client.post(
            "/api/jobs",
            json={
                "inspection_id": preview["id"],
                "entry_ids": entries,
            },
        )
        assert response.status_code == 422


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://example.com/a", "https://u:p@example.com", "junk"]
)
def test_invalid_urls(configured, url):
    assert configured[0].post("/api/inspect", json={"url": url}).status_code == 422


def test_partial_playlist_zip_and_retry(configured):
    client, _, runner, _ = configured
    job = create_job(client, inspect(client, playlist=True), ["1", "2", "3"])
    done = wait_job(client, job["id"], archive=True)
    assert done["status"] == "partial"
    assert done["completed_count"] == 2
    assert runner.maximum == 2
    archive = client.get(f"/api/jobs/{job['id']}/archive")
    with zipfile.ZipFile(io.BytesIO(archive.content)) as result:
        assert result.namelist() == ["0001 - same-title.mp4", "0002 - same-title.mp4"]
        assert all(result.read(name) == b"local fixture media" for name in result.namelist())
    retry = client.post(f"/api/jobs/{job['id']}/retry")
    assert retry.status_code == 202
    assert retry.json()["total_count"] == 1
    assert retry.json()["items"][0]["position"] == 3
    assert retry.json()["id"] != job["id"]


def test_download_files_missing_ids_and_delete(configured):
    client, _, _, settings = configured
    job = wait_job(client, create_job(client)["id"])
    file_id = job["items"][0]["file_id"]
    url = f"/api/jobs/{job['id']}/files/{file_id}"
    assert client.get(url).content == b"local fixture media"
    assert "attachment" in client.get(url).headers["content-disposition"]
    assert client.get(f"/api/jobs/{job['id']}/files/{uuid4().hex}").status_code == 404
    assert client.get(f"/api/jobs/{job['id']}/archive").status_code == 409
    next((settings.data_dir / job["id"]).rglob("*.mp4")).unlink()
    assert client.get(url).status_code == 404
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert not (settings.data_dir / job["id"]).exists()
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404


def test_file_traversal_and_symlink(configured, tmp_path):
    client, app, _, settings = configured
    job = wait_job(client, create_job(client)["id"])
    outside = tmp_path / "secret.txt"
    outside.write_text("not downloadable")
    link = settings.data_dir / job["id"] / "escape.mp4"
    link.symlink_to(outside)
    with closing(sqlite3.connect(settings.data_dir / "jobs.sqlite3", autocommit=True)) as db:
        db.execute(
            "UPDATE items SET relative_path=? WHERE job_id=?",
            (f"{job['id']}/escape.mp4", job["id"]),
        )
    url = f"/api/jobs/{job['id']}/files/{job['items'][0]['file_id']}"
    assert client.get(url).status_code == 404
    with closing(sqlite3.connect(settings.data_dir / "jobs.sqlite3", autocommit=True)) as db:
        db.execute("UPDATE items SET relative_path=? WHERE job_id=?", (str(outside), job["id"]))
    assert client.get(url).status_code == 404
    assert client.get("/api/jobs/not-a-job").status_code == 422


def test_cancel_running_and_late_completion(configured):
    client, _, runner, _ = configured
    job = create_job(client, inspect(client, url="https://example.com/slow"))
    wait_job(client, job["id"], status="downloading")
    response = client.post(f"/api/jobs/{job['id']}/cancel")
    assert response.json()["status"] == "cancelled"
    time.sleep(0.1)
    result = client.get(f"/api/jobs/{job['id']}").json()
    assert result["items"][0]["status"] == "cancelled"
    assert result["items"][0]["file_id"] is None
    assert runner.cancelled == 1
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200


def test_delete_running_job(configured):
    client, _, runner, settings = configured
    job = create_job(client, inspect(client, url="https://example.com/slow"))
    wait_job(client, job["id"], status="downloading")
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert runner.running == 0
    assert not (settings.data_dir / job["id"]).exists()


def test_restart_recovery_and_lock(tmp_path, fake_health):
    from app.config import Settings
    from tests.conftest import FakeRunner

    settings = Settings(data_dir=tmp_path / "store", concurrency=1, _env_file=None)
    runner = FakeRunner()
    first = create_app(settings, runner)
    with TestClient(first, base_url="http://127.0.0.1:8000") as client:
        completed = wait_job(client, create_job(client)["id"])
        running = create_job(client, inspect(client, url="https://example.com/slow"))
        wait_job(client, running["id"], status="downloading")
        queued = create_job(client)
        with pytest.raises(RuntimeError, match="Another app instance"):
            with TestClient(create_app(settings, FakeRunner()), base_url="http://127.0.0.1:8000"):
                pass
    with TestClient(create_app(settings, FakeRunner()), base_url="http://127.0.0.1:8000") as client:
        assert client.get(f"/api/jobs/{completed['id']}").json()["status"] == "completed"
        assert client.get(f"/api/jobs/{running['id']}").json()["status"] == "interrupted"
        assert wait_job(client, queued["id"])["status"] == "completed"


def test_dependency_failure_blocks_new_work(configured, monkeypatch):
    client, _, runner, _ = configured
    monkeypatch.setattr(
        "app.runtime.preflight",
        lambda *_: Health(
            ready=False,
            dependencies={"node": False},
            issues=["Install Node 24."],
            cookie_configured=False,
        ),
    )
    assert client.get("/api/health").json()["ready"] is False
    assert client.post("/api/inspect", json={"url": "https://example.com"}).status_code == 503
    assert runner.calls == []


def test_host_origin_and_inspection_errors(configured):
    client, _, _, _ = configured
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400
    assert (
        client.post(
            "/api/inspect",
            json={"url": "https://example.com"},
            headers={"origin": "https://evil.example"},
        ).status_code
        == 403
    )
    response = client.post("/api/inspect", json={"url": "https://example.com/inspect-fail"})
    assert response.status_code == 422
    assert "unavailable" in response.json()["detail"]
    assert (
        client.post("/api/jobs", json={"inspection_id": "a" * 32, "entry_ids": ["1"]}).status_code
        == 404
    )


def test_history_pagination(configured):
    client, _, _, _ = configured
    create_job(client)
    create_job(client)
    assert len(client.get("/api/jobs?limit=1").json()) == 1
    assert len(client.get("/api/jobs?limit=1&offset=1").json()) == 1
    assert client.get("/api/jobs?limit=101").status_code == 422


def test_archive_failure_keeps_media(configured, monkeypatch):
    client, app, _, _ = configured

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr(app.state.manager, "zip_files", fail)
    job = create_job(client, inspect(client, playlist=True), ["1", "2"])
    done = wait_job(client, job["id"], archive=True)
    assert done["status"] == "completed"
    assert done["archive_status"] == "failed"
    assert "Individual" in done["archive_error"]
    assert (
        client.get(f"/api/jobs/{job['id']}/files/{done['items'][0]['file_id']}").status_code == 200
    )


def test_delete_failure_preserves_history(configured, monkeypatch):
    client, _, _, _ = configured
    job = wait_job(client, create_job(client)["id"])

    def fail(*args, **kwargs):
        raise PermissionError("Cannot remove file")

    monkeypatch.setattr("app.runtime.shutil.rmtree", fail)
    response = client.delete(f"/api/jobs/{job['id']}")
    assert response.status_code == 409
    assert client.get(f"/api/jobs/{job['id']}").status_code == 200
