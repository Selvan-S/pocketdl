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
async def test_collection_item_id_round_trips_through_add_and_get(tmp_path) -> None:
    repository = SqliteDownloadRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    job = build_job('job-1', DownloadEngine.GALLERY_DL)
    job.collection_item_id = 'item-1'

    await repository.add(job)

    fetched = await repository.get('job-1')
    assert fetched is not None
    assert fetched.collection_item_id == 'item-1'


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
    assert legacy.collection_item_id is None


# --- Round 4: bounded live snapshot + paged history ---

async def _seed_mixed(repository) -> None:
    """Two active jobs and five finished ones, with distinct created_at so
    ordering is deterministic."""
    base = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    from datetime import timedelta
    specs = [
        ('run-1', DownloadStatus.RUNNING), ('queue-1', DownloadStatus.QUEUED),
        ('done-1', DownloadStatus.COMPLETED), ('done-2', DownloadStatus.COMPLETED),
        ('fail-1', DownloadStatus.FAILED), ('cancel-1', DownloadStatus.CANCELLED),
        ('done-3', DownloadStatus.COMPLETED),
    ]
    for index, (job_id, status) in enumerate(specs):
        job = build_job(job_id)
        job.status = status
        job.created_at = base + timedelta(minutes=index)
        await repository.add(job)


@pytest.mark.asyncio
async def test_list_recent_keeps_all_active_and_caps_terminal(tmp_path) -> None:
    repository = SqliteDownloadRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await _seed_mixed(repository)

    recent = await repository.list_recent(terminal_limit=2)
    ids = [job.id for job in recent]

    # Both active jobs are present regardless of the terminal cap.
    assert 'run-1' in ids and 'queue-1' in ids
    # Only the 2 newest terminal jobs (done-3 newest, then cancel-1).
    terminal_ids = [i for i in ids if i not in {'run-1', 'queue-1'}]
    assert terminal_ids == ['done-3', 'cancel-1']
    # Newest-first overall.
    assert recent == sorted(recent, key=lambda job: job.created_at, reverse=True)


@pytest.mark.asyncio
async def test_list_terminal_page_pages_history_newest_first(tmp_path) -> None:
    repository = SqliteDownloadRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await _seed_mixed(repository)

    page1 = await repository.list_terminal_page(limit=2, offset=0)
    page2 = await repository.list_terminal_page(limit=2, offset=2)

    assert [job.id for job in page1] == ['done-3', 'cancel-1']
    assert [job.id for job in page2] == ['fail-1', 'done-2']
    # Active jobs never appear in history.
    all_history = await repository.list_terminal_page(limit=100, offset=0)
    assert 'run-1' not in {job.id for job in all_history}
