import asyncio
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Entry, Health, Inspection
from app.runtime import WorkerError


class FakeRunner:
    def __init__(self):
        self.running = 0
        self.maximum = 0
        self.cancelled = 0
        self.calls = []

    async def run(self, payload, on_event):
        self.calls.append(payload)
        if payload["mode"] == "inspect":
            if "inspect-fail" in payload["url"]:
                raise WorkerError("This video is unavailable or has been removed.")
            if "inspect-slow" in payload["url"]:
                await asyncio.sleep(30)
            entries = [
                Entry(
                    id="1",
                    position=1,
                    title="A quiet morning",
                    url="https://example.com/good",
                    duration=120,
                )
            ]
            if payload["playlist"]:
                entries += [
                    Entry(
                        id="2", position=2, title="A quiet morning", url="https://example.com/good2"
                    ),
                    Entry(
                        id="3", position=3, title="A removed video", url="https://example.com/fail"
                    ),
                    Entry(id="4", position=4, title="Private", available=False),
                ]
            if "slow" in payload["url"]:
                entries[0].url = "https://example.com/slow"
            inspection = Inspection(
                id=uuid4().hex,
                source_url=payload["url"],
                title="Weekend favorites",
                kind="playlist" if payload["playlist"] else "video",
                entries=entries,
                limit=payload["limit"],
            )
            await on_event({"event": "inspection", "data": inspection.model_dump()})
            return
        self.running += 1
        self.maximum = max(self.maximum, self.running)
        try:
            await on_event(
                {
                    "event": "progress",
                    "downloaded_bytes": 10,
                    "total_bytes": 20,
                    "speed": 100,
                    "eta": 1,
                }
            )
            await asyncio.sleep(30 if "slow" in payload["url"] else 0.08)
            if "fail" in payload["url"]:
                raise WorkerError("This video is unavailable or has been removed.")
            await on_event({"event": "processing"})
            directory = Path(payload["directory"])
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "same-title.mp4"
            path.write_bytes(b"local fixture media")
            await on_event({"event": "completed", "path": str(path), "title": "A quiet morning"})
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.running -= 1


@pytest.fixture
def fake_health(monkeypatch):
    def check(*_):
        return Health(
            ready=True,
            dependencies={
                "ffmpeg": True,
                "ffprobe": True,
                "node": True,
                "storage": True,
                "cookies": True,
            },
            issues=[],
            cookie_configured=False,
        )

    monkeypatch.setattr("app.runtime.preflight", check)


@pytest.fixture
def configured(tmp_path, fake_health):
    runner = FakeRunner()
    settings = Settings(data_dir=tmp_path / "downloads", _env_file=None)
    app = create_app(settings, runner)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client, app, runner, settings


def inspect(client, *, playlist=False, url="https://example.com/video"):
    response = client.post("/api/inspect", json={"url": url, "playlist": playlist})
    assert response.status_code == 200, response.text
    return response.json()


def create_job(client, preview=None, entry_ids=None, **kwargs):
    preview = preview or inspect(client)
    response = client.post(
        "/api/jobs",
        json={
            "inspection_id": preview["id"],
            "entry_ids": entry_ids or ["1"],
            **kwargs,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def wait_job(client, job_id, *, status=None, archive=False):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        settled = job["status"] in {"completed", "partial", "failed", "cancelled", "interrupted"}
        if (job["status"] == status if status else settled) and (
            not archive or job["archive_status"] in {"ready", "failed"}
        ):
            return job
        time.sleep(0.02)
    raise AssertionError(f"Timed out waiting for {job_id}: {job}")
