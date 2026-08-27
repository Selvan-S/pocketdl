from datetime import datetime, timezone
from pathlib import Path

from app.application.downloads.strategy import DownloadAttempt
from app.domain.models import DownloadJob, DownloadSourceType, ImpersonationMode, DownloadStatus, RequestContext
from app.infrastructure.yt_dlp import YtDlpService


class _StubSettings:
    download_directory = Path('/downloads')


class _StubCapturedMedia:
    pass


class _StubGalleryDl:
    pass


def _make_job() -> DownloadJob:
    now = datetime.now(timezone.utc)
    return DownloadJob(
        id='test', url='https://cdn.example/video.mp4', filename=None, title=None, status=DownloadStatus.RUNNING,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.AUTO, referer=None, origin=None, user_agent=None,
        source_type=DownloadSourceType.STANDARD, created_at=now, started_at=now, finished_at=None,
    )


def test_build_args_adds_no_check_certificate_flag_for_that_attempt() -> None:
    # Regression: some sites serve an incomplete certificate chain that
    # Python's ssl module rejects even though browsers tolerate it via AIA
    # chasing. The cert-verify retry attempt must actually pass
    # --no-check-certificate through to yt-dlp.
    service = YtDlpService(_StubSettings(), _StubCapturedMedia(), _StubGalleryDl())  # type: ignore[arg-type]
    job = _make_job()
    attempt = DownloadAttempt(label='standard+no-check-certificate', no_check_certificate=True)

    args = service._build_args(
        job, preset='best', format_id=None, concurrent_fragments=4, retries=3,
        use_aria2=False, request_context=RequestContext(), attempt=attempt,
    )

    assert '--no-check-certificate' in args


def test_build_args_omits_no_check_certificate_by_default() -> None:
    service = YtDlpService(_StubSettings(), _StubCapturedMedia(), _StubGalleryDl())  # type: ignore[arg-type]
    job = _make_job()
    attempt = DownloadAttempt(label='standard')

    args = service._build_args(
        job, preset='best', format_id=None, concurrent_fragments=4, retries=3,
        use_aria2=False, request_context=RequestContext(), attempt=attempt,
    )

    assert '--no-check-certificate' not in args
