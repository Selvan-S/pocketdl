from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.session_store import save_session_cookie
from app.domain.collections import InstagramContentType
from app.domain.models import DownloadJob, DownloadSourceType, DownloadStatus, ImpersonationMode
from app.infrastructure.gallery_dl import GalleryDlService, InstagramAuthRequiredError


class _StubSettings:
    def __init__(self, database_path: Path, download_directory: Path) -> None:
        self.database_path = database_path
        self.download_directory = download_directory


def _make_service(tmp_path: Path) -> GalleryDlService:
    return GalleryDlService(_StubSettings(tmp_path / 'pocketdl.db', tmp_path / 'downloads'))  # type: ignore[arg-type]


def _make_job(job_id: str = 'job-1', filename: str | None = None, title: str | None = None) -> DownloadJob:
    now = datetime.now(timezone.utc)
    return DownloadJob(
        id=job_id, url='https://www.instagram.com/p/abc123/', filename=filename, title=title,
        status=DownloadStatus.QUEUED, progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None,
        eta_seconds=None, output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.NONE, referer=None, origin=None, user_agent=None,
        source_type=DownloadSourceType.STANDARD, created_at=now, started_at=None, finished_at=None,
    )


def test_content_type_url_uses_verified_gallery_dl_url_patterns(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    profile = 'https://www.instagram.com/someuser/'

    assert service._content_type_url(profile, InstagramContentType.POST) == 'https://www.instagram.com/someuser/posts/'
    assert service._content_type_url(profile, InstagramContentType.CAROUSEL) == 'https://www.instagram.com/someuser/posts/'
    assert service._content_type_url(profile, InstagramContentType.REEL) == 'https://www.instagram.com/someuser/reels/'
    assert service._content_type_url(profile, InstagramContentType.STORY) == 'https://www.instagram.com/stories/someuser/'
    assert service._content_type_url(profile, InstagramContentType.HIGHLIGHT) == 'https://www.instagram.com/someuser/highlights/'


def test_content_type_url_rejects_a_bare_domain(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    with pytest.raises(ValueError):
        service._content_type_url('https://www.instagram.com/', InstagramContentType.POST)


def test_cookie_args_empty_when_no_session_configured(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    assert service._cookie_args('instagram') == []


def test_cookie_args_points_at_the_stored_cookie_file(tmp_path: Path) -> None:
    database = tmp_path / 'pocketdl.db'
    save_session_cookie(database, 'instagram', '.instagram.com', 'sessionid=abc123')
    service = GalleryDlService(_StubSettings(database, tmp_path / 'downloads'))  # type: ignore[arg-type]

    args = service._cookie_args('instagram')

    assert args[0] == '--cookies'
    assert args[1].endswith('instagram_session_cookies.txt')


def test_classify_distinguishes_carousel_from_plain_post(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    assert service._classify({'typename': 'GraphSidecar'}, InstagramContentType.POST) == 'carousel'
    assert service._classify({'sidecar_shortcode': '123'}, InstagramContentType.POST) == 'carousel'
    assert service._classify({}, InstagramContentType.POST) == 'post'


def test_classify_passes_through_non_post_buckets(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    assert service._classify({}, InstagramContentType.REEL) == 'reel'
    assert service._classify({}, InstagramContentType.STORY) == 'story'
    assert service._classify({}, InstagramContentType.HIGHLIGHT) == 'highlight'


@pytest.mark.asyncio
async def test_list_profile_items_parses_url_messages_and_skips_directory_and_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(tmp_path)
    payload = [
        [2, {'category': 'instagram', 'subcategory': 'posts'}],
        [6, 'https://www.instagram.com/someuser/posts/', {}],
        [3, 'https://cdn.example/photo.jpg', {
            'post_url': 'https://www.instagram.com/p/abc123/',
            'username': 'someuser',
            'description': 'a caption',
            'post_shortcode': 'abc123',
            'display_url': 'https://cdn.example/thumb.jpg',
        }],
    ]

    async def fake_run_json(args: list[str]) -> tuple[int, list, str]:
        return 0, payload, ''

    monkeypatch.setattr(service, '_run_json', fake_run_json)

    items = await service.list_profile_items('https://www.instagram.com/someuser/', [InstagramContentType.POST])

    assert len(items) == 1
    assert items[0].source_url == 'https://www.instagram.com/p/abc123/'
    assert items[0].content_type == 'post'
    assert items[0].author_username == 'someuser'
    assert items[0].caption == 'a caption'
    assert items[0].external_id == 'abc123'
    assert items[0].thumbnail_url == 'https://cdn.example/thumb.jpg'


@pytest.mark.asyncio
async def test_list_profile_items_dedupes_post_and_carousel_into_one_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(tmp_path)
    calls: list[list[str]] = []

    async def fake_run_json(args: list[str]) -> tuple[int, list, str]:
        calls.append(args)
        return 0, [], ''

    monkeypatch.setattr(service, '_run_json', fake_run_json)

    await service.list_profile_items(
        'https://www.instagram.com/someuser/', [InstagramContentType.POST, InstagramContentType.CAROUSEL],
    )

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_list_profile_items_raises_auth_required_for_the_verified_unauthenticated_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression for the exact failure experimentally observed against a
    # real public Instagram profile with no session cookie configured (see
    # docs/docs_POCKETDL_ROADMAP.md Phase 5): gallery-dl's own error sentinel
    # entry, not a normal HTTP error, and not distinguishable from "wrong
    # username" without this classification.
    service = _make_service(tmp_path)
    payload = [[-1, {'error': 'NotFoundError', 'message': 'Requested user could not be found'}]]

    async def fake_run_json(args: list[str]) -> tuple[int, list, str]:
        return 0, payload, ''

    monkeypatch.setattr(service, '_run_json', fake_run_json)

    with pytest.raises(InstagramAuthRequiredError):
        await service.list_profile_items('https://www.instagram.com/someuser/', [InstagramContentType.POST])


@pytest.mark.asyncio
async def test_list_profile_items_raises_plain_error_for_unrelated_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(tmp_path)

    async def fake_run_json(args: list[str]) -> tuple[int, list, str]:
        return 1, [], 'gallery-dl exited with code 1'

    monkeypatch.setattr(service, '_run_json', fake_run_json)

    with pytest.raises(RuntimeError) as exc_info:
        await service.list_profile_items('https://www.instagram.com/someuser/', [InstagramContentType.POST])
    assert not isinstance(exc_info.value, InstagramAuthRequiredError)


def test_build_download_args_organizes_by_username_and_content_type_folder(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    job = _make_job(title='My Reel')

    args = service._build_download_args(job, username='someuser', content_type='reel')

    assert '-D' in args
    directory = args[args.index('-D') + 1]
    assert directory == str(tmp_path / 'downloads' / 'Instagram' / 'someuser' / 'Reels')
    assert '-f' in args
    assert args[args.index('-f') + 1] == 'My Reel.{extension}'
    assert args[-1] == job.url


def test_build_download_args_falls_back_to_posts_folder_for_unknown_content_type(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    job = _make_job(title='Untitled')

    args = service._build_download_args(job, username='someuser', content_type=None)

    directory = args[args.index('-D') + 1]
    assert directory == str(tmp_path / 'downloads' / 'Instagram' / 'someuser' / 'Posts')


def test_build_download_args_includes_cookie_flag_when_session_configured(tmp_path: Path) -> None:
    database = tmp_path / 'pocketdl.db'
    save_session_cookie(database, 'instagram', '.instagram.com', 'sessionid=abc123')
    service = GalleryDlService(_StubSettings(database, tmp_path / 'downloads'))  # type: ignore[arg-type]
    job = _make_job(title='My Post')

    args = service._build_download_args(job, username='someuser', content_type='post')

    assert '--cookies' in args
