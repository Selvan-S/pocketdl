"""Filename templates and title cleanup (product-polish Round 4)."""

from datetime import datetime, timezone

import pytest

from app.application.downloads.strategy import DownloadAttempt
from app.core.config import get_settings
from app.domain.models import DownloadJob, DownloadSourceType, ImpersonationMode, MediaOptions, RequestContext, DownloadStatus
from app.infrastructure.ffmpeg import CapturedMediaService
from app.infrastructure.gallery_dl import GalleryDlService
from app.infrastructure.instaloader_service import InstaloaderService
from app.infrastructure.yt_dlp import YtDlpService
from app.core.settings_store import load_setting, save_setting


def _service() -> YtDlpService:
    settings = get_settings()
    captured = CapturedMediaService(settings.download_directory)
    return YtDlpService(settings, captured, GalleryDlService(settings, None), InstaloaderService(settings, None))


def _job(filename=None) -> DownloadJob:
    now = datetime.now(timezone.utc)
    return DownloadJob(
        id='j', url='https://example.com/v', filename=filename, title=None, status=DownloadStatus.RUNNING,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.NONE, referer=None, origin=None, user_agent=None,
        source_type=DownloadSourceType.STANDARD, created_at=now, started_at=now, finished_at=None,
    )


def _args(service) -> list[str]:
    return service._build_args(
        _job(), preset='best', format_id=None, concurrent_fragments=8, retries=10, use_aria2=False,
        request_context=RequestContext(impersonation=ImpersonationMode.NONE),
        attempt=DownloadAttempt(label='standard'), media_options=MediaOptions(),
    )


def test_default_template_uses_title() -> None:
    service = _service()
    service.settings.filename_template = 'title'
    template = service._output_template(_job())
    assert template.endswith('%(title)s.%(ext)s')


def test_uploader_title_template() -> None:
    service = _service()
    service.settings.filename_template = 'uploader-title'
    template = service._output_template(_job())
    assert template.endswith('%(uploader)s - %(title)s.%(ext)s')


def test_explicit_filename_ignores_template() -> None:
    service = _service()
    service.settings.filename_template = 'uploader-title'
    template = service._output_template(_job(filename='my clip'))
    assert template.endswith('my clip.%(ext)s')


def test_clean_titles_adds_replace_in_metadata() -> None:
    service = _service()
    service.settings.clean_titles = True
    args = _args(service)
    assert '--replace-in-metadata' in args


def test_clean_titles_off_omits_replace() -> None:
    service = _service()
    service.settings.clean_titles = False
    args = _args(service)
    assert '--replace-in-metadata' not in args


def test_settings_store_merges_keys(tmp_path) -> None:
    db = tmp_path / 'pocketdl.db'
    save_setting(db, 'download_directory', '/x')
    save_setting(db, 'filename_template', 'title-id')
    # Writing one key must not drop the other.
    assert load_setting(db, 'download_directory') == '/x'
    assert load_setting(db, 'filename_template') == 'title-id'


@pytest.mark.asyncio
async def test_settings_endpoint_round_trips_naming(api_client) -> None:
    response = await api_client.put('/api/settings', json={
        'download_directory': str(api_client.app_settings.download_directory),
        'filename_template': 'date-title', 'clean_titles': False,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['filename_template'] == 'date-title'
    assert body['clean_titles'] is False
    # And it persisted / is readable back.
    again = (await api_client.get('/api/settings')).json()
    assert again['filename_template'] == 'date-title'
    assert again['clean_titles'] is False
