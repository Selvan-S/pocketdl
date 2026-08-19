import re
from dataclasses import dataclass

from ...domain.errors import DownloadErrorCategory
from ...domain.models import DownloadJob, ImpersonationMode, RequestContext

_FORMAT_ID_RE = re.compile(r'^[A-Za-z0-9_.+-]{1,100}$')


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


def format_args(preset: str, format_id: str | None = None) -> list[str]:
    """yt-dlp -f/merge args for a download. A specific format_id from
    /api/analyze's format list overrides the coarse preset -- see
    AnalyzeResult.tsx. The API layer already validates format_id's shape;
    re-checking here means a malformed value degrades to the preset instead
    of handing yt-dlp a broken -f argument. Only video formats are
    selectable this way -- an audio-only format_id would double up with the
    +bestaudio merge below, so audio-only downloads keep going through
    preset='audio'.
    """
    if format_id and _FORMAT_ID_RE.match(format_id):
        return ['-f', f'{format_id}+bestaudio/best', '--merge-output-format', 'mp4']
    if preset == 'audio':
        return ['-f', 'ba/b', '-x', '--audio-format', 'mp3']
    if preset == '1080p':
        return ['-f', 'bv*[height<=1080]+ba/b', '--merge-output-format', 'mp4']
    if preset == '720p':
        return ['-f', 'bv*[height<=720]+ba/b', '--merge-output-format', 'mp4']
    if preset == '480p':
        return ['-f', 'bv*[height<=480]+ba/b', '--merge-output-format', 'mp4']
    return ['-f', 'bv*+ba/b', '--merge-output-format', 'mp4']
