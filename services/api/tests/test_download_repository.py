import sqlite3
from datetime import datetime, timezone

import pytest

from app.domain.models import DownloadEngine, DownloadJob, DownloadSourceType, DownloadStatus, ImpersonationMode
from app.infrastructure.sqlite import SqliteDownloadRepository

# The downloads table as it shipped before the engine column existed, used to
# prove the migration runs against a real historical database.
LEGACY_SCHEMA = """CREATE TABLE downloads (
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
    finished_at TEXT,
    capture_id TEXT
)"""


def build_job(job_id: str = 'job-1', engine: DownloadEngine = DownloadEngine.YT_DLP) -> DownloadJob:
    now = datetime.now(timezone.utc)
    return DownloadJob(
        id=job_id, url='https://example.com/video', filename=None, title=None, status=DownloadStatus.QUEUED,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.AUTO, referer=None, origin=None, user_agent=None,
        source_type=DownloadSourceType.STANDARD, created_at=now, started_at=None, finished_at=None,
        engine=engine,
    )


@pytest.mark.asyncio
async def test_engine_round_trips_through_add_and_get(tmp_path) -> None:
    repository = SqliteDownloadRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()

    await repository.add(build_job('job-1', DownloadEngine.GALLERY_DL))

    fetched = await repository.get('job-1')
    assert fetched is not None
    assert fetched.engine is DownloadEngine.GALLERY_DL


@pytest.mark.asyncio
async def test_engine_defaults_to_yt_dlp_when_unset(tmp_path) -> None:
    repository = SqliteDownloadRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()

    await repository.add(build_job('job-1'))

    fetched = await repository.get('job-1')
    assert fetched is not None
    assert fetched.engine is DownloadEngine.YT_DLP


@pytest.mark.asyncio
async def test_initialize_migrates_a_pre_engine_database_and_is_idempotent(tmp_path) -> None:
    database = tmp_path / 'pocketdl.db'
    with sqlite3.connect(database) as db:
        db.execute(LEGACY_SCHEMA)
        db.execute(
            '''INSERT INTO downloads (
                id, url, filename, title, status, progress, downloaded_bytes, total_bytes, retry_count,
                impersonation, source_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                'legacy-1', 'https://example.com/legacy.mp4', None, None, 'completed', 100.0, 1000, 1000, 0,
                'auto', 'standard', datetime.now(timezone.utc).isoformat(),
            ),
        )

    repository = SqliteDownloadRepository(database)
    await repository.initialize()
    await repository.initialize()

    legacy = await repository.get('legacy-1')
    assert legacy is not None
    assert legacy.engine is DownloadEngine.YT_DLP
