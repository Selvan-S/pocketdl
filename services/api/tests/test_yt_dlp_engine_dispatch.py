from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.domain.models import DownloadEngine, DownloadJob, DownloadSourceType, DownloadStatus, ImpersonationMode, RequestContext
from app.infrastructure.yt_dlp import YtDlpService


class _StubSettings:
    download_directory = Path('/downloads')


class _StubCapturedMedia:
    async def download(self, job, **kwargs):
        raise AssertionError('captured_media.download should not be called for a gallery_dl-engine job')


class _RecordingGalleryDl:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def download(self, job, *, context, retries, on_progress, collection_item_id=None):
        self.calls.append({'job': job, 'collection_item_id': collection_item_id})
        job.status = DownloadStatus.COMPLETED
        return job


def _make_job(engine: DownloadEngine, collection_item_id: str | None = None) -> DownloadJob:
    now = datetime.now(timezone.utc)
    return DownloadJob(
        id='test', url='https://www.instagram.com/p/abc123/', filename=None, title=None, status=DownloadStatus.QUEUED,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.NONE, referer=None, origin=None, user_agent=None,
        source_type=DownloadSourceType.STANDARD, created_at=now, started_at=None, finished_at=None,
        engine=engine, collection_item_id=collection_item_id,
    )


@pytest.mark.asyncio
async def test_gallery_dl_engine_job_dispatches_to_gallery_dl_service() -> None:
    gallery_dl = _RecordingGalleryDl()
    service = YtDlpService(_StubSettings(), _StubCapturedMedia(), gallery_dl)  # type: ignore[arg-type]
    job = _make_job(DownloadEngine.GALLERY_DL, collection_item_id='item-1')

    async def on_progress(_job):
        pass

    result = await service.download(
        job, preset='best', concurrent_fragments=1, retries=1, use_aria2=False,
        request_context=RequestContext(), source_type=DownloadSourceType.STANDARD,
        capture_id=None, on_progress=on_progress, collection_item_id='item-1',
    )

    assert result.status is DownloadStatus.COMPLETED
    assert len(gallery_dl.calls) == 1
    assert gallery_dl.calls[0]['collection_item_id'] == 'item-1'
