from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import instaloader
import pytest

from app.core.session_store import save_session_cookie
from app.domain.collections import InstagramAuthRequiredError, InstagramContentType
from app.infrastructure.instaloader_service import InstaloaderService


class _StubSettings:
    def __init__(self, database_path: Path, download_directory: Path) -> None:
        self.database_path = database_path
        self.download_directory = download_directory


def _make_service(tmp_path: Path) -> InstaloaderService:
    return InstaloaderService(_StubSettings(tmp_path / 'pocketdl.db', tmp_path / 'downloads'))  # type: ignore[arg-type]


def _fake_post(shortcode: str, date: datetime, typename: str = 'GraphImage', mediacount: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        shortcode=shortcode, date_utc=date, typename=typename, mediacount=mediacount,
        owner_username='someuser', caption='a caption', url='https://cdn.example/thumb.jpg',
    )


class _FakeProfile:
    """Stand-in for instaloader.Profile that raises from get_posts()/
    get_reels() without needing a real network-backed context -- avoids
    monkeypatching SimpleNamespace itself, which would leak across tests
    since it's a shared builtin type."""

    def __init__(self, userid: int = 1, username: str = 'someuser', posts_error: Exception | None = None) -> None:
        self.userid = userid
        self.username = username
        self._posts_error = posts_error
        self.get_posts_calls = 0

    def get_posts(self):
        self.get_posts_calls += 1
        if self._posts_error:
            raise self._posts_error
        return []

    def get_reels(self):
        return self.get_posts()


def test_profile_username_extracts_from_a_profile_url(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    assert service._profile_username('https://www.instagram.com/someuser/') == 'someuser'


def test_profile_username_rejects_a_bare_domain(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    with pytest.raises(ValueError):
        service._profile_username('https://www.instagram.com/')


def test_classify_treats_sidecar_typename_as_carousel(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    post = _fake_post('abc', datetime.now(timezone.utc), typename='GraphSidecar')
    assert service._classify(post, InstagramContentType.POST) == 'carousel'


def test_classify_treats_multi_media_count_as_carousel(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    post = _fake_post('abc', datetime.now(timezone.utc), typename='GraphImage', mediacount=3)
    assert service._classify(post, InstagramContentType.POST) == 'carousel'


def test_classify_plain_post_stays_post(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    post = _fake_post('abc', datetime.now(timezone.utc))
    assert service._classify(post, InstagramContentType.POST) == 'post'


def test_classify_passes_through_non_post_buckets(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    post = _fake_post('abc', datetime.now(timezone.utc))
    assert service._classify(post, InstagramContentType.REEL) == 'reel'
    assert service._classify(post, InstagramContentType.STORY) == 'story'
    assert service._classify(post, InstagramContentType.HIGHLIGHT) == 'highlight'


def test_collect_posts_stops_early_once_older_than_since(tmp_path: Path) -> None:
    posts = [
        _fake_post('newest', datetime(2026, 3, 20, tzinfo=timezone.utc)),
        _fake_post('middle', datetime(2026, 3, 10, tzinfo=timezone.utc)),
        _fake_post('oldest', datetime(2026, 2, 1, tzinfo=timezone.utc)),
    ]
    since = datetime(2026, 3, 5, tzinfo=timezone.utc)

    previews = InstaloaderService._collect_posts(posts, InstagramContentType.POST, since, None)

    assert [p.external_id for p in previews] == ['newest', 'middle']


def test_collect_posts_skips_newer_than_until(tmp_path: Path) -> None:
    posts = [
        _fake_post('too_new', datetime(2026, 3, 20, tzinfo=timezone.utc)),
        _fake_post('in_range', datetime(2026, 3, 10, tzinfo=timezone.utc)),
    ]
    until = datetime(2026, 3, 15, tzinfo=timezone.utc)

    previews = InstaloaderService._collect_posts(posts, InstagramContentType.POST, None, until)

    assert [p.external_id for p in previews] == ['in_range']


def test_collect_posts_with_no_range_returns_everything(tmp_path: Path) -> None:
    posts = [_fake_post('a', datetime(2026, 1, 1, tzinfo=timezone.utc)), _fake_post('b', datetime(2026, 2, 1, tzinfo=timezone.utc))]
    previews = InstaloaderService._collect_posts(posts, InstagramContentType.POST, None, None)
    assert len(previews) == 2


def test_post_to_preview_maps_fields_correctly(tmp_path: Path) -> None:
    post = _fake_post('abc123', datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc))
    preview = InstaloaderService._post_to_preview(post, InstagramContentType.POST)
    assert preview.source_url == 'https://www.instagram.com/p/abc123/'
    assert preview.external_id == 'abc123'
    assert preview.author_username == 'someuser'
    assert preview.posted_at == datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)


def test_target_directory_maps_content_type_to_folder_and_creates_it(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    directory = service._target_directory('someuser', 'reel')
    assert directory == tmp_path / 'downloads' / 'Instagram' / 'someuser' / 'Reels'
    assert directory.is_dir()


def test_target_directory_falls_back_to_posts_and_unknown_username(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    directory = service._target_directory(None, None)
    assert directory == tmp_path / 'downloads' / 'Instagram' / 'unknown' / 'Posts'


@pytest.mark.asyncio
async def test_list_profile_items_maps_profile_not_exists_to_value_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(tmp_path)

    def fake_from_username(context, username):
        raise instaloader.ProfileNotExistsException('nope')

    monkeypatch.setattr(instaloader.Profile, 'from_username', staticmethod(fake_from_username))

    with pytest.raises(ValueError):
        await service.list_profile_items('https://www.instagram.com/someuser/', [InstagramContentType.POST])


@pytest.mark.asyncio
async def test_list_profile_items_maps_login_required_to_auth_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(tmp_path)

    def fake_from_username(context, username):
        raise instaloader.LoginRequiredException('nope')

    monkeypatch.setattr(instaloader.Profile, 'from_username', staticmethod(fake_from_username))

    with pytest.raises(InstagramAuthRequiredError):
        await service.list_profile_items('https://www.instagram.com/someuser/', [InstagramContentType.POST])


@pytest.mark.asyncio
async def test_list_profile_items_maps_private_profile_not_followed_to_auth_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(tmp_path)
    fake_profile = _FakeProfile(posts_error=instaloader.PrivateProfileNotFollowedException('nope'))
    monkeypatch.setattr(instaloader.Profile, 'from_username', staticmethod(lambda context, username: fake_profile))

    with pytest.raises(InstagramAuthRequiredError):
        await service.list_profile_items('https://www.instagram.com/someuser/', [InstagramContentType.POST])


@pytest.mark.asyncio
async def test_list_profile_items_maps_rate_limit_to_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(tmp_path)
    fake_profile = _FakeProfile(posts_error=instaloader.TooManyRequestsException('slow down'))
    monkeypatch.setattr(instaloader.Profile, 'from_username', staticmethod(lambda context, username: fake_profile))

    with pytest.raises(RuntimeError) as exc_info:
        await service.list_profile_items('https://www.instagram.com/someuser/', [InstagramContentType.POST])
    assert not isinstance(exc_info.value, InstagramAuthRequiredError)


@pytest.mark.asyncio
async def test_list_profile_items_dedupes_post_and_carousel_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(tmp_path)
    fake_profile = _FakeProfile()
    monkeypatch.setattr(instaloader.Profile, 'from_username', staticmethod(lambda context, username: fake_profile))

    await service.list_profile_items(
        'https://www.instagram.com/someuser/', [InstagramContentType.POST, InstagramContentType.CAROUSEL],
    )

    assert fake_profile.get_posts_calls == 1


@pytest.mark.asyncio
async def test_test_session_returns_none_when_no_cookie_configured(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    assert await service.test_session() is None


@pytest.mark.asyncio
async def test_test_session_returns_username_when_cookie_authenticates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / 'pocketdl.db'
    save_session_cookie(database, 'instagram', '.instagram.com', 'sessionid=abc123')
    service = InstaloaderService(_StubSettings(database, tmp_path / 'downloads'))  # type: ignore[arg-type]

    monkeypatch.setattr(instaloader.InstaloaderContext, 'test_login', lambda self: 'someuser')

    assert await service.test_session() == 'someuser'


@pytest.mark.asyncio
async def test_test_session_returns_none_when_cookie_does_not_authenticate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / 'pocketdl.db'
    save_session_cookie(database, 'instagram', '.instagram.com', 'sessionid=bad')
    service = InstaloaderService(_StubSettings(database, tmp_path / 'downloads'))  # type: ignore[arg-type]

    monkeypatch.setattr(instaloader.InstaloaderContext, 'test_login', lambda self: None)

    assert await service.test_session() is None
