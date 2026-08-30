"""Generic (non-Instagram) playlists: plain URLs downloaded via yt-dlp into a
per-platform, per-playlist folder."""

from datetime import datetime, timezone

import pytest

from app.core.config import get_settings
from app.domain.collections import PLATFORM_FOLDERS, Platform
from app.domain.models import DownloadJob, DownloadSourceType, ImpersonationMode, DownloadStatus
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
        id='j', url='https://example.com/v', filename='clip', title=None, status=DownloadStatus.RUNNING,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.NONE, referer=None, origin=None, user_agent=None,
        source_type=DownloadSourceType.STANDARD, created_at=now, started_at=now, finished_at=None,
    )


def test_output_template_nests_platform_and_playlist_folder() -> None:
    service = _service()
    template = service._output_template(_job(), output_subdir='Web/My Playlist')
    normalized = template.replace('\\', '/')
    assert '/Web/My Playlist/clip.%(ext)s' in normalized


def test_output_subdir_segments_are_sanitized() -> None:
    service = _service()
    # A traversal attempt in the playlist name can't escape the download dir.
    template = service._output_template(_job(), output_subdir='Web/../../etc')
    normalized = template.replace('\\', '/')
    assert '..' not in normalized


def test_platform_folders_cover_both_platforms() -> None:
    assert PLATFORM_FOLDERS[Platform.INSTAGRAM] == 'Instagram'
    assert PLATFORM_FOLDERS[Platform.GENERIC] == 'Web'


@pytest.mark.asyncio
async def test_create_generic_collection_and_add_urls(api_client) -> None:
    created = await api_client.post('/api/collections', json={'platform': 'generic', 'name': 'Watch later'})
    assert created.status_code == 201, created.text
    assert created.json()['platform'] == 'generic'
    collection_id = created.json()['id']

    added = await api_client.post(f'/api/collections/{collection_id}/urls', json={
        'urls': ['https://example.com/a', 'https://example.com/b', 'https://example.com/a'],
    })
    body = added.json()
    # The duplicate is de-duped.
    assert body['added'] == 2

    listed = (await api_client.get(f'/api/collections/{collection_id}/items')).json()
    assert {item['source_url'] for item in listed} == {'https://example.com/a', 'https://example.com/b'}
    assert all(item['content_type'] == 'url' for item in listed)


@pytest.mark.asyncio
async def test_add_urls_rejects_non_http(api_client) -> None:
    created = await api_client.post('/api/collections', json={'platform': 'generic', 'name': 'X'})
    collection_id = created.json()['id']
    bad = await api_client.post(f'/api/collections/{collection_id}/urls', json={'urls': ['ftp://nope/x']})
    assert bad.status_code == 422
