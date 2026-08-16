from dataclasses import dataclass

from ...domain.errors import DownloadErrorCategory
from ...domain.models import DownloadJob, ImpersonationMode, RequestContext


@dataclass(frozen=True, slots=True)
class DownloadAttempt:
    label: str
    impersonate: str | None = None
    use_ffmpeg_hls: bool = False


def looks_like_hls(job: DownloadJob, output: str) -> bool:
    text = f'{job.url}\n{output}'.lower()
    return '.m3u8' in text or 'hls' in text


def should_retry_with_impersonation(job: DownloadJob, output: str, context: RequestContext, error_category: DownloadErrorCategory) -> bool:
    if context.impersonation is not ImpersonationMode.AUTO:
        return False
    return error_category is DownloadErrorCategory.HTTP_403 and looks_like_hls(job, output)


def should_retry_with_ffmpeg(output: str) -> bool:
    return 'live hls streams are not supported by the native downloader' in output.lower()


def initial_attempt(context: RequestContext) -> DownloadAttempt:
    if context.impersonation is ImpersonationMode.CHROME:
        return DownloadAttempt(label='impersonate:chrome', impersonate='chrome')
    return DownloadAttempt(label='standard')


def impersonated_attempt() -> DownloadAttempt:
    return DownloadAttempt(label='impersonate:chrome', impersonate='chrome')


def ffmpeg_hls_attempt(use_chrome: bool) -> DownloadAttempt:
    if use_chrome:
        return DownloadAttempt(label='impersonate:chrome+ffmpeg-hls', impersonate='chrome', use_ffmpeg_hls=True)
    return DownloadAttempt(label='standard+ffmpeg-hls', use_ffmpeg_hls=True)
