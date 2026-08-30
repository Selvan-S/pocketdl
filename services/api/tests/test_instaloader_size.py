"""Instaloader downloads report the written file's size instead of 0 B
(captures round follow-up)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.domain.models import DownloadEngine, DownloadJob, DownloadSourceType, ImpersonationMode, RequestContext, DownloadStatus
from app.infrastructure.instaloader_service import DownloadResult, InstaloaderService


def _job() -> DownloadJob:
    now = datetime.now(timezone.utc)
    return DownloadJob(
        id='j', url='https://www.instagram.com/reel/abc/', filename=None, title='reel', status=DownloadStatus.QUEUED,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.NONE, referer=None, origin=None, user_agent=None,
        source_type=DownloadSourceType.STANDARD, created_at=now, started_at=None, finished_at=None,
        engine=DownloadEngine.INSTALOADER,
    )


@pytest.mark.asyncio
async def test_completed_instaloader_download_reports_file_size(tmp_path, monkeypatch) -> None:
    media = tmp_path / 'reel.mp4'
    media.write_bytes(b'x' * 4096)

    service = InstaloaderService(get_settings(), None)

    def fake_sync(job, username, content_type):
        return DownloadResult(output_path=str(media))

    monkeypatch.setattr(service, '_download_sync', fake_sync)

    job = _job()
    await service.download(job, context=RequestContext(), retries=1, on_progress=_noop)

    assert job.status is DownloadStatus.COMPLETED
    assert job.downloaded_bytes == 4096
    assert job.total_bytes == 4096


async def _noop(job) -> None:
    return None
