from pathlib import Path

import pytest

from app.core.session_store import save_session_cookie
from app.domain.collections import InstagramContentType
from app.infrastructure.gallery_dl import GalleryDlService, InstagramAuthRequiredError


class _StubSettings:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path


def _make_service(tmp_path: Path) -> GalleryDlService:
    return GalleryDlService(_StubSettings(tmp_path / 'pocketdl.db'))  # type: ignore[arg-type]


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
    service = GalleryDlService(_StubSettings(database))  # type: ignore[arg-type]

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
