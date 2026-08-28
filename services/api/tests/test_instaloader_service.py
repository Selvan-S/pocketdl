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


def test_collect_posts_with_no_range_returns_everything_under_the_cap(tmp_path: Path) -> None:
    posts = [_fake_post('a', datetime(2026, 1, 1, tzinfo=timezone.utc)), _fake_post('b', datetime(2026, 2, 1, tzinfo=timezone.utc))]
    previews = InstaloaderService._collect_posts(posts, InstagramContentType.POST, None, None)
    assert len(previews) == 2


def test_collect_posts_caps_item_count_when_no_since_bound_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: live-verified as the dominant cause of a preview call
    # taking 5+ minutes -- with no `since` to stop at naturally,
    # instaloader's get_reels()/get_posts() would otherwise page through an
    # active profile's entire history, one HTTP request per page.
    import app.infrastructure.instaloader_service as instaloader_service_module
    monkeypatch.setattr(instaloader_service_module, '_MAX_ITEMS_WITHOUT_DATE_RANGE', 3)

    def infinite_posts():
        index = 0
        while True:
            yield _fake_post(f'post-{index}', datetime(2026, 1, 1, tzinfo=timezone.utc))
            index += 1

    previews = InstaloaderService._collect_posts(infinite_posts(), InstagramContentType.POST, None, None)

    assert len(previews) == 3


def test_collect_posts_does_not_cap_when_since_is_given(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.infrastructure.instaloader_service as instaloader_service_module
    monkeypatch.setattr(instaloader_service_module, '_MAX_ITEMS_WITHOUT_DATE_RANGE', 2)

    posts = [_fake_post(f'post-{i}', datetime(2026, 3, 1, tzinfo=timezone.utc)) for i in range(5)]
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)

    previews = InstaloaderService._collect_posts(posts, InstagramContentType.POST, since, None)

    assert len(previews) == 5


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


@pytest.mark.asyncio
async def test_list_profile_items_times_out_instead_of_hanging_indefinitely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: instaloader's own default request_timeout is 300s per
    # HTTP call with 3 retries on top -- live-verified to hang a real
    # preview for 5+ minutes and stall the browser tab behind it. The
    # overall wait_for wrapper must fire well before that.
    import time as time_module

    import app.infrastructure.instaloader_service as instaloader_service_module

    service = _make_service(tmp_path)
    monkeypatch.setattr(instaloader_service_module, '_OVERALL_TIMEOUT_SECONDS', 0.05)

    def slow_from_username(context, username):
        time_module.sleep(1)
        raise instaloader.ProfileNotExistsException('should never get here')

    monkeypatch.setattr(instaloader.Profile, 'from_username', staticmethod(slow_from_username))

    with pytest.raises(instaloader_service_module.InstaloaderTimeoutError):
        await service.list_profile_items('https://www.instagram.com/someuser/', [InstagramContentType.POST])


@pytest.mark.asyncio
async def test_test_session_returns_none_on_timeout_rather_than_hanging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time as time_module

    import app.infrastructure.instaloader_service as instaloader_service_module

    database = tmp_path / 'pocketdl.db'
    save_session_cookie(database, 'instagram', '.instagram.com', 'sessionid=abc123')
    service = InstaloaderService(_StubSettings(database, tmp_path / 'downloads'))  # type: ignore[arg-type]
    monkeypatch.setattr(instaloader_service_module, '_OVERALL_TIMEOUT_SECONDS', 0.05)

    def slow_test_login(self):
        time_module.sleep(1)
        return 'someuser'

    monkeypatch.setattr(instaloader.InstaloaderContext, 'test_login', slow_test_login)

    assert await service.test_session() is None


def test_build_loader_uses_a_short_request_timeout_and_limited_retries(tmp_path: Path) -> None:
    import app.infrastructure.instaloader_service as instaloader_service_module

    service = _make_service(tmp_path)
    loader = service._build_loader()

    assert loader.context.request_timeout == instaloader_service_module._REQUEST_TIMEOUT_SECONDS
    assert loader.context.max_connection_attempts == instaloader_service_module._MAX_CONNECTION_ATTEMPTS
    # Regression: instaloader's own defaults are 300s and 3 attempts,
    # which is what produced the 5+ minute hang this test guards against.
    assert loader.context.request_timeout < 300
    assert loader.context.max_connection_attempts < 3


# --- Round 6 regressions: authenticated session wiring and the reels path ---


def _fake_timeline_post(
    shortcode: str,
    date: datetime,
    *,
    product_type: str = 'feed',
    pinned: bool = False,
    typename: str = 'GraphImage',
    mediacount: int = 1,
) -> SimpleNamespace:
    """A fake post carrying the `_node['iphone_struct']` the logged-in
    timeline actually returns, which is where product_type and the pinned
    marker live."""
    post = _fake_post(shortcode, date, typename=typename, mediacount=mediacount)
    post._node = {
        'iphone_struct': {
            'product_type': product_type,
            'timeline_pinned_user_ids': ['123'] if pinned else [],
        },
    }
    return post


def _cookie_json(**overrides: str) -> str:
    import json

    cookies = {
        'csrftoken': 'csrf-value',
        'sessionid': 'session-value',
        'ds_user_id': '4242',
        'mid': 'mid-value',
    }
    cookies.update(overrides)
    return json.dumps([{'name': name, 'value': value} for name, value in cookies.items()])


def test_build_loader_marks_the_context_as_logged_in_when_a_session_is_stored(tmp_path: Path) -> None:
    # Regression: this used to call context.update_cookies(), which attaches
    # cookies but leaves context.username unset. With is_logged_in False,
    # Profile.get_posts() takes its anonymous branch, whose doc_id query
    # Instagram answered with a 302 to the homepage -- surfacing as a
    # confusing "JSON Query ... Expecting value" ConnectionException.
    service = _make_service(tmp_path)
    save_session_cookie(service.settings.database_path, 'instagram', '.instagram.com', _cookie_json())

    loader = service._build_loader()

    assert loader.context.is_logged_in is True
    assert loader.context.user_id == 4242


def test_build_loader_sets_the_csrf_header_from_the_stored_session(tmp_path: Path) -> None:
    # The other half of what update_cookies() failed to do: load_session()
    # promotes csrftoken to an X-CSRFToken request header, which Instagram's
    # graphql endpoint requires.
    service = _make_service(tmp_path)
    save_session_cookie(service.settings.database_path, 'instagram', '.instagram.com', _cookie_json())

    loader = service._build_loader()

    assert loader.context._session.headers['X-CSRFToken'] == 'csrf-value'


def test_build_loader_stays_anonymous_with_no_session(tmp_path: Path) -> None:
    service = _make_service(tmp_path)

    assert service._build_loader().context.is_logged_in is False


def test_build_loader_falls_back_to_cookies_only_when_csrftoken_is_missing(tmp_path: Path) -> None:
    # load_session() indexes cookies['csrftoken'] directly, so a paste
    # missing it must not raise KeyError out of _build_loader.
    import json

    service = _make_service(tmp_path)
    save_session_cookie(
        service.settings.database_path, 'instagram', '.instagram.com',
        json.dumps([{'name': 'sessionid', 'value': 'session-value'}]),
    )

    loader = service._build_loader()

    assert loader.context.is_logged_in is False
    assert loader.context._session.cookies.get('sessionid') == 'session-value'


def test_build_loader_uses_the_username_cached_by_a_verified_session(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    save_session_cookie(service.settings.database_path, 'instagram', '.instagram.com', _cookie_json())
    service._session_username = 'realuser'
    service._session_username_key = 'session-value'

    assert service._build_loader().context.username == 'realuser'


def test_build_loader_ignores_a_username_cached_for_a_different_session(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    save_session_cookie(service.settings.database_path, 'instagram', '.instagram.com', _cookie_json())
    service._session_username = 'staleuser'
    service._session_username_key = 'a-previous-session-value'

    loader = service._build_loader()

    # Still logged in, but must not mislabel requests as the old account.
    assert loader.context.is_logged_in is True
    assert loader.context.username != 'staleuser'


def test_collect_posts_clips_only_keeps_reels_and_drops_ordinary_posts(tmp_path: Path) -> None:
    # Regression: reels are read by filtering the timeline rather than via
    # instaloader's get_reels(), which costs one extra HTTP request per reel.
    posts = [
        _fake_timeline_post('a', datetime(2026, 8, 20, tzinfo=timezone.utc), product_type='feed'),
        _fake_timeline_post('b', datetime(2026, 8, 19, tzinfo=timezone.utc), product_type='clips'),
        _fake_timeline_post('c', datetime(2026, 8, 18, tzinfo=timezone.utc), product_type='carousel_container'),
        _fake_timeline_post('d', datetime(2026, 8, 17, tzinfo=timezone.utc), product_type='clips'),
    ]

    previews = InstaloaderService._collect_posts(
        posts, InstagramContentType.REEL, None, None, clips_only=True,
    )

    assert [p.external_id for p in previews] == ['b', 'd']
    assert {p.content_type for p in previews} == {'reel'}


def test_collect_posts_without_clips_only_keeps_everything(tmp_path: Path) -> None:
    posts = [
        _fake_timeline_post('a', datetime(2026, 8, 20, tzinfo=timezone.utc), product_type='feed'),
        _fake_timeline_post('b', datetime(2026, 8, 19, tzinfo=timezone.utc), product_type='clips'),
    ]

    previews = InstaloaderService._collect_posts(posts, InstagramContentType.POST, None, None)

    assert [p.external_id for p in previews] == ['a', 'b']


def test_collect_posts_does_not_stop_at_an_out_of_order_pinned_post(tmp_path: Path) -> None:
    # Regression: Instagram serves pinned posts at the head of the timeline
    # regardless of age, so the first entry can be older than `since` while
    # the real reverse-chronological tail is still ahead. Live-verified
    # against a profile whose first three entries predated its fourth.
    since = datetime(2026, 8, 15, tzinfo=timezone.utc)
    posts = [
        _fake_timeline_post('pinned-old', datetime(2026, 1, 1, tzinfo=timezone.utc), pinned=True),
        _fake_timeline_post('recent', datetime(2026, 8, 26, tzinfo=timezone.utc)),
        _fake_timeline_post('also-recent', datetime(2026, 8, 20, tzinfo=timezone.utc)),
        _fake_timeline_post('genuinely-older', datetime(2026, 7, 1, tzinfo=timezone.utc)),
        _fake_timeline_post('never-reached', datetime(2026, 6, 1, tzinfo=timezone.utc)),
    ]

    previews = InstaloaderService._collect_posts(posts, InstagramContentType.POST, since, None)

    assert [p.external_id for p in previews] == ['recent', 'also-recent']


def test_collect_posts_still_stops_at_an_unpinned_older_post(tmp_path: Path) -> None:
    since = datetime(2026, 8, 15, tzinfo=timezone.utc)
    posts = [
        _fake_timeline_post('recent', datetime(2026, 8, 26, tzinfo=timezone.utc)),
        _fake_timeline_post('older', datetime(2026, 7, 1, tzinfo=timezone.utc)),
        _fake_timeline_post('never-reached', datetime(2026, 6, 1, tzinfo=timezone.utc)),
    ]

    previews = InstaloaderService._collect_posts(posts, InstagramContentType.POST, since, None)

    assert [p.external_id for p in previews] == ['recent']


def test_collect_posts_bounds_how_many_posts_it_scans_for_reels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A profile that posts almost no video must not page through its whole
    # history hunting for reels that aren't there.
    import app.infrastructure.instaloader_service as instaloader_service_module

    monkeypatch.setattr(instaloader_service_module, '_MAX_POSTS_SCANNED', 10)
    scanned = 0

    def endless_feed():
        nonlocal scanned
        day = datetime(2026, 8, 20, tzinfo=timezone.utc)
        while True:
            scanned += 1
            yield _fake_timeline_post(f'p{scanned}', day, product_type='feed')

    previews = InstaloaderService._collect_posts(
        endless_feed(), InstagramContentType.REEL, None, None, clips_only=True,
    )

    assert previews == []
    assert scanned <= 11


def test_media_struct_is_empty_for_a_post_with_no_timeline_struct(tmp_path: Path) -> None:
    # Must never fall through to instaloader's _iphone_struct property,
    # which fetches api/v1/media/<id>/info/ -- one request per post.
    post = _fake_post('x', datetime(2026, 8, 20, tzinfo=timezone.utc))

    assert InstaloaderService._media_struct(post) == {}
    assert InstaloaderService._is_pinned(post) is False


# --- Round 6 regressions: download target path and empty-result honesty ---


def _download_job(url: str) -> object:
    from app.domain.models import (
        DownloadEngine, DownloadJob, DownloadSourceType, DownloadStatus, ImpersonationMode,
    )

    return DownloadJob(
        id='job-1', url=url, filename=None, title=None, status=DownloadStatus.QUEUED,
        progress=0.0, downloaded_bytes=0, total_bytes=None, speed_bytes=None, eta_seconds=None,
        output_path=None, error=None, error_details=None, error_category=None, exit_code=None,
        retry_count=0, impersonation=ImpersonationMode.NONE, referer=None, origin=None,
        user_agent=None, source_type=DownloadSourceType.STANDARD,
        created_at=datetime.now(timezone.utc), started_at=None, finished_at=None,
        engine=DownloadEngine.INSTALOADER,
    )


def test_build_loader_uses_the_target_directory_as_a_literal_dirname_pattern(tmp_path: Path) -> None:
    # Regression: the target directory used to be passed as download_post()'s
    # `target=`, which instaloader substitutes into '{target}' and sanitizes.
    # On Windows that rewrote ':' and '\\' into lookalike characters, so an
    # absolute path became one literal directory name created under the
    # process's working directory -- while download_post() still returned
    # True and the job was marked completed with no file.
    service = _make_service(tmp_path)
    target = tmp_path / 'downloads' / 'Instagram' / 'someuser' / 'Reels'

    loader = service._build_loader(target)

    assert loader.dirname_pattern == str(target)
    # The pattern is str.format()ed before use, so it must survive that
    # round-trip unchanged -- this is the property that actually matters.
    assert loader.dirname_pattern.format(target='ignored', profile='ignored') == str(target)


def test_build_loader_escapes_braces_in_the_target_directory(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    target = tmp_path / 'a{weird}dir'

    loader = service._build_loader(target)

    assert loader.dirname_pattern.format(target='ignored', profile='ignored') == str(target)


def test_build_loader_without_a_target_keeps_instaloaders_default_pattern(tmp_path: Path) -> None:
    assert _make_service(tmp_path)._build_loader().dirname_pattern == '{target}'


def test_download_sync_raises_when_no_file_was_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # download_post() returns True even when nothing reached disk, so an
    # empty target directory is the only reliable failure signal.
    service = _make_service(tmp_path)
    monkeypatch.setattr(
        instaloader.Post, 'from_shortcode',
        staticmethod(lambda context, shortcode: SimpleNamespace(shortcode=shortcode)),
    )
    monkeypatch.setattr(instaloader.Instaloader, 'download_post', lambda self, post, target: True)

    job = _download_job('https://www.instagram.com/p/ABC123/')

    with pytest.raises(RuntimeError, match='no file was written'):
        service._download_sync(job, 'someuser', 'post')


def test_download_sync_returns_the_written_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _make_service(tmp_path)
    monkeypatch.setattr(
        instaloader.Post, 'from_shortcode',
        staticmethod(lambda context, shortcode: SimpleNamespace(shortcode=shortcode)),
    )

    def fake_download_post(self, post, target):
        written = Path(self.dirname_pattern) / 'ABC123_GraphVideo.mp4'
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_bytes(b'video')
        return True

    monkeypatch.setattr(instaloader.Instaloader, 'download_post', fake_download_post)

    job = _download_job('https://www.instagram.com/reel/ABC123/')
    output_path = service._download_sync(job, 'someuser', 'reel')

    assert Path(output_path).name == 'ABC123_GraphVideo.mp4'
    # And it landed in the real folder tree, not a sanitized lookalike.
    assert Path(output_path).parent == tmp_path / 'downloads' / 'Instagram' / 'someuser' / 'Reels'


@pytest.mark.asyncio
async def test_download_fails_rather_than_reporting_success_without_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.models import DownloadStatus, RequestContext

    service = _make_service(tmp_path)
    monkeypatch.setattr(InstaloaderService, '_download_sync', lambda self, job, username, content_type: None)

    async def on_progress(job) -> None:
        return None

    job = await service.download(
        _download_job('https://www.instagram.com/p/ABC123/'),
        context=RequestContext(), retries=0, on_progress=on_progress,
    )

    assert job.status is DownloadStatus.FAILED
    assert job.output_path is None
    assert 'produced no file' in (job.error or '')


@pytest.mark.asyncio
async def test_download_fails_when_the_reported_file_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.models import DownloadStatus, RequestContext

    service = _make_service(tmp_path)
    missing = str(tmp_path / 'gone.mp4')
    monkeypatch.setattr(InstaloaderService, '_download_sync', lambda self, job, username, content_type: missing)

    async def on_progress(job) -> None:
        return None

    job = await service.download(
        _download_job('https://www.instagram.com/p/ABC123/'),
        context=RequestContext(), retries=0, on_progress=on_progress,
    )

    assert job.status is DownloadStatus.FAILED


@pytest.mark.asyncio
async def test_download_succeeds_when_the_file_is_really_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.models import DownloadStatus, RequestContext

    service = _make_service(tmp_path)
    written = tmp_path / 'real.mp4'
    written.write_bytes(b'video')
    monkeypatch.setattr(
        InstaloaderService, '_download_sync', lambda self, job, username, content_type: str(written),
    )

    async def on_progress(job) -> None:
        return None

    job = await service.download(
        _download_job('https://www.instagram.com/p/ABC123/'),
        context=RequestContext(), retries=0, on_progress=on_progress,
    )

    assert job.status is DownloadStatus.COMPLETED
    assert job.output_path == str(written)
    assert job.progress == 100.0


# --- Round 6 regressions: posts and reels share one timeline scan ---


class _TimelineProfile:
    """Profile stub whose get_posts() yields a fixed timeline and counts how
    many times it was paged."""

    def __init__(self, posts: list) -> None:
        self.userid = 1
        self.username = 'someuser'
        self._posts = posts
        self.get_posts_calls = 0

    def get_posts(self):
        self.get_posts_calls += 1
        return iter(self._posts)


def _mixed_timeline() -> list:
    return [
        _fake_timeline_post('p1', datetime(2026, 8, 20, tzinfo=timezone.utc), product_type='feed'),
        _fake_timeline_post('r1', datetime(2026, 8, 19, tzinfo=timezone.utc), product_type='clips'),
        _fake_timeline_post(
            'c1', datetime(2026, 8, 18, tzinfo=timezone.utc),
            product_type='carousel_container', typename='GraphSidecar', mediacount=3,
        ),
        _fake_timeline_post('r2', datetime(2026, 8, 17, tzinfo=timezone.utc), product_type='clips'),
    ]


@pytest.mark.asyncio
async def test_posts_and_reels_page_the_timeline_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: posts and reels are both views of Profile.get_posts(), so
    # scanning them separately paged the identical timeline twice. Measured
    # live at 63s vs 45s for the same 100 items -- uncomfortably close to
    # the 90s overall budget for the common "everything" selection.
    service = _make_service(tmp_path)
    profile = _TimelineProfile(_mixed_timeline())
    monkeypatch.setattr(instaloader.Profile, 'from_username', staticmethod(lambda context, username: profile))

    items = await service.list_profile_items(
        'https://www.instagram.com/someuser/', [InstagramContentType.POST, InstagramContentType.REEL],
    )

    assert profile.get_posts_calls == 1
    # Same output as scanning twice: every timeline item under 'post'
    # (carousels classified as such), plus the clips again under 'reel'.
    assert [(i.external_id, i.content_type) for i in items] == [
        ('p1', 'post'), ('r1', 'post'), ('c1', 'carousel'), ('r2', 'post'),
        ('r1', 'reel'), ('r2', 'reel'),
    ]


@pytest.mark.asyncio
async def test_reels_only_does_not_return_ordinary_posts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(tmp_path)
    profile = _TimelineProfile(_mixed_timeline())
    monkeypatch.setattr(instaloader.Profile, 'from_username', staticmethod(lambda context, username: profile))

    items = await service.list_profile_items(
        'https://www.instagram.com/someuser/', [InstagramContentType.REEL],
    )

    assert profile.get_posts_calls == 1
    assert [(i.external_id, i.content_type) for i in items] == [('r1', 'reel'), ('r2', 'reel')]


@pytest.mark.asyncio
async def test_reels_requested_before_posts_keeps_the_requested_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The shared scan is triggered by whichever bucket comes first; the
    # response must still follow the order the caller asked for.
    service = _make_service(tmp_path)
    profile = _TimelineProfile(_mixed_timeline())
    monkeypatch.setattr(instaloader.Profile, 'from_username', staticmethod(lambda context, username: profile))

    items = await service.list_profile_items(
        'https://www.instagram.com/someuser/', [InstagramContentType.REEL, InstagramContentType.POST],
    )

    assert profile.get_posts_calls == 1
    assert [i.content_type for i in items] == ['reel', 'reel', 'post', 'post', 'carousel', 'post']


def test_scan_timeline_caps_each_bucket_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.infrastructure.instaloader_service as instaloader_service_module

    monkeypatch.setattr(instaloader_service_module, '_MAX_ITEMS_WITHOUT_DATE_RANGE', 3)
    day = datetime(2026, 8, 20, tzinfo=timezone.utc)
    # Every third item is a reel, so the post bucket fills long before the
    # reel bucket does -- the scan must keep going until both are full.
    timeline = [
        _fake_timeline_post(f'i{n}', day, product_type='clips' if n % 3 == 0 else 'feed')
        for n in range(30)
    ]

    posts, reels = InstaloaderService._scan_timeline(
        iter(timeline), None, None, want_posts=True, want_reels=True,
    )

    assert len(posts) == 3
    assert len(reels) == 3
    assert all(p.external_id in {'i0', 'i3', 'i6'} for p in reels)
