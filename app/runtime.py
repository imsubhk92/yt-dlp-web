import asyncio
import contextlib
import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from uuid import uuid4

from app.config import ROOT, Settings
from app.db import Database
from app.models import TERMINAL, Health, Inspection


class WorkerError(Exception):
    pass


class DataDirectory:
    def __init__(self, path: Path):
        self.root = path.expanduser().resolve()

    def acquire(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.handle = (self.root / ".instance.lock").open("a")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError(
                "Another app instance is already using this data directory."
            ) from None

    def release(self):
        self.handle.close()


def safe_file(root: Path, relative_path: str) -> Path:
    candidate = root / relative_path
    if Path(relative_path).is_absolute():
        raise FileNotFoundError
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise FileNotFoundError
    # Reject symlinks even when they happen to point within the managed directory.
    if any(p.is_symlink() for p in [candidate, *candidate.parents] if p != root.parent):
        raise FileNotFoundError
    return resolved


def preflight(settings: Settings, root: Path) -> Health:
    dependencies = {}
    issues = []
    for name, executable in (
        ("ffmpeg", "ffmpeg"),
        ("ffprobe", "ffprobe"),
        ("node", settings.node_path),
    ):
        executable = shutil.which(executable)
        valid = False
        if executable:
            try:
                result = subprocess.run(
                    [executable, "--version" if name == "node" else "-version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True,
                )
                valid = name != "node" or int(result.stdout.strip().lstrip("v").split(".")[0]) >= 24
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        dependencies[name] = valid
        if not valid:
            issues.append(
                f"Install {'Node 24 or newer' if name == 'node' else name} and check PATH."
            )
    try:
        with tempfile.TemporaryFile(dir=root) as handle:
            handle.write(b"ready")
            handle.flush()
        dependencies["storage"] = shutil.disk_usage(root).free >= 64 * 1024 * 1024
    except OSError:
        dependencies["storage"] = False
    if not dependencies["storage"]:
        issues.append("Storage must be writable with at least 64 MiB free.")
    dependencies["cookies"] = True
    if settings.cookie_file:
        try:
            with settings.cookie_file.expanduser().open("rb") as handle:
                dependencies["cookies"] = handle.readline().strip() in {
                    b"# Netscape HTTP Cookie File",
                    b"# HTTP Cookie File",
                }
        except OSError:
            dependencies["cookies"] = False
        if not dependencies["cookies"]:
            issues.append("The configured cookie file must be readable in Mozilla/Netscape format.")
    return Health(
        ready=all(dependencies.values()),
        dependencies=dependencies,
        issues=issues,
        cookie_configured=settings.cookie_file is not None,
    )


async def terminate_group(process):
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
    # A crashed worker can leave descendants after its own exit. Reap that group too.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


class WorkerRunner:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def run(self, payload: dict, on_event):
        private_directory = tempfile.TemporaryDirectory(prefix="yt-dlp-web-worker-")
        payload = {
            **payload,
            "cookie_temp_dir": private_directory.name,
            "node_path": self.settings.node_path,
            "cookie_file": str(self.settings.cookie_file.expanduser().resolve())
            if self.settings.cookie_file
            else None,
        }
        creation = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.worker",
                cwd=ROOT,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                limit=8 * 1024 * 1024,
            )
        )
        process = None
        try:
            # Shield spawning so cancellation cannot lose a just-created subprocess.
            process = await asyncio.shield(creation)
            process.stdin.write(json.dumps(payload).encode() + b"\n")
            await process.stdin.drain()
            error = None
            async for line in process.stdout:
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    raise WorkerError("The download worker returned an invalid event.") from None
                if event.get("event") == "error":
                    error = event["message"]
                else:
                    await on_event(event)
            code = await process.wait()
            if code or error:
                raise WorkerError(error or "The download worker stopped unexpectedly.")
        finally:
            if process is None:
                with contextlib.suppress(Exception):
                    process = await creation
            if process:
                await terminate_group(process)
                process.stdin.close()
            private_directory.cleanup()


class Manager:
    def __init__(self, db: Database, settings: Settings, root: Path, runner=None):
        self.db, self.settings, self.root = db, settings, root
        self.runner = runner or WorkerRunner(settings)
        self.guard = asyncio.Lock()
        self.inspect_slots = asyncio.Semaphore(2)
        self.inspections: set[asyncio.Task] = set()
        self.active: dict[str, tuple[str, asyncio.Task]] = {}
        self.archives: dict[str, tuple[asyncio.Task, threading.Event]] = {}
        self.stopping = False
        self.ready = False

    async def check(self) -> Health:
        health = await asyncio.to_thread(preflight, self.settings, self.root)
        self.ready = health.ready
        return health

    async def inspect(self, url: str, playlist: bool) -> Inspection:
        result = None

        async def event(data):
            nonlocal result
            if data.get("event") == "inspection":
                result = Inspection.model_validate(data["data"])

        async with self.inspect_slots:
            task = asyncio.create_task(
                self.runner.run(
                    {
                        "mode": "inspect",
                        "url": url,
                        "playlist": playlist,
                        "limit": self.settings.playlist_limit,
                    },
                    event,
                )
            )
            self.inspections.add(task)
            try:
                await asyncio.wait_for(task, self.settings.inspect_timeout)
            except TimeoutError:
                raise WorkerError(
                    "Inspection timed out. Try a smaller playlist or check access."
                ) from None
            finally:
                self.inspections.discard(task)
        if result is None:
            raise WorkerError("No video metadata was returned for this link.")
        await self.db.save_inspection(result)
        return result

    async def start(self):
        await self.check()
        self.scheduler = asyncio.create_task(self.schedule())

    async def stop(self):
        self.stopping = True
        self.scheduler.cancel()
        await asyncio.gather(self.scheduler, return_exceptions=True)
        for task in self.inspections:
            task.cancel()
        tasks = list(self.inspections)
        for _, task in self.active.values():
            task.cancel()
            tasks.append(task)
        for task, stop in self.archives.values():
            stop.set()
            tasks.append(task)
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.db.refresh_jobs()

    async def schedule(self):
        while not self.stopping:
            async with self.guard:
                if self.ready:
                    queued = await self.db.queued(self.settings.concurrency - len(self.active))
                    for item in queued:
                        await self.db.update_item(item["id"], status="downloading")
                        task = asyncio.create_task(self.run_item(item))
                        self.active[item["id"]] = (item["job_id"], task)
                await self.db.refresh_jobs()
                settled = await self.db.rows(
                    "SELECT id FROM jobs WHERE status IN "
                    "('completed','partial','cancelled','interrupted') AND archive_status='none' "
                    "AND kind='playlist' AND (SELECT count(*) FROM items WHERE job_id=jobs.id "
                    "AND status='completed') > 0"
                )
                for job in settled:
                    if job["id"] not in self.archives:
                        await self.db.write(
                            "UPDATE jobs SET archive_status='building' WHERE id=?", (job["id"],)
                        )
                        stop = threading.Event()
                        task = asyncio.create_task(self.build_archive(job["id"], stop))
                        self.archives[job["id"]] = (task, stop)
            await asyncio.sleep(0.2)

    async def run_item(self, item: dict):
        final = None

        async def event(data):
            nonlocal final
            if data["event"] == "progress":
                await self.db.update_item(
                    item["id"],
                    status="downloading",
                    **{
                        key: data.get(key)
                        for key in ("downloaded_bytes", "total_bytes", "speed", "eta")
                    },
                )
            elif data["event"] == "processing":
                await self.db.update_item(item["id"], status="processing", speed=None, eta=None)
            elif data["event"] == "completed":
                final = data

        directory = self.root / item["job_id"] / item["id"]
        try:
            await self.runner.run(
                {
                    "mode": "download",
                    "url": item["url"],
                    "directory": str(directory),
                    "preset": item["preset"],
                    "resolution": item["resolution"],
                },
                event,
            )
            if not final:
                raise WorkerError("The worker finished without producing a media file.")
            path = Path(final["path"])
            relative = path.relative_to(self.root).as_posix()
            path = safe_file(self.root, relative)
            if not path.is_relative_to(directory):
                raise WorkerError("The worker returned an invalid media file.")
            size = path.stat().st_size
            await self.db.update_item(
                item["id"],
                status="completed",
                file_id=uuid4().hex,
                filename=path.name,
                relative_path=relative,
                size=size,
                title=final.get("title", item["title"]),
                downloaded_bytes=size,
                total_bytes=size,
                speed=None,
                eta=None,
            )
        except asyncio.CancelledError:
            await self.db.update_item(item["id"], status="interrupted", error="App stopped.")
            raise
        except Exception as error:
            message = (
                str(error) if isinstance(error, WorkerError) else "Unable to save the media file."
            )
            await self.db.update_item(
                item["id"], status="failed", error=message, speed=None, eta=None
            )
        finally:
            # Partial files are never offered for download and need not consume disk indefinitely.
            rows = await self.db.rows("SELECT status FROM items WHERE id=?", (item["id"],))
            if rows and rows[0]["status"] != "completed":
                await asyncio.to_thread(shutil.rmtree, directory, True)
            self.active.pop(item["id"], None)
            await self.db.refresh_jobs()

    def zip_files(self, job_id: str, items: list[dict], stop: threading.Event):
        directory = self.root / job_id
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "playlist.zip.part"
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
                for item in items:
                    path = safe_file(self.root, item["relative_path"])
                    name = f"{item['position']:04d} - {path.name}"
                    with (
                        path.open("rb") as source,
                        archive.open(name, "w", force_zip64=True) as target,
                    ):
                        while chunk := source.read(1024 * 1024):
                            if stop.is_set():
                                raise InterruptedError
                            target.write(chunk)
            if stop.is_set():
                raise InterruptedError
            temporary.replace(directory / "playlist.zip")
        finally:
            temporary.unlink(missing_ok=True)

    async def build_archive(self, job_id: str, stop: threading.Event):
        try:
            items = await self.db.rows(
                "SELECT * FROM items WHERE job_id=? AND status='completed' ORDER BY position",
                (job_id,),
            )
            await asyncio.to_thread(self.zip_files, job_id, items, stop)
            await self.db.write(
                "UPDATE jobs SET archive_status='ready', archive_error=NULL WHERE id=?", (job_id,)
            )
        except InterruptedError:
            await self.db.write("UPDATE jobs SET archive_status='none' WHERE id=?", (job_id,))
        except Exception:
            await self.db.write(
                "UPDATE jobs SET archive_status='failed', archive_error=? WHERE id=?",
                ("Could not build ZIP. Individual media files are still available.", job_id),
            )
        finally:
            self.archives.pop(job_id, None)

    async def cancel(self, job_id: str):
        async with self.guard:
            await self.cancel_locked(job_id)

    async def cancel_locked(self, job_id: str):
        job = await self.db.get_job(job_id)
        if job is None or job.status in TERMINAL:
            return
        await self.db.write("UPDATE jobs SET status='cancelled' WHERE id=?", (job_id,))
        await self.db.write(
            "UPDATE items SET status='cancelled', speed=NULL, eta=NULL WHERE job_id=? "
            "AND status IN ('queued','downloading','processing')",
            (job_id,),
        )
        tasks = [task for owner, task in self.active.values() if owner == job_id]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def delete(self, job_id: str):
        async with self.guard:
            await self.cancel_locked(job_id)
            if job_id in self.archives:
                task, stop = self.archives[job_id]
                stop.set()
                await task
            directory = self.root / job_id
            if directory.exists():
                await asyncio.to_thread(shutil.rmtree, directory)
            await self.db.write("DELETE FROM jobs WHERE id=?", (job_id,))
