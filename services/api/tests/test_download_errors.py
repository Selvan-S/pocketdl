from app.application.downloads.errors import classify_download_error
from app.application.downloads.strategy import (
    DownloadAttempt,
    should_retry_with_ffmpeg,
    should_retry_with_impersonation,
    should_retry_without_cert_verification,
    without_cert_verification,
)
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


def test_classifies_gallery_dl_login_redirect() -> None:
    # Observed live from a real gallery-dl run against an Instagram post
    # without a valid session cookie: '[instagram][error] HTTP redirect to
    # login page (https://www.instagram.com/accounts/login/)'.
    assert classify_download_error('[instagram][error] HTTP redirect to login page (...)') is DownloadErrorCategory.AUTHENTICATION_REQUIRED


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


def test_classifies_ssl_certificate_verify_failed() -> None:
    output = (
        "UNKNOWN: ERROR: [generic] video: Unable to download webpage: "
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
        "unable to get local issuer certificate (_ssl.c:1032)"
    )
    assert classify_download_error(output) is DownloadErrorCategory.SSL_CERTIFICATE_ERROR


def test_retries_without_cert_verification_only_once_per_attempt() -> None:
    standard = DownloadAttempt(label='standard')
    assert should_retry_without_cert_verification(DownloadErrorCategory.SSL_CERTIFICATE_ERROR, standard)
    assert not should_retry_without_cert_verification(DownloadErrorCategory.HTTP_403, standard)

    retried = without_cert_verification(standard)
    assert retried.no_check_certificate is True
    assert retried.label == 'standard+no-check-certificate'
    # Already retried once for this failure -- don't loop forever on a
    # site whose SSL is broken for reasons other than a missing chain.
    assert not should_retry_without_cert_verification(DownloadErrorCategory.SSL_CERTIFICATE_ERROR, retried)


def test_without_cert_verification_preserves_impersonation_and_ffmpeg_hls() -> None:
    attempt = DownloadAttempt(label='impersonate:chrome+ffmpeg-hls', impersonate='chrome', use_ffmpeg_hls=True)
    retried = without_cert_verification(attempt)
    assert retried.impersonate == 'chrome'
    assert retried.use_ffmpeg_hls is True
    assert retried.no_check_certificate is True
