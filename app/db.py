import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import aiosqlite

from app.models import Entry, Inspection, Item, Job, Preset, Resolution


def now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """One serialized writer; SQLite is owned exclusively by the API process."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = asyncio.Lock()

    async def open(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS inspections (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, source_url TEXT NOT NULL,
                kind TEXT NOT NULL, preset TEXT NOT NULL, resolution INTEGER,
                status TEXT NOT NULL, created_at TEXT NOT NULL,
                archive_status TEXT NOT NULL DEFAULT 'none', archive_error TEXT
            );
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                position INTEGER NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
                status TEXT NOT NULL, downloaded_bytes INTEGER NOT NULL DEFAULT 0,
                total_bytes INTEGER, speed REAL, eta REAL, error TEXT,
                file_id TEXT, filename TEXT, relative_path TEXT, size INTEGER
            );
            CREATE INDEX IF NOT EXISTS items_queue ON items(status, job_id, position);
        """)
        # Queued work survives; running subprocesses cannot safely be resumed as running.
        await self.write(
            "UPDATE items SET status='interrupted', error='App stopped during this download.' "
            "WHERE status IN ('downloading','processing')"
        )
        await self.write(
            "UPDATE jobs SET archive_status='none', archive_error=NULL "
            "WHERE archive_status='building'"
        )
        await self.refresh_jobs()

    async def close(self):
        await self.conn.close()

    async def write(self, sql: str, values=()):
        async with self.lock:
            cursor = await self.conn.execute(sql, values)
            await self.conn.commit()
            return cursor.rowcount

    async def rows(self, sql: str, values=()) -> list[dict]:
        async with self.lock:
            async with self.conn.execute(sql, values) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def save_inspection(self, inspection: Inspection):
        await self.write(
            "DELETE FROM inspections WHERE julianday(created_at) < julianday('now', '-1 day')"
        )
        await self.write(
            "INSERT INTO inspections VALUES (?, ?, ?)",
            (inspection.id, inspection.model_dump_json(), now()),
        )

    async def inspection(self, inspection_id: str) -> Inspection | None:
        rows = await self.rows("SELECT payload FROM inspections WHERE id=?", (inspection_id,))
        return Inspection.model_validate_json(rows[0]["payload"]) if rows else None

    async def create_job(
        self, inspection: Inspection, entries: list[Entry], preset: Preset, resolution: Resolution
    ) -> str:
        job_id = uuid4().hex
        async with self.lock:
            try:
                await self.conn.execute(
                    "INSERT INTO jobs"
                    "(id,title,source_url,kind,preset,resolution,status,created_at) "
                    "VALUES (?,?,?,?,?,?,'queued',?)",
                    (
                        job_id,
                        inspection.title,
                        inspection.source_url,
                        inspection.kind,
                        preset.value,
                        resolution,
                        now(),
                    ),
                )
                await self.conn.executemany(
                    "INSERT INTO items(id,job_id,position,title,url,status) "
                    "VALUES (?,?,?,?,?,'queued')",
                    [(uuid4().hex, job_id, e.position, e.title, e.url) for e in entries],
                )
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback()
                raise
        return job_id

    async def get_job(self, job_id: str) -> Job | None:
        rows = await self.rows("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not rows:
            return None
        items = await self.rows("SELECT * FROM items WHERE job_id=? ORDER BY position", (job_id,))
        return Job(
            **rows[0],
            items=[Item(**i) for i in items],
            total_count=len(items),
            completed_count=sum(i["status"] == "completed" for i in items),
        )

    async def list_jobs(self, limit: int, offset: int) -> list[Job]:
        rows = await self.rows(
            "SELECT id FROM jobs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [job for r in rows if (job := await self.get_job(r["id"])) is not None]

    async def refresh_jobs(self):
        await self.write("""
            UPDATE jobs SET status = CASE
                WHEN status='cancelled' THEN 'cancelled'
                WHEN EXISTS(SELECT 1 FROM items WHERE job_id=jobs.id AND status='downloading')
                    THEN 'downloading'
                WHEN EXISTS(SELECT 1 FROM items WHERE job_id=jobs.id AND status='processing')
                    THEN 'processing'
                WHEN EXISTS(SELECT 1 FROM items WHERE job_id=jobs.id AND status='queued')
                    THEN 'queued'
                WHEN NOT EXISTS(SELECT 1 FROM items WHERE job_id=jobs.id AND status!='completed')
                    THEN 'completed'
                WHEN EXISTS(SELECT 1 FROM items WHERE job_id=jobs.id AND status='completed')
                    THEN 'partial'
                WHEN EXISTS(SELECT 1 FROM items WHERE job_id=jobs.id AND status='interrupted')
                    THEN 'interrupted'
                ELSE 'failed' END
        """)

    async def queued(self, limit: int) -> list[dict]:
        return await self.rows(
            "SELECT items.*, jobs.preset, jobs.resolution FROM items JOIN jobs ON jobs.id=job_id "
            "WHERE items.status='queued' AND jobs.status!='cancelled' "
            "ORDER BY jobs.created_at, items.position LIMIT ?",
            (limit,),
        )

    async def update_item(self, item_id: str, **changes):
        # Terminal states are immutable: late progress can never undo cancellation.
        allowed = {
            "status",
            "downloaded_bytes",
            "total_bytes",
            "speed",
            "eta",
            "error",
            "file_id",
            "filename",
            "relative_path",
            "size",
            "title",
        }
        if not changes or changes.keys() - allowed:
            raise ValueError("Invalid item update")
        assignments = ", ".join(f"{key}=?" for key in changes)
        await self.write(
            f"UPDATE items SET {assignments} WHERE id=? AND status IN "
            "('queued','downloading','processing')",
            (*changes.values(), item_id),
        )

    async def retry_data(self, job: Job) -> tuple[Inspection, list[Entry]]:
        rows = await self.rows(
            "SELECT * FROM items WHERE job_id=? AND status IN ('failed','cancelled','interrupted') "
            "ORDER BY position",
            (job.id,),
        )
        entries = [Entry(**r) for r in rows]
        inspection = Inspection(
            id=uuid4().hex,
            title=job.title,
            source_url=job.source_url,
            kind=job.kind,
            entries=entries,
            limit=len(entries),
        )
        return inspection, entries

    async def export_debug_counts(self) -> dict:
        # Counts only, never persist raw yt-dlp metadata or authentication headers.
        return {
            r["status"]: r["count"]
            for r in await self.rows("SELECT status, count(*) AS count FROM items GROUP BY status")
        }
