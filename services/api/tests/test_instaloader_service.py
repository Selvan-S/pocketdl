from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import instaloader
import pytest

from app.core.session_store import save_session_cookie
from app.domain.collections import InstagramAuthRequiredError, InstagramContentType
from app.infrastructure.instaloader_service import DownloadResult, InstaloaderService


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
    result = service._download_sync(job, 'someuser', 'reel')

    assert Path(result.output_path).name == 'ABC123_GraphVideo.mp4'
    # And it landed in the real folder tree, not a sanitized lookalike.
    assert Path(result.output_path).parent == tmp_path / 'downloads' / 'Instagram' / 'someuser' / 'Reels'


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
    missing = DownloadResult(output_path=str(tmp_path / 'gone.mp4'))
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
        InstaloaderService, '_download_sync',
        lambda self, job, username, content_type: DownloadResult(output_path=str(written)),
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


# --- Round 7 regressions: reels come from the Reels tab, not the timeline ---


def _reel_media(code: str, pk: int, *, pinned: bool = False, thumb: str | None = 'https://cdn.example/r.jpg') -> dict:
    """The shape the reels connection actually returns -- note the absence of
    taken_at and caption, which is the whole reason for _media_pk_to_datetime."""
    media: dict = {
        'code': code,
        'pk': pk,
        'media_type': 2,
        'user': {'pk': '123', 'id': '123'},
        'clips_tab_pinned_user_ids': ['123'] if pinned else [],
    }
    if thumb:
        media['image_versions2'] = {'candidates': [{'height': 1280, 'url': thumb}]}
    return media


def _pk_for(when: datetime) -> int:
    """Inverse of _media_pk_to_datetime, for building fixtures at a known date."""
    import app.infrastructure.instaloader_service as mod

    millis = int(when.timestamp() * 1000) - mod._IG_ID_EPOCH_MS
    return millis << mod._IG_ID_TIMESTAMP_SHIFT


class _ReelsProfile:
    """Profile stub with an empty grid but a populated Reels tab -- the exact
    shape that made reels come back empty."""

    def __init__(self, timeline: list | None = None) -> None:
        self.userid = 1
        self.username = 'someuser'
        self._timeline = timeline or []
        self.get_posts_calls = 0

    def get_posts(self):
        self.get_posts_calls += 1
        return iter(self._timeline)


def test_media_pk_round_trips_to_the_expected_timestamp(tmp_path: Path) -> None:
    when = datetime(2026, 8, 23, 11, 9, 1, tzinfo=timezone.utc)
    derived = InstaloaderService._media_pk_to_datetime(_pk_for(when))
    assert abs((derived - when).total_seconds()) < 1


def test_media_pk_decodes_a_real_instagram_id(tmp_path: Path) -> None:
    # Captured live from the reels connection: pk 3971730051816042598 is
    # shortcode Dcea3BiPTBm, published 2026-08-25 19:55:51 UTC. The derived
    # value is the upload start, so it runs early -- but only by minutes.
    derived = InstaloaderService._media_pk_to_datetime(3971730051816042598)
    published = datetime(2026, 8, 25, 19, 55, 51, tzinfo=timezone.utc)
    assert derived <= published
    assert (published - derived).total_seconds() < 3600


def test_reel_to_preview_maps_the_connection_struct(tmp_path: Path) -> None:
    when = datetime(2026, 8, 23, 11, 9, 1, tzinfo=timezone.utc)
    preview = InstaloaderService._reel_to_preview(_reel_media('ABC', _pk_for(when)), 'someuser')

    assert preview is not None
    assert preview.external_id == 'ABC'
    assert preview.source_url == 'https://www.instagram.com/reel/ABC/'
    assert preview.content_type == 'reel'
    assert preview.thumbnail_url == 'https://cdn.example/r.jpg'
    assert preview.author_username == 'someuser'
    assert preview.profile_username == 'someuser'
    # The connection carries no caption at any depth; it is filled in at
    # download time instead of costing a request per reel at preview time.
    assert preview.caption is None
    assert abs((preview.posted_at - when).total_seconds()) < 1


def test_reel_to_preview_skips_a_struct_with_no_code_or_pk(tmp_path: Path) -> None:
    assert InstaloaderService._reel_to_preview({'pk': 1}, 'u') is None
    assert InstaloaderService._reel_to_preview({'code': 'A'}, 'u') is None
    assert InstaloaderService._reel_to_preview({'code': 'A', 'pk': 'not-a-number'}, 'u') is None


def test_reel_to_preview_tolerates_a_missing_thumbnail(tmp_path: Path) -> None:
    preview = InstaloaderService._reel_to_preview(
        _reel_media('ABC', _pk_for(datetime(2026, 8, 23, tzinfo=timezone.utc)), thumb=None), 'someuser',
    )
    assert preview is not None and preview.thumbnail_url is None


@pytest.mark.asyncio
async def test_reels_are_returned_even_when_the_timeline_has_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # THE regression. Round 6 read reels as the product_type=='clips' entries
    # of the profile grid. Live testing found a real profile whose 25 grid
    # posts and 15+ reels were entirely disjoint (a reel can be published with
    # "don't show on profile grid"), so reels came back empty every time while
    # posts worked fine.
    service = _make_service(tmp_path)
    profile = _ReelsProfile(timeline=[
        _fake_timeline_post('grid1', datetime(2026, 8, 20, tzinfo=timezone.utc), product_type='feed'),
        _fake_timeline_post('grid2', datetime(2026, 8, 19, tzinfo=timezone.utc), product_type='carousel_container'),
    ])
    monkeypatch.setattr(instaloader.Profile, 'from_username', staticmethod(lambda context, username: profile))
    monkeypatch.setattr(
        InstaloaderService, '_collect_reels',
        lambda self, loader, prof, since, until: [
            InstaloaderService._reel_to_preview(
                _reel_media('reel1', _pk_for(datetime(2026, 8, 23, tzinfo=timezone.utc))), prof.username,
            ),
        ],
    )

    items = await service.list_profile_items(
        'https://www.instagram.com/someuser/', [InstagramContentType.REEL],
    )

    assert [i.external_id for i in items] == ['reel1']
    # And it must not have paged the grid at all to find them.
    assert profile.get_posts_calls == 0


def test_collect_reels_stops_at_the_date_bound_and_skips_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.infrastructure.instaloader_service as mod

    service = _make_service(tmp_path)
    profile = _ReelsProfile()
    since = datetime(2026, 8, 15, tzinfo=timezone.utc)
    feed = [
        _reel_media('pinned-old', _pk_for(datetime(2026, 1, 1, tzinfo=timezone.utc)), pinned=True),
        _reel_media('recent', _pk_for(datetime(2026, 8, 26, tzinfo=timezone.utc))),
        _reel_media('older', _pk_for(datetime(2026, 7, 1, tzinfo=timezone.utc))),
        _reel_media('never-reached', _pk_for(datetime(2026, 6, 1, tzinfo=timezone.utc))),
    ]
    monkeypatch.setattr(mod.instaloader, 'NodeIterator', lambda **kwargs: iter(feed))

    previews = service._collect_reels(SimpleNamespace(context=object()), profile, since, None)

    assert [p.external_id for p in previews] == ['recent']


def test_collect_reels_caps_when_no_date_range_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.infrastructure.instaloader_service as mod

    monkeypatch.setattr(mod, '_MAX_ITEMS_WITHOUT_DATE_RANGE', 3)
    service = _make_service(tmp_path)
    when = datetime(2026, 8, 20, tzinfo=timezone.utc)
    consumed = 0

    def endless():
        nonlocal consumed
        while True:
            consumed += 1
            yield _reel_media(f'r{consumed}', _pk_for(when))

    monkeypatch.setattr(mod.instaloader, 'NodeIterator', lambda **kwargs: endless())

    previews = service._collect_reels(SimpleNamespace(context=object()), _ReelsProfile(), None, None)

    assert len(previews) == 3
    assert consumed <= 4


def test_collect_reels_asks_for_the_reels_connection_not_the_timeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.infrastructure.instaloader_service as mod

    captured: dict = {}

    def fake_iterator(**kwargs):
        captured.update(kwargs)
        return iter([])

    monkeypatch.setattr(mod.instaloader, 'NodeIterator', fake_iterator)
    _make_service(tmp_path)._collect_reels(SimpleNamespace(context=object()), _ReelsProfile(), None, None)

    assert captured['doc_id'] == mod._REELS_DOC_ID
    assert captured['query_variables']['data']['target_user_id'] == '1'
    # The node_wrapper must hand back the raw struct. instaloader's own
    # get_reels() wraps it in Post.from_shortcode(), which is one HTTP
    # request per reel -- 15 reels took 179s live.
    assert captured['node_wrapper']({'media': {'code': 'X'}}) == {'code': 'X'}


# --- Round 7: downloads belong to the profile you browsed ---


def test_post_preview_records_both_the_owner_and_the_browsed_profile(tmp_path: Path) -> None:
    # Regression: Instagram credits a co-authored post to the collaborator
    # (live-verified: a post browsed on `nasa` reported `nasajohnson`), so
    # keying the download folder on the owner scattered one profile's
    # download across other people's folders.
    post = _fake_post('abc', datetime(2026, 8, 20, tzinfo=timezone.utc))
    post.owner_username = 'a_collaborator'

    preview = InstaloaderService._post_to_preview(post, InstagramContentType.POST, 'browsed_profile')

    assert preview.author_username == 'a_collaborator'
    assert preview.profile_username == 'browsed_profile'


def test_download_target_uses_the_browsed_profile(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    directory = service._target_directory('browsed_profile', 'reel')
    assert directory == tmp_path / 'downloads' / 'Instagram' / 'browsed_profile' / 'Reels'


def test_highlights_land_in_the_same_profile_folder_as_posts(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    posts = service._target_directory('someuser', 'post')
    highlights = service._target_directory('someuser', 'highlight')
    assert posts.parent == highlights.parent
    assert highlights.name == 'Highlights'


# --- Round 7: archive-quality filenames and captions ---


def test_filename_pattern_leads_with_the_date_and_keeps_the_shortcode(tmp_path: Path) -> None:
    import app.infrastructure.instaloader_service as mod

    rendered = mod._FILENAME_PATTERN.format(
        date_utc=datetime(2026, 8, 23, 11, 9, 1), shortcode='DcYSnllvjCn',
    )
    assert rendered == '2026-08-23_11-09-01_DcYSnllvjCn'
    # Colons would be mangled by instaloader's Windows path sanitizer, which
    # is why this does not use instaloader's literal '{date_utc}_UTC' default.
    assert ':' not in rendered


def test_caption_sidecar_is_enabled_but_metadata_json_is_not(tmp_path: Path) -> None:
    loader = _make_service(tmp_path)._build_loader()
    assert loader.post_metadata_txt_pattern == '{caption}'
    assert loader.save_metadata is False


def test_download_glob_finds_a_date_prefixed_file_and_ignores_the_caption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(tmp_path)
    monkeypatch.setattr(
        instaloader.Post, 'from_shortcode',
        staticmethod(lambda context, shortcode: SimpleNamespace(shortcode=shortcode)),
    )

    def fake_download_post(self, post, target):
        directory = Path(self.dirname_pattern)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / '2026-08-23_11-09-01_ABC123.mp4').write_bytes(b'video')
        (directory / '2026-08-23_11-09-01_ABC123.txt').write_text('the caption')
        return True

    monkeypatch.setattr(instaloader.Instaloader, 'download_post', fake_download_post)

    result = service._download_sync(_download_job('https://www.instagram.com/reel/ABC123/'), 'someuser', 'reel')

    assert Path(result.output_path).name == '2026-08-23_11-09-01_ABC123.mp4'


# --- Round 7: exact caption/date backfilled onto the item at download time ---


class _RecordingCollectionRepository:
    def __init__(self, item) -> None:
        self.item = item
        self.metadata_updates: list[tuple] = []

    async def get_item(self, item_id: str):
        return self.item

    async def update_item_metadata(self, item_id: str, *, caption, posted_at) -> None:
        self.metadata_updates.append((item_id, caption, posted_at))


def _collection_item(**overrides):
    from app.domain.collections import CollectionItem

    defaults = dict(
        id='item-1', collection_id='c1', source_url='https://www.instagram.com/reel/ABC123/',
        content_type='reel', author_username='someuser', caption=None,
        thumbnail_url=None, external_id='ABC123', added_at=datetime.now(timezone.utc),
        posted_at=None, profile_username='someuser',
    )
    defaults.update(overrides)
    return CollectionItem(**defaults)


@pytest.mark.asyncio
async def test_download_backfills_the_exact_caption_and_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A reel preview has no caption and only a media-id-derived approximation
    # of the date. Downloading fetches the real post anyway, so the exact
    # values are free at that point and should replace the estimate.
    from app.domain.models import RequestContext

    written = tmp_path / 'real.mp4'
    written.write_bytes(b'video')
    exact = datetime(2026, 8, 23, 11, 9, 1, tzinfo=timezone.utc)
    repository = _RecordingCollectionRepository(_collection_item())
    service = _make_service(tmp_path)
    service.collection_repository = repository
    monkeypatch.setattr(
        InstaloaderService, '_download_sync',
        lambda self, job, username, content_type: DownloadResult(
            output_path=str(written), caption='the real caption', posted_at=exact,
        ),
    )

    async def on_progress(job) -> None:
        return None

    await service.download(
        _download_job('https://www.instagram.com/reel/ABC123/'),
        context=RequestContext(), retries=0, on_progress=on_progress, collection_item_id='item-1',
    )

    assert repository.metadata_updates == [('item-1', 'the real caption', exact)]


@pytest.mark.asyncio
async def test_download_does_not_backfill_when_it_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.models import RequestContext

    repository = _RecordingCollectionRepository(_collection_item())
    service = _make_service(tmp_path)
    service.collection_repository = repository
    monkeypatch.setattr(
        InstaloaderService, '_download_sync',
        lambda self, job, username, content_type: (_ for _ in ()).throw(RuntimeError('nope')),
    )

    async def on_progress(job) -> None:
        return None

    await service.download(
        _download_job('https://www.instagram.com/reel/ABC123/'),
        context=RequestContext(), retries=0, on_progress=on_progress, collection_item_id='item-1',
    )

    assert repository.metadata_updates == []


@pytest.mark.asyncio
async def test_download_folder_prefers_profile_username_over_author(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.models import RequestContext

    captured: list[str | None] = []
    written = tmp_path / 'real.mp4'
    written.write_bytes(b'video')
    repository = _RecordingCollectionRepository(
        _collection_item(author_username='a_collaborator', profile_username='browsed_profile'),
    )
    service = _make_service(tmp_path)
    service.collection_repository = repository

    def fake_sync(self, job, username, content_type):
        captured.append(username)
        return DownloadResult(output_path=str(written))

    monkeypatch.setattr(InstaloaderService, '_download_sync', fake_sync)

    async def on_progress(job) -> None:
        return None

    await service.download(
        _download_job('https://www.instagram.com/p/ABC123/'),
        context=RequestContext(), retries=0, on_progress=on_progress, collection_item_id='item-1',
    )

    assert captured == ['browsed_profile']


@pytest.mark.asyncio
async def test_download_folder_falls_back_to_author_for_pre_migration_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Items saved before profile_username existed have it as NULL.
    from app.domain.models import RequestContext

    captured: list[str | None] = []
    written = tmp_path / 'real.mp4'
    written.write_bytes(b'video')
    repository = _RecordingCollectionRepository(
        _collection_item(author_username='legacy_author', profile_username=None),
    )
    service = _make_service(tmp_path)
    service.collection_repository = repository

    def fake_sync(self, job, username, content_type):
        captured.append(username)
        return DownloadResult(output_path=str(written))

    monkeypatch.setattr(InstaloaderService, '_download_sync', fake_sync)

    async def on_progress(job) -> None:
        return None

    await service.download(
        _download_job('https://www.instagram.com/p/ABC123/'),
        context=RequestContext(), retries=0, on_progress=on_progress, collection_item_id='item-1',
    )

    assert captured == ['legacy_author']
