"""Paged download history endpoint (product-polish Round 4). The SSE snapshot
carries only active + recent jobs; older finished ones are reached here."""

from datetime import datetime, timezone

import pytest

from app.domain.models import DownloadJob, DownloadSourceType, DownloadStatus, ImpersonationMode
from app.infrastructure.sqlite import SqliteDownloadRepository


def _job(job_id: str, status: DownloadStatus, minute: int) -> DownloadJob:
    now = datetime(2026, 8, 1, 12, minute, tzinfo=timezone.utc)
    return DownloadJob(
        id=job_id, url='https://example.com/v', filename=None, title=None, status=status,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.AUTO, referer=None, origin=None, user_agent=None,
        source_type=DownloadSourceType.STANDARD, created_at=now, started_at=None, finished_at=None,
    )


@pytest.mark.asyncio
async def test_history_endpoint_pages_newest_first(api_client) -> None:
    repository = SqliteDownloadRepository(api_client.app_settings.database_path)
    for index in range(5):
        await repository.add(_job(f'done-{index}', DownloadStatus.COMPLETED, index))
    # An active job must never leak into history.
    await repository.add(_job('running', DownloadStatus.RUNNING, 9))

    first = (await api_client.get('/api/downloads/history?limit=2&offset=0')).json()
    assert [item['id'] for item in first['items']] == ['done-4', 'done-3']
    assert first['has_more'] is True

    last = (await api_client.get('/api/downloads/history?limit=2&offset=4')).json()
    assert [item['id'] for item in last['items']] == ['done-0']
    assert last['has_more'] is False

    everything = (await api_client.get('/api/downloads/history?limit=100')).json()
    assert 'running' not in {item['id'] for item in everything['items']}


@pytest.mark.asyncio
async def test_clear_completed_removes_only_completed(api_client) -> None:
    repository = SqliteDownloadRepository(api_client.app_settings.database_path)
    await repository.add(_job('done-1', DownloadStatus.COMPLETED, 1))
    await repository.add(_job('done-2', DownloadStatus.COMPLETED, 2))
    await repository.add(_job('failed-1', DownloadStatus.FAILED, 3))
    await repository.add(_job('running-1', DownloadStatus.RUNNING, 4))

    result = (await api_client.post('/api/downloads/clear-completed')).json()
    assert result['removed'] == 2

    remaining = {item['id'] for item in (await api_client.get('/api/downloads')).json()}
    assert remaining == {'failed-1', 'running-1'}
