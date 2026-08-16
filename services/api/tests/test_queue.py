from datetime import datetime, timezone

from app.domain.models import DownloadJob, DownloadSourceType, DownloadStatus, ImpersonationMode


def test_download_job_initial_state() -> None:
    job = DownloadJob(
        id='test', url='https://example.com/video', filename=None, title=None, status=DownloadStatus.QUEUED,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.AUTO, referer=None, origin=None, user_agent=None, source_type=DownloadSourceType.STANDARD,
        created_at=datetime.now(timezone.utc), started_at=None, finished_at=None,
    )
    assert job.status is DownloadStatus.QUEUED
    assert job.progress == 0.0


def test_download_job_supports_custom_filename_and_failure_diagnostics() -> None:
    job = DownloadJob(
        id='test-failure',
        url='https://example.com/video',
        filename='my-video',
        title='Example Video',
        status=DownloadStatus.FAILED,
        progress=42.0,
        downloaded_bytes=123,
        total_bytes=456,
        speed_bytes=789.0,
        eta_seconds=10,
        output_path=None,
        error='ERROR: Example failure',
        error_details='ERROR: Example failure\nMore diagnostic output',
        error_category=None,
        exit_code=1,
        retry_count=0,
        impersonation=ImpersonationMode.AUTO,
        referer=None,
        origin=None,
        user_agent=None, source_type=DownloadSourceType.STANDARD,
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    assert job.filename == 'my-video'
    assert job.exit_code == 1
    assert 'More diagnostic output' in job.error_details
