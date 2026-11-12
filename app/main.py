from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import ROOT, Settings
from app.db import Database
from app.models import TERMINAL, Health, Inspection, InspectRequest, Job, JobCreate
from app.runtime import DataDirectory, Manager, WorkerError, safe_file

ID = Annotated[str, ApiPath(pattern=r"^[a-f0-9]{32}$")]
LOCAL_ORIGINS = {
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}


def create_app(settings: Settings | None = None, runner=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        directory = DataDirectory(settings.data_dir)
        directory.acquire()
        db = Database(directory.root / "jobs.sqlite3")
        try:
            await db.open()
            manager = Manager(db, settings, directory.root, runner)
            app.state.manager = manager
            await manager.start()
            try:
                yield
            finally:
                await manager.stop()
        finally:
            if hasattr(db, "conn"):
                await db.close()
            directory.release()

    app = FastAPI(title="Local Video Downloader", version="0.1.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin not in LOCAL_ORIGINS:
                return Response("Origin is not permitted.", status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return Response("Cross-site requests are not permitted.", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def manager() -> Manager:
        return app.state.manager

    async def ready():
        health = await manager().check()
        if not health.ready:
            raise HTTPException(503, detail=" ".join(health.issues))

    async def find_job(job_id: str) -> Job:
        job = await manager().db.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found.")
        return job

    @app.get("/api/health", response_model=Health)
    async def health():
        return await manager().check()

    @app.post("/api/inspect", response_model=Inspection)
    async def inspect(body: InspectRequest):
        await ready()
        try:
            return await manager().inspect(body.url, body.playlist)
        except WorkerError as error:
            raise HTTPException(422, str(error)) from None

    @app.post("/api/jobs", status_code=202, response_model=Job)
    async def create_job(body: JobCreate):
        await ready()
        inspection = await manager().db.inspection(body.inspection_id)
        if inspection is None:
            raise HTTPException(404, "Preview expired or was not found. Inspect the link again.")
        selected = set(body.entry_ids)
        entries = [e for e in inspection.entries if e.id in selected and e.available and e.url]
        if len(entries) != len(selected):
            raise HTTPException(422, "Select available entries from this preview.")
        async with manager().guard:
            job_id = await manager().db.create_job(
                inspection, entries, body.preset, body.resolution
            )
        return await find_job(job_id)

    @app.get("/api/jobs", response_model=list[Job])
    async def list_jobs(
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        return await manager().db.list_jobs(limit, offset)

    @app.get("/api/jobs/{job_id}", response_model=Job)
    async def get_job(job_id: ID):
        return await find_job(job_id)

    @app.post("/api/jobs/{job_id}/cancel", response_model=Job)
    async def cancel(job_id: ID):
        await find_job(job_id)
        await manager().cancel(job_id)
        return await find_job(job_id)

    @app.post("/api/jobs/{job_id}/retry", response_model=Job, status_code=202)
    async def retry(job_id: ID):
        await ready()
        async with manager().guard:
            job = await find_job(job_id)
            if job.status not in TERMINAL:
                raise HTTPException(409, "Wait for this job to finish or cancel it first.")
            inspection, entries = await manager().db.retry_data(job)
            if not entries:
                raise HTTPException(409, "There are no unsuccessful entries to retry.")
            new_id = await manager().db.create_job(inspection, entries, job.preset, job.resolution)
        return await find_job(new_id)

    @app.get("/api/jobs/{job_id}/files/{file_id}")
    async def file(job_id: ID, file_id: ID):
        await find_job(job_id)
        rows = await manager().db.rows(
            "SELECT relative_path, filename FROM items WHERE job_id=? AND file_id=? "
            "AND status='completed'",
            (job_id, file_id),
        )
        if not rows:
            raise HTTPException(404, "File not found.")
        try:
            path = safe_file(manager().root, rows[0]["relative_path"])
        except (FileNotFoundError, ValueError):
            raise HTTPException(404, "The media file is missing. Create a new download.") from None
        return FileResponse(
            path, filename=rows[0]["filename"], media_type="application/octet-stream"
        )

    @app.get("/api/jobs/{job_id}/archive")
    async def archive(job_id: ID):
        job = await find_job(job_id)
        if job.archive_status != "ready":
            raise HTTPException(409, job.archive_error or "The ZIP archive is not ready yet.")
        try:
            path = safe_file(manager().root, f"{job_id}/playlist.zip")
        except FileNotFoundError:
            raise HTTPException(404, "The ZIP archive is missing.") from None
        return FileResponse(
            path, filename=f"playlist-{job_id[:8]}.zip", media_type="application/zip"
        )

    @app.delete("/api/jobs/{job_id}", status_code=204)
    async def delete(job_id: ID):
        await find_job(job_id)
        try:
            await manager().delete(job_id)
        except OSError:
            raise HTTPException(
                409,
                "Could not remove the managed files. Check filesystem permissions and try again.",
            ) from None
        return Response(status_code=204)

    # Register API routes first so static serving cannot shadow API errors or /docs.
    distribution = ROOT / "frontend" / "dist"
    if distribution.is_dir():
        app.mount("/", StaticFiles(directory=distribution, html=True), name="frontend")
    else:

        @app.get("/", include_in_schema=False)
        async def frontend_missing():
            return {
                "message": "Run the frontend dev server, or run make build and restart the API."
            }

    return app


app = create_app()
