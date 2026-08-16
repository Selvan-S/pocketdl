from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from ..domain.models import DownloadJob, DownloadSourceType, DownloadStatus, ImpersonationMode
from ..domain.ports import DownloadRepository
from ..application.downloads.errors import DownloadErrorCategory


class SqliteDownloadRepository(DownloadRepository):
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS downloads (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    filename TEXT,
                    title TEXT,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL,
                    downloaded_bytes INTEGER NOT NULL,
                    total_bytes INTEGER,
                    speed_bytes REAL,
                    eta_seconds INTEGER,
                    output_path TEXT,
                    error TEXT,
                    error_details TEXT,
                    error_category TEXT,
                    exit_code INTEGER,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    impersonation TEXT NOT NULL DEFAULT 'auto',
                    referer TEXT,
                    origin TEXT,
                    user_agent TEXT,
                    source_type TEXT NOT NULL DEFAULT 'standard',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
            ''')
            await self._ensure_columns(db)
            await db.commit()

    @staticmethod
    async def _ensure_columns(db: aiosqlite.Connection) -> None:
        cursor = await db.execute('PRAGMA table_info(downloads)')
        columns = {row[1] for row in await cursor.fetchall()}
        migrations = {
            'filename': 'ALTER TABLE downloads ADD COLUMN filename TEXT',
            'error_details': 'ALTER TABLE downloads ADD COLUMN error_details TEXT',
            'error_category': 'ALTER TABLE downloads ADD COLUMN error_category TEXT',
            'exit_code': 'ALTER TABLE downloads ADD COLUMN exit_code INTEGER',
            'retry_count': 'ALTER TABLE downloads ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0',
            'impersonation': "ALTER TABLE downloads ADD COLUMN impersonation TEXT NOT NULL DEFAULT 'auto'",
            'referer': 'ALTER TABLE downloads ADD COLUMN referer TEXT',
            'origin': 'ALTER TABLE downloads ADD COLUMN origin TEXT',
            'user_agent': 'ALTER TABLE downloads ADD COLUMN user_agent TEXT',
            'source_type': "ALTER TABLE downloads ADD COLUMN source_type TEXT NOT NULL DEFAULT 'standard'",
        }
        for column, statement in migrations.items():
            if column not in columns:
                await db.execute(statement)

    @staticmethod
    def _row_to_job(row: aiosqlite.Row) -> DownloadJob:
        def parse(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        return DownloadJob(
            id=row['id'],
            url=row['url'],
            filename=row['filename'],
            title=row['title'],
            status=DownloadStatus(row['status']),
            progress=row['progress'],
            downloaded_bytes=row['downloaded_bytes'],
            total_bytes=row['total_bytes'],
            speed_bytes=row['speed_bytes'],
            eta_seconds=row['eta_seconds'],
            output_path=row['output_path'],
            error=row['error'],
            error_details=row['error_details'],
            error_category=DownloadErrorCategory(row['error_category']) if row['error_category'] else None,
            exit_code=row['exit_code'],
            retry_count=row['retry_count'] or 0,
            impersonation=ImpersonationMode(row['impersonation'] or 'auto'),
            referer=row['referer'],
            origin=row['origin'],
            user_agent=row['user_agent'],
            source_type=DownloadSourceType(row['source_type'] or 'standard'),
            created_at=parse(row['created_at']) or datetime.now(timezone.utc),
            started_at=parse(row['started_at']),
            finished_at=parse(row['finished_at']),
        )

    async def add(self, job: DownloadJob) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                '''INSERT INTO downloads (
                    id, url, filename, title, status, progress, downloaded_bytes, total_bytes,
                    speed_bytes, eta_seconds, output_path, error, error_details, error_category, exit_code, retry_count,
                    impersonation, referer, origin, user_agent, source_type, created_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    job.id, job.url, job.filename, job.title, job.status.value, job.progress, job.downloaded_bytes,
                    job.total_bytes, job.speed_bytes, job.eta_seconds, job.output_path, job.error,
                    job.error_details, job.error_category.value if job.error_category else None, job.exit_code, job.retry_count,
                    job.impersonation.value, job.referer, job.origin, job.user_agent, job.source_type.value,
                    job.created_at.isoformat(), job.started_at.isoformat() if job.started_at else None,
                    job.finished_at.isoformat() if job.finished_at else None,
                ),
            )
            await db.commit()

    async def get(self, job_id: str) -> DownloadJob | None:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM downloads WHERE id = ?', (job_id,))
            row = await cursor.fetchone()
            return self._row_to_job(row) if row else None

    async def list(self) -> list[DownloadJob]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM downloads ORDER BY created_at DESC')
            return [self._row_to_job(row) for row in await cursor.fetchall()]

    async def update(self, job: DownloadJob) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('''
                UPDATE downloads SET filename=?, title=?, status=?, progress=?, downloaded_bytes=?, total_bytes=?,
                speed_bytes=?, eta_seconds=?, output_path=?, error=?, error_details=?, error_category=?, exit_code=?, retry_count=?,
                impersonation=?, referer=?, origin=?, user_agent=?, source_type=?, started_at=?, finished_at=? WHERE id=?
            ''', (
                job.filename, job.title, job.status.value, job.progress, job.downloaded_bytes, job.total_bytes,
                job.speed_bytes, job.eta_seconds, job.output_path, job.error, job.error_details,
                job.error_category.value if job.error_category else None, job.exit_code, job.retry_count,
                job.impersonation.value, job.referer, job.origin, job.user_agent, job.source_type.value,
                job.started_at.isoformat() if job.started_at else None,
                job.finished_at.isoformat() if job.finished_at else None, job.id,
            ))
            await db.commit()

    async def delete(self, job_id: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('DELETE FROM downloads WHERE id = ?', (job_id,))
            await db.commit()
