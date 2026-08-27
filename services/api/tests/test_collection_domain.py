from datetime import datetime, timezone

from app.domain.collections import Collection, CollectionItem, InstagramContentType, Platform
from app.domain.models import DownloadEngine, DownloadJob, DownloadSourceType, DownloadStatus, ImpersonationMode


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_collection_construction() -> None:
    collection = Collection(id='c1', platform=Platform.INSTAGRAM, name='Trip photos', created_at=_now(), updated_at=_now())
    assert collection.platform is Platform.INSTAGRAM
    assert collection.name == 'Trip photos'


def test_collection_item_defaults_to_not_downloaded() -> None:
    item = CollectionItem(
        id='i1',
        collection_id='c1',
        source_url='https://instagram.com/p/abc123/',
        content_type=InstagramContentType.REEL.value,
        author_username='someone',
        caption=None,
        thumbnail_url=None,
        external_id='abc123',
        added_at=_now(),
    )
    assert item.downloaded_job_id is None
    assert item.content_type == 'reel'


def test_download_job_defaults_to_yt_dlp_engine() -> None:
    job = DownloadJob(
        id='test', url='https://example.com/video', filename=None, title=None, status=DownloadStatus.QUEUED,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.AUTO, referer=None, origin=None, user_agent=None,
        source_type=DownloadSourceType.STANDARD, created_at=_now(), started_at=None, finished_at=None,
    )
    assert job.engine is DownloadEngine.YT_DLP


def test_download_job_accepts_gallery_dl_engine() -> None:
    job = DownloadJob(
        id='test', url='https://instagram.com/reel/abc123/', filename=None, title=None, status=DownloadStatus.QUEUED,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.NONE, referer=None, origin=None, user_agent=None,
        source_type=DownloadSourceType.STANDARD, created_at=_now(), started_at=None, finished_at=None,
        engine=DownloadEngine.GALLERY_DL,
    )
    assert job.engine is DownloadEngine.GALLERY_DL
