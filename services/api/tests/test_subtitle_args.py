"""yt-dlp argument building for subtitles and preferred audio language
(product-polish Round 3)."""

from datetime import datetime, timezone

from app.application.downloads.strategy import DownloadAttempt
from app.core.config import get_settings
from app.domain.models import DownloadJob, DownloadSourceType, ImpersonationMode, MediaOptions, RequestContext, DownloadStatus
from app.infrastructure.ffmpeg import CapturedMediaService
from app.infrastructure.gallery_dl import GalleryDlService
from app.infrastructure.instaloader_service import InstaloaderService
from app.infrastructure.yt_dlp import YtDlpService


def _service() -> YtDlpService:
    settings = get_settings()
    captured = CapturedMediaService(settings.download_directory)
    return YtDlpService(settings, captured, GalleryDlService(settings, None), InstaloaderService(settings, None))


def _job() -> DownloadJob:
    now = datetime.now(timezone.utc)
    return DownloadJob(
        id='j', url='https://example.com/video', filename=None, title=None, status=DownloadStatus.RUNNING,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.NONE, referer=None, origin=None, user_agent=None,
        source_type=DownloadSourceType.STANDARD, created_at=now, started_at=now, finished_at=None,
    )


def _args(media_options: MediaOptions, preset: str = 'best') -> list[str]:
    service = _service()
    return service._build_args(
        _job(), preset=preset, format_id=None, concurrent_fragments=8, retries=10,
        use_aria2=False, request_context=RequestContext(impersonation=ImpersonationMode.NONE),
        attempt=DownloadAttempt(label='standard'), media_options=media_options,
    )


def test_no_subtitle_args_by_default() -> None:
    args = _args(MediaOptions())
    assert '--write-subs' not in args
    assert '-S' not in args


def test_subtitles_add_write_and_langs() -> None:
    args = _args(MediaOptions(subtitles=True, subtitle_langs='en,es'))
    assert '--write-subs' in args
    assert '--sub-langs' in args
    assert args[args.index('--sub-langs') + 1] == 'en,es'
    assert '--embed-subs' not in args


def test_embed_subtitles_adds_embed_flag() -> None:
    args = _args(MediaOptions(subtitles=True, embed_subtitles=True))
    assert '--embed-subs' in args


def test_subtitles_skipped_for_audio_only() -> None:
    args = _args(MediaOptions(subtitles=True), preset='audio')
    assert '--write-subs' not in args


def test_audio_language_adds_sort_preference() -> None:
    args = _args(MediaOptions(audio_language='pt-BR'))
    assert '-S' in args
    assert args[args.index('-S') + 1] == 'lang:pt-BR'


# --- Conflict strategy (product-polish Round 3) ---

def test_conflict_skip_and_overwrite_flags() -> None:
    from app.domain.models import ConflictStrategy
    skip = _args(MediaOptions(conflict_strategy=ConflictStrategy.SKIP))
    assert '--no-overwrites' in skip and '--force-overwrites' not in skip
    overwrite = _args(MediaOptions(conflict_strategy=ConflictStrategy.OVERWRITE))
    assert '--force-overwrites' in overwrite and '--no-overwrites' not in overwrite


def test_unique_stem_appends_counter(tmp_path) -> None:
    from app.core.filenames import unique_stem
    assert unique_stem(tmp_path, 'video') == 'video'
    (tmp_path / 'video.mp4').write_bytes(b'x')
    assert unique_stem(tmp_path, 'video') == 'video (1)'
    (tmp_path / 'video (1).mkv').write_bytes(b'x')
    assert unique_stem(tmp_path, 'video') == 'video (2)'


def test_unique_stem_handles_glob_metacharacters(tmp_path) -> None:
    from app.core.filenames import unique_stem
    (tmp_path / 'a[1].mp4').write_bytes(b'x')
    # The literal 'a[1]' collides; a different literal does not.
    assert unique_stem(tmp_path, 'a[1]') == 'a[1] (1)'
    assert unique_stem(tmp_path, 'a1') == 'a1'
