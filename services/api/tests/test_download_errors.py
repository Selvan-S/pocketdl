from app.application.downloads.errors import classify_download_error
from app.application.downloads.strategy import should_retry_with_ffmpeg, should_retry_with_impersonation
from app.domain.errors import DownloadErrorCategory
from app.domain.models import DownloadJob, DownloadSourceType, ImpersonationMode, RequestContext
from app.domain.models import DownloadStatus
from datetime import datetime, timezone


def make_job(url: str) -> DownloadJob:
    now = datetime.now(timezone.utc)
    return DownloadJob(
        id='test', url=url, filename=None, title=None, status=DownloadStatus.RUNNING,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.AUTO, referer=None, origin=None, user_agent=None, source_type=DownloadSourceType.STANDARD,
        created_at=now, started_at=now, finished_at=None,
    )


def test_classifies_http_403() -> None:
    assert classify_download_error('ERROR: Unable to download webpage: HTTP Error 403: Forbidden') is DownloadErrorCategory.HTTP_403


def test_classifies_unsupported_url() -> None:
    assert classify_download_error('ERROR: Unsupported URL') is DownloadErrorCategory.UNSUPPORTED_URL


def test_auto_impersonation_retry_only_for_hls_403() -> None:
    context = RequestContext(impersonation=ImpersonationMode.AUTO)
    assert should_retry_with_impersonation(
        make_job('https://cdn.example/video/master.m3u8'),
        'HTTP Error 403: Forbidden', context, DownloadErrorCategory.HTTP_403,
    )
    assert not should_retry_with_impersonation(
        make_job('https://cdn.example/video.mp4'),
        'HTTP Error 403: Forbidden', context, DownloadErrorCategory.HTTP_403,
    )


def test_chrome_mode_does_not_repeat_impersonation_retry() -> None:
    context = RequestContext(impersonation=ImpersonationMode.CHROME)
    assert not should_retry_with_impersonation(
        make_job('https://cdn.example/video/master.m3u8'),
        'HTTP Error 403: Forbidden', context, DownloadErrorCategory.HTTP_403,
    )


def test_detects_live_hls_fallback() -> None:
    assert should_retry_with_ffmpeg('WARNING: Live HLS streams are not supported by the native downloader.')
