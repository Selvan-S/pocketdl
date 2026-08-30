import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import instaloader

from ..core.config import Settings
from ..core.filenames import sanitize_filename
from ..core.session_store import load_cookie_pairs
from ..domain.collections import InstagramAuthRequiredError, InstagramContentType, ProfileItemPreview
from ..domain.errors import DownloadErrorCategory
from ..domain.models import DownloadJob, DownloadStatus, RequestContext
from ..domain.ports import CollectionRepository

ProgressCallback = Callable[[DownloadJob], Awaitable[None]]

# Instagram content_type values (see domain/collections.py) mapped to the
# folder-tree names from docs/instagram-full-profile-plan.md's "Folder
# organization" section. Shared with GalleryDlService's own copy -- kept
# duplicated rather than imported across the two engine modules, since each
# is a leaf infrastructure module and this is four short strings, not a
# real cross-cutting concern.
_CONTENT_TYPE_FOLDERS = {
    'post': 'Posts',
    'carousel': 'Posts',
    'reel': 'Reels',
    'story': 'Stories',
    'highlight': 'Highlights',
}

# instaloader's own filename pattern language (see Instaloader.filename_pattern).
#
# Date first so a folder sorts chronologically by name, then the shortcode so
# the name is collision-free and a generated gallery can link a file back to
# its Instagram post. instaloader's own default is '{date_utc}_UTC', which
# renders with colons ('2026-08-25 19:55:51_UTC') -- those hit the same
# Windows sanitize_path mangling documented on dirname_pattern below, so the
# format spec here spells the date out with hyphens instead.
#
# instaloader skips a file that already exists under the exact name it would
# write (Instaloader.download_pic), so a stable pattern is also what makes
# re-downloading a collection idempotent.
_FILENAME_PATTERN = '{date_utc:%Y-%m-%d_%H-%M-%S}_{shortcode}'

# Reels live in their own tab, which is NOT a subset of the profile grid: a
# reel can be published with "don't show on profile grid", and live testing
# found a real profile whose 25 grid posts and 15+ reels were entirely
# disjoint (see docs_POCKETDL_ROADMAP.md Phase 5 "Round 7"). So reels have to
# come from the reels connection, not from filtering the timeline.
#
# instaloader's own Profile.get_reels() wraps this same connection but calls
# Post.from_shortcode() per reel to fill in the metadata the connection
# omits -- measured live at 15 reels in 179s. This module drives the
# connection directly and builds previews from the raw media struct instead,
# which costs one request per 12 reels.
_REELS_DOC_ID = '7845543455542541'
_REELS_PAGE_SIZE = 12
_REELS_CONNECTION_KEY = 'xdt_api__v1__clips__user__connection_v2'

# Instagram media primary keys are Snowflake-like: the upper bits are a
# millisecond timestamp offset from this epoch. The reels connection omits
# `taken_at` entirely, so this is how a reel preview gets a date without
# spending a request per reel to look one up.
#
# It is the moment the *upload began*, not the moment the post published, so
# it runs early -- measured against known-good dates on a real profile, by
# between 47 seconds and 31 minutes. Good enough to sort by and to filter a
# day-granularity date range with, and it is deliberately surfaced as
# approximate rather than presented as exact; the true date and the caption
# are both filled in at download time, where Post.from_shortcode() runs
# anyway.
_IG_ID_EPOCH_MS = 1314220021721
_IG_ID_TIMESTAMP_SHIFT = 23

# Preview cards are small and there can be a hundred of them on screen at
# once. Instagram offers the same image at a dozen sizes; `Post.url` is the
# *original* -- measured at 3024x4032 on a real profile -- so a preview grid
# was pulling multiple megabytes per card and locking up the browser, which
# was the single biggest cause of the reported UI slowness. Pick the smallest
# rendition that still looks sharp on a retina card instead.
_THUMBNAIL_TARGET_WIDTH = 320

# instaloader's own default request_timeout is 300s (five minutes) *per HTTP
# request*, with max_connection_attempts=3 retries on top -- live-verified
# to actually hang a real preview call for 5+ minutes against a real
# profile, stalling the browser tab behind it (see
# docs_POCKETDL_ROADMAP.md Phase 5). A single Instagram request normally
# completes in well under this; a slow/soft-blocked one should fail fast
# and let the caller retry, not sit on an open connection indefinitely.
_REQUEST_TIMEOUT_SECONDS = 20.0
_MAX_CONNECTION_ATTEMPTS = 2
# Outer safety net around the whole operation (asyncio.wait_for on the
# to_thread call) -- a preview can make several sequential requests
# (profile lookup, then one per requested content type), so this is a
# multiple of the per-request timeout above, not equal to it. Does not
# actually kill the underlying thread (Python threads cannot be forced to
# stop), just stops the caller from waiting on it -- the orphaned request
# finishes or fails on its own in the background.
_OVERALL_TIMEOUT_SECONDS = 90.0
# A download transfers real media bytes, not just metadata, so it gets a
# much longer cap than a preview -- this only guards against a fully
# stalled connection (the per-request timeout above already fails fast on
# that), not against a large file legitimately taking a while.
_DOWNLOAD_TIMEOUT_SECONDS = 600.0


class InstaloaderTimeoutError(RuntimeError):
    """Instagram did not respond within the overall time budget."""


@dataclass(frozen=True, slots=True)
class ProfileItemPage:
    """One page of profile items, plus what a caller needs to ask for the
    next one.

    `has_more` is only ever true because a bucket filled its page -- never
    because a scan ceiling was hit or a feed ran out -- so "load more" is
    offered exactly when there really is more.
    """

    items: list[ProfileItemPreview]
    has_more: bool

    @property
    def next_posted_before(self) -> datetime | None:
        """Cursor for the following page: the oldest item on this one.

        A date rather than an opaque iterator handle. instaloader can freeze
        and thaw a NodeIterator, but that state expires, has to be carried
        across restarts, and has to be rebuilt identically to be usable --
        whereas both feeds here are already reverse-chronological and the
        code already filters on `until`, so a date reuses machinery that
        exists and is verified. The cost is that page N re-scans the N-1
        pages above it; the mitigation is that a caller wanting a lot of
        items should ask for one big page instead (see _MAX_PAGE_SIZE).

        Callers must de-duplicate by external_id when appending: items
        sharing a timestamp with the last of this page can reappear.
        """
        dated = [item.posted_at for item in self.items if item.posted_at is not None]
        return min(dated) if dated else None


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """What a completed download learned on the way.

    A reel's preview comes from the Reels connection, which carries no
    caption and only a media-id-derived approximation of the date. The
    download fetches the real post regardless, so the exact values are free
    here -- worth handing back so the stored item stops showing an estimate.
    """

    output_path: str
    caption: str | None = None
    posted_at: datetime | None = None


# When no `since` bound is given, there is nothing to naturally stop
# pagination early -- an active profile's full post/reel history can be
# dozens of pages. Cap to a recent window instead; explicitly narrowing
# the date range still works via the ordinary early-break above this.
_DEFAULT_PAGE_SIZE = 50
# A "load more" page costs a full re-scan from the top of the feed (see
# ProfileDiscoveryService for why the cursor is a date rather than an opaque
# iterator handle), so a caller wanting a lot of items is better served by
# asking for a big page once than by paging repeatedly. Bounded so one
# request still fits inside the overall timeout.
_MAX_PAGE_SIZE = 200

# Reels are read by filtering the ordinary profile timeline rather than by
# instaloader's own `Profile.get_reels()` -- see `_collect_posts`. Filtering
# means the number of *posts scanned* is larger than the number of reels
# kept, so pagination needs its own separate ceiling: without one, a profile
# that posts rarely-but-not-never in video form would page through its whole
# history looking for reels that aren't there.
#
# Ceiling on how far into a feed one request will read, independent of how
# many items it keeps. Matters when a filter rejects most of what it sees --
# without it, a narrow date range on an inactive profile would page that
# profile's whole history looking for matches that aren't there.
#
# Sized against _OVERALL_TIMEOUT_SECONDS rather than picked round: a feed
# returns 12 items per request, and a request plus instaloader's rate-limit
# courtesy sleep was measured live at ~3.5s, so 600 items is ~50 requests is
# ~175s. That exceeds the default budget on purpose -- a large page raises
# the timeout to match (see list_profile_items), and a default-sized page
# stops at _DEFAULT_PAGE_SIZE long before reaching here.
_MAX_ITEMS_SCANNED = 600

# Extra time budget for a large page. The default 90s covers a 50-item page
# comfortably; a 200-item one needs more, and a request that is going to take
# a while is better than one that fails at 90s having done the work.
_LARGE_PAGE_TIMEOUT_SECONDS = 240.0

# Instagram's own `product_type` discriminator on a timeline media struct.
# 'clips' is what the app calls a Reel; 'feed' is an ordinary post and
# 'carousel_container' a multi-image post.
_CLIPS_PRODUCT_TYPE = 'clips'

# instaloader's `InstaloaderContext.username` is what its `is_logged_in`
# property tests, and it is only ever set by `load_session()`/`login()` --
# never by `update_cookies()`. Session cookies are pasted from the user's
# browser, so there is no login step to learn the username from, and a
# request to resolve it is not always worth making (see `_apply_session`).
# This placeholder keeps `is_logged_in` true, which is the part that
# actually changes instaloader's behaviour; `test_session()` replaces it
# with the real username once the user verifies their session.
_UNRESOLVED_USERNAME = '(session)'


class InstaloaderService:
    """Instagram-specific engine: precise, typed exceptions and native
    date filtering, in exchange for running in-process (a library call on a
    background thread via asyncio.to_thread) rather than as a subprocess --
    see domain/models.py's DownloadEngine docstring.
    """

    def __init__(self, settings: Settings, collection_repository: CollectionRepository | None = None) -> None:
        self.settings = settings
        self.collection_repository = collection_repository
        # Username behind the currently-stored cookie, once resolved by
        # test_session(). Keyed by the cookie itself so that replacing the
        # stored session invalidates it instead of silently mislabelling
        # requests as the previous account.
        self._session_username: str | None = None
        self._session_username_key: str | None = None

    @staticmethod
    def version() -> str:
        return instaloader.__version__

    def _build_loader(self, target_directory: Path | None = None) -> instaloader.Instaloader:
        loader = instaloader.Instaloader(
            sleep=True,
            quiet=True,
            request_timeout=_REQUEST_TIMEOUT_SECONDS,
            max_connection_attempts=_MAX_CONNECTION_ATTEMPTS,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            filename_pattern=_FILENAME_PATTERN,
            # instaloader's default: a per-post '<same basename>.txt' holding
            # the caption. Round 6 disabled this on the grounds that the
            # caption is already in the DB (CollectionItem.caption), which
            # was the wrong call -- the download folder should stand on its
            # own, readable without PocketDL's database, and a generated
            # offline gallery reads captions from here. The heavier
            # per-post JSON stays off via save_metadata=False above.
            post_metadata_txt_pattern='{caption}',
            # Where downloads land. instaloader's default is '{target}',
            # substituting the `target=` argument of download_post() -- but
            # every *substituted* value is run through
            # _PostPathFormatter.sanitize_path(), which on Windows rewrites
            # ':' to a fullwidth colon and a backslash to a small reverse
            # solidus unconditionally (the `sanitize_paths` flag only forces
            # that behaviour on non-Windows; it does not disable it here).
            # Passing an absolute path as `target` therefore created one
            # literal directory named after the whole mangled path, under
            # the process's working directory -- while download_post() still
            # returned True. Live-verified; see docs_POCKETDL_ROADMAP.md
            # Phase 5 "Round 6".
            #
            # The *pattern* itself is never sanitized, only the values
            # substituted into it, so a literal path with no placeholders
            # round-trips intact. Braces are escaped because the pattern is
            # run through str.format().
            dirname_pattern=(
                str(target_directory).replace('{', '{{').replace('}', '}}')
                if target_directory is not None else '{target}'
            ),
        )
        pairs = load_cookie_pairs(self.settings.database_path, 'instagram')
        if pairs:
            self._apply_session(loader, pairs)
        return loader

    @staticmethod
    def _session_key(pairs: dict[str, str]) -> str:
        return pairs.get('sessionid', '')

    def _apply_session(self, loader: instaloader.Instaloader, pairs: dict[str, str]) -> None:
        """Attach the stored browser session so instaloader treats itself as
        logged in.

        Deliberately `load_session()` and not `update_cookies()`, which is
        what this used to call. `update_cookies()` only pushes cookies into
        the requests session: it leaves `context.username` unset (so
        `context.is_logged_in` stays False) and never sets the `X-CSRFToken`
        header. Both mattered, and were live-verified against a real session
        (see docs_POCKETDL_ROADMAP.md Phase 5 "Round 6"):

        * With `is_logged_in` False, `Profile.get_posts()` selects its
          anonymous doc_id/edge-extractor branch. Instagram answered that
          query with a 302 to the homepage, which instaloader surfaced as a
          confusing `ConnectionException: JSON Query ... Expecting value` --
          i.e. profile posts failed outright, not slowly.
        * With `is_logged_in` True, the same call selects the logged-in
          branch, which returns full per-post metadata (date, caption, owner,
          media URLs) 12 items at a time, with no follow-up request per item.
        """
        if 'csrftoken' not in pairs:
            # load_session() indexes cookies['csrftoken'] directly; a paste
            # missing it would raise KeyError. Better to run anonymously and
            # let the caller's auth-required handling report it.
            loader.context.update_cookies(pairs)
            return

        key = self._session_key(pairs)
        username = self._session_username if key == self._session_username_key else None
        loader.context.load_session(username or _UNRESOLVED_USERNAME, pairs)
        user_id = pairs.get('ds_user_id')
        if user_id and user_id.isdigit():
            loader.context.user_id = int(user_id)

    async def test_session(self) -> str | None:
        """Verify the stored session cookie actually authenticates,
        returning the logged-in username, or None if it does not (missing,
        expired, or rejected). Lets the UI confirm a pasted cookie works
        immediately instead of finding out mid-preview."""
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._test_session_sync), timeout=_OVERALL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return None

    def _test_session_sync(self) -> str | None:
        pairs = load_cookie_pairs(self.settings.database_path, 'instagram')
        if not pairs:
            return None
        loader = self._build_loader()
        username = loader.context.test_login()
        # Cache it so subsequent previews run under the real username rather
        # than the _UNRESOLVED_USERNAME placeholder, without spending an
        # extra request per preview to look it up.
        self._session_username = username
        self._session_username_key = self._session_key(pairs) if username else None
        return username

    @staticmethod
    def _profile_username(profile_url: str) -> str:
        parsed = urlparse(profile_url)
        username = parsed.path.strip('/').split('/')[0] if parsed.path else ''
        if not username:
            raise ValueError('profile_url must include a username, e.g. https://www.instagram.com/someuser/')
        return username

    @staticmethod
    def _classify(post: instaloader.Post, bucket: InstagramContentType) -> str:
        if bucket is not InstagramContentType.POST:
            return bucket.value
        if post.typename == 'GraphSidecar' or post.mediacount > 1:
            return InstagramContentType.CAROUSEL.value
        return InstagramContentType.POST.value

    @staticmethod
    def _post_to_preview(
        post: instaloader.Post, bucket: InstagramContentType, profile_username: str | None = None,
    ) -> ProfileItemPreview:
        return ProfileItemPreview(
            source_url=f'https://www.instagram.com/p/{post.shortcode}/',
            content_type=InstaloaderService._classify(post, bucket),
            # The true credit, which for a co-authored post is the
            # collaborator rather than the profile being browsed.
            author_username=post.owner_username,
            profile_username=profile_username,
            caption=post.caption or None,
            # post.url is the full-size original; only fall back to it when
            # the timeline struct offers nothing smaller.
            thumbnail_url=InstaloaderService._pick_thumbnail(
                InstaloaderService._media_struct(post), fallback=post.url,
            ),
            external_id=post.shortcode,
            posted_at=post.date_utc.replace(tzinfo=timezone.utc),
        )

    @staticmethod
    def _media_struct(post: instaloader.Post) -> dict:
        """The raw Instagram media struct behind a timeline post, or {} when
        the post was not built from one. Read straight off the node rather
        than via instaloader's `Post._iphone_struct` property, which falls
        back to fetching `api/v1/media/<id>/info/` when the struct is absent
        -- an extra request per post is exactly what this module is avoiding.
        """
        node = getattr(post, '_node', None)  # noqa: SLF001 -- no public accessor
        struct = node.get('iphone_struct') if isinstance(node, dict) else None
        return struct if isinstance(struct, dict) else {}

    @staticmethod
    def _is_pinned(post: instaloader.Post) -> bool:
        """Pinned posts are served at the head of the timeline regardless of
        age, so they are the one documented exception to the feed being
        reverse-chronological -- live-verified against a real profile whose
        first three timeline entries were older than the fourth."""
        return bool(InstaloaderService._media_struct(post).get('timeline_pinned_user_ids'))

    @staticmethod
    def _collect_posts(
        posts,
        bucket: InstagramContentType,
        since: datetime | None,
        until: datetime | None,
        profile_username: str | None = None,
        limit: int = _DEFAULT_PAGE_SIZE,
    ) -> list[ProfileItemPreview]:
        """Read the profile timeline (the grid). Reels are NOT sourced from
        here -- see _collect_reels for why the two are separate."""
        previews: list[ProfileItemPreview] = []
        scanned = 0
        for post in posts:
            scanned += 1
            if scanned > _MAX_ITEMS_SCANNED:
                break

            post_date = post.date_utc.replace(tzinfo=timezone.utc)
            if until is not None and post_date > until:
                continue
            if since is not None and post_date < since:
                if InstaloaderService._is_pinned(post):
                    # Out of order by design, not the start of the older
                    # tail -- skip it without ending the scan.
                    continue
                # Everything after this point is even older, so stop reading
                # instead of paging through a profile's entire history.
                break
            previews.append(InstaloaderService._post_to_preview(post, bucket, profile_username))
            if len(previews) >= limit:
                # A full page. The caller turns this into a cursor and can
                # ask for the next one -- unlike the old behaviour, which
                # silently truncated here and gave no way to see the rest.
                #
                # The limit applies even with a date range: "everything since
                # 2019" is otherwise an unbounded walk of a profile's whole
                # history in one request, which is how this took minutes
                # before.
                break
        return previews

    @staticmethod
    def _media_pk_to_datetime(pk: int) -> datetime:
        """Approximate post time recovered from an Instagram media pk -- see
        _IG_ID_EPOCH_MS."""
        millis = (pk >> _IG_ID_TIMESTAMP_SHIFT) + _IG_ID_EPOCH_MS
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)

    @staticmethod
    def _pick_thumbnail(media: dict, fallback: str | None = None) -> str | None:
        """Smallest rendition at least _THUMBNAIL_TARGET_WIDTH wide, falling
        back to the largest available when every candidate is smaller.

        Instagram lists candidates largest-first and mixes aspect ratios
        (a 4:5 set followed by a square set), so this sorts by width rather
        than trusting the order.
        """
        candidates = (media.get('image_versions2') or {}).get('candidates') or []
        sized = [
            (candidate.get('width') or 0, candidate['url'])
            for candidate in candidates
            if isinstance(candidate, dict) and candidate.get('url')
        ]
        if not sized:
            return fallback
        big_enough = [entry for entry in sized if entry[0] >= _THUMBNAIL_TARGET_WIDTH]
        chosen = min(big_enough, key=lambda entry: entry[0]) if big_enough else max(sized, key=lambda entry: entry[0])
        return chosen[1]

    @staticmethod
    def _reel_to_preview(media: dict, username: str | None) -> ProfileItemPreview | None:
        code = media.get('code')
        pk = media.get('pk')
        if not code or pk is None:
            return None
        try:
            posted_at = InstaloaderService._media_pk_to_datetime(int(pk))
        except (TypeError, ValueError):
            return None
        return ProfileItemPreview(
            source_url=f'https://www.instagram.com/reel/{code}/',
            content_type=InstagramContentType.REEL.value,
            # The reels connection identifies the owner by numeric pk only,
            # with no username, so this is the profile being browsed. That is
            # also what we want for the download folder -- see
            # _target_directory.
            author_username=username,
            profile_username=username,
            # Not in the connection payload at any depth; filled in at
            # download time. See _IG_ID_EPOCH_MS.
            caption=None,
            thumbnail_url=InstaloaderService._pick_thumbnail(media),
            external_id=code,
            posted_at=posted_at,
        )

    def _collect_reels(
        self,
        loader: instaloader.Instaloader,
        profile: instaloader.Profile,
        since: datetime | None,
        until: datetime | None,
        limit: int = _DEFAULT_PAGE_SIZE,
    ) -> list[ProfileItemPreview]:
        """Page the reels connection directly, building previews from the raw
        media struct rather than letting instaloader refetch each reel."""
        iterator = instaloader.NodeIterator(
            context=loader.context,
            query_hash=None,
            doc_id=_REELS_DOC_ID,
            edge_extractor=lambda data: data['data'][_REELS_CONNECTION_KEY],
            # The whole point: hand back the raw struct instead of
            # Post.from_shortcode(), which is one HTTP request per reel.
            node_wrapper=lambda node: node.get('media') or {},
            query_variables={'data': {
                'page_size': _REELS_PAGE_SIZE,
                'include_feed_video': True,
                'target_user_id': str(profile.userid),
            }},
            query_referer=f'https://www.instagram.com/{profile.username}/',
        )

        previews: list[ProfileItemPreview] = []
        scanned = 0
        for media in iterator:
            scanned += 1
            if scanned > _MAX_ITEMS_SCANNED:
                break
            preview = self._reel_to_preview(media, profile.username)
            if preview is None or preview.posted_at is None:
                continue
            if until is not None and preview.posted_at > until:
                continue
            if since is not None and preview.posted_at < since:
                if media.get('clips_tab_pinned_user_ids'):
                    # Pinned to the top of the reels tab regardless of age,
                    # same exception the timeline has for pinned posts.
                    continue
                break
            previews.append(preview)
            if len(previews) >= limit:
                break
        return previews

    @staticmethod
    def _collect_stories(loader: instaloader.Instaloader, profile: instaloader.Profile) -> list[ProfileItemPreview]:
        previews: list[ProfileItemPreview] = []
        for story in loader.get_stories(userids=[profile.userid]):
            for item in story.get_items():
                previews.append(ProfileItemPreview(
                    # A story's media URL, not a page URL -- stories are
                    # ephemeral (Instagram expires them, commonly ~24h), so
                    # there is no stable "fetch again later" identifier the
                    # way a permanent post has a shortcode. Downloading this
                    # item works if done reasonably soon after preview;
                    # download() falls back to a direct fetch of this exact
                    # URL, which can fail once the story is gone. See
                    # docs_POCKETDL_ROADMAP.md Phase 5 for this tradeoff.
                    source_url=item.url,
                    content_type=InstagramContentType.STORY.value,
                    author_username=profile.username,
                    profile_username=profile.username,
                    caption=item.caption or None,
                    thumbnail_url=item.url,
                    external_id=str(item.mediaid),
                    posted_at=item.date_utc.replace(tzinfo=timezone.utc),
                ))
        return previews

    @staticmethod
    def _collect_highlights(loader: instaloader.Instaloader, profile: instaloader.Profile) -> list[ProfileItemPreview]:
        previews: list[ProfileItemPreview] = []
        for highlight in loader.get_highlights(profile):
            for item in highlight.get_items():
                previews.append(ProfileItemPreview(
                    # Same caveat as stories: a highlight's own items are
                    # sourced from stories and can still be removed by the
                    # owner, so this is a direct media URL, not a stable
                    # re-fetchable identifier.
                    source_url=item.url,
                    content_type=InstagramContentType.HIGHLIGHT.value,
                    author_username=profile.username,
                    profile_username=profile.username,
                    caption=item.caption or highlight.title or None,
                    thumbnail_url=item.url,
                    external_id=str(item.mediaid),
                    posted_at=item.date_utc.replace(tzinfo=timezone.utc),
                ))
        return previews

    def _list_profile_items_sync(
        self,
        profile_url: str,
        content_types: list[InstagramContentType],
        since: datetime | None,
        until: datetime | None,
        limit: int,
    ) -> ProfileItemPage:
        loader = self._build_loader()
        username = self._profile_username(profile_url)

        try:
            profile = instaloader.Profile.from_username(loader.context, username)
        except instaloader.ProfileNotExistsException as exc:
            raise ValueError(f'Instagram profile "{username}" does not exist.') from exc
        except instaloader.LoginRequiredException as exc:
            raise InstagramAuthRequiredError(f'Instagram requires a session to look up this profile: {exc}') from exc
        except instaloader.ConnectionException as exc:
            raise RuntimeError(f'Could not reach Instagram: {exc}') from exc

        previews: list[ProfileItemPreview] = []
        has_more = False
        seen_buckets: set[InstagramContentType] = set()
        for content_type in content_types:
            bucket = InstagramContentType.POST if content_type is InstagramContentType.CAROUSEL else content_type
            if bucket in seen_buckets:
                continue
            seen_buckets.add(bucket)

            try:
                if bucket is InstagramContentType.STORY:
                    # Stories and highlights are small, bounded sets (a
                    # profile has at most a day's stories and a handful of
                    # highlights), so they are never paged.
                    previews.extend(self._collect_stories(loader, profile))
                elif bucket is InstagramContentType.HIGHLIGHT:
                    previews.extend(self._collect_highlights(loader, profile))
                else:
                    if bucket is InstagramContentType.REEL:
                        page = self._collect_reels(loader, profile, since, until, limit)
                    else:
                        page = self._collect_posts(
                            profile.get_posts(), bucket, since, until, profile.username, limit,
                        )
                    # A bucket that exactly filled its page is the only
                    # reason to believe there is more behind it.
                    has_more = has_more or len(page) >= limit
                    previews.extend(page)
            except instaloader.LoginRequiredException as exc:
                raise InstagramAuthRequiredError(f'Instagram requires a session to view this content: {exc}') from exc
            except instaloader.PrivateProfileNotFollowedException as exc:
                raise InstagramAuthRequiredError(
                    f'This profile is private and the configured session does not follow it: {exc}',
                ) from exc
            except instaloader.TooManyRequestsException as exc:
                raise RuntimeError(f'Instagram is rate-limiting this session: {exc}') from exc
            except instaloader.ConnectionException as exc:
                raise RuntimeError(f'Could not reach Instagram: {exc}') from exc

        return ProfileItemPage(items=previews, has_more=has_more)

    async def list_profile_items(
        self,
        profile_url: str,
        content_types: list[InstagramContentType],
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = _DEFAULT_PAGE_SIZE,
    ) -> ProfileItemPage:
        limit = max(1, min(limit, _MAX_PAGE_SIZE))
        # A bigger page is more requests, so it gets proportionally longer --
        # otherwise asking for 200 items would reliably fail at 90s having
        # already done most of the work.
        timeout = _OVERALL_TIMEOUT_SECONDS if limit <= _DEFAULT_PAGE_SIZE else _LARGE_PAGE_TIMEOUT_SECONDS
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._list_profile_items_sync, profile_url, content_types, since, until, limit),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise InstaloaderTimeoutError(
                f'Instagram did not respond within {timeout:.0f}s. It may be rate-limiting this '
                'session or temporarily slow -- try again shortly, or ask for fewer items.',
            ) from exc

    def _target_directory(self, username: str | None, content_type: str | None) -> Path:
        """`username` is the profile the item was discovered under, not
        necessarily the post's own owner: Instagram attributes a co-authored
        post to the collaborator, so keying the folder on `post.owner_username`
        scattered one profile's download across other people's folders
        (live-verified -- a post browsed on `nasa` reported `nasajohnson`).
        See docs_POCKETDL_ROADMAP.md Phase 5 "Round 7".
        """
        folder = _CONTENT_TYPE_FOLDERS.get(content_type or '', 'Posts')
        directory = self.settings.download_directory.joinpath('Instagram', username or 'unknown', folder)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _download_sync(self, job: DownloadJob, username: str | None, content_type: str | None) -> DownloadResult:
        target_dir = self._target_directory(username, content_type)
        loader = self._build_loader(target_dir)

        parsed = urlparse(job.url)
        is_page_url = 'instagram.com' in parsed.netloc and ('/p/' in parsed.path or '/reel/' in parsed.path)
        if is_page_url:
            shortcode = [part for part in parsed.path.split('/') if part][-1]
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
            # `target` no longer selects the directory (dirname_pattern above
            # is already the literal target path); it only fills {target} in
            # filename patterns, which this module's does not reference.
            loader.download_post(post, target=shortcode)
            # A carousel post downloads multiple files (one per sidecar
            # item); job.output_path only shows one representative file --
            # all of them still land on disk, this just doesn't enumerate
            # them for display, matching output_path's existing single-path
            # shape everywhere else in this codebase.
            # _FILENAME_PATTERN puts the date first, so the shortcode is
            # in the middle of the name rather than at the start.
            matches = sorted(
                (path for path in target_dir.glob(f'*{shortcode}*') if path.suffix.lower() != '.txt'),
                key=lambda path: path.stat().st_mtime, reverse=True,
            )
            caption = None
            posted_at = None
            try:
                caption = post.caption or None
                posted_at = post.date_utc.replace(tzinfo=timezone.utc)
            except Exception:  # noqa: BLE001 -- metadata is a bonus, never a reason to fail a saved file
                pass

            if not matches:
                # download_post() returns True even when nothing reached
                # disk, so an empty target directory is the only reliable
                # signal that the download did not actually happen. Raise
                # rather than return None: download() would otherwise mark
                # the job COMPLETED with no file, which is how the
                # sanitized-path bug above stayed invisible.
                raise RuntimeError(
                    f'Instagram post {shortcode} reported success but no file was written to {target_dir}.',
                )
            return DownloadResult(output_path=str(matches[0]), caption=caption, posted_at=posted_at)

        # Not a page URL -- a direct story/highlight media URL captured at
        # preview time (see _collect_stories/_collect_highlights). No
        # stable identifier to re-fetch through instaloader's own
        # structures, so this is a direct authenticated fetch of that exact
        # URL, which can fail if the story/highlight item is gone by now.
        stem = sanitize_filename(job.filename) if job.filename else sanitize_filename(job.title or f'instagram-{job.id[:8]}')
        extension = Path(parsed.path).suffix or '.mp4'
        output_path = target_dir / f'{stem}{extension}'
        loader.context.get_and_write_raw(job.url, str(output_path))
        # A story/highlight item is a bare media URL with no post behind it,
        # so there is no richer metadata to learn here.
        return DownloadResult(output_path=str(output_path))

    async def download(
        self,
        job: DownloadJob,
        *,
        context: RequestContext,
        retries: int,
        on_progress: ProgressCallback,
        collection_item_id: str | None = None,
    ) -> DownloadJob:
        job.status = DownloadStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.error = None
        job.error_details = None
        job.error_category = None
        job.exit_code = None
        await on_progress(job)

        username: str | None = None
        content_type: str | None = None
        if collection_item_id and self.collection_repository:
            item = await self.collection_repository.get_item(collection_item_id)
            if item is not None:
                # profile_username first: see _target_directory. Falls back to
                # author_username for items saved before that column existed.
                username = item.profile_username or item.author_username
                content_type = item.content_type

        result: DownloadResult | None = None
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._download_sync, job, username, content_type),
                timeout=_DOWNLOAD_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            self._fail(
                job, f'Instagram download timed out after {_DOWNLOAD_TIMEOUT_SECONDS:.0f}s.',
                DownloadErrorCategory.NETWORK_ERROR,
            )
        except instaloader.LoginRequiredException as exc:
            self._fail(job, f'Instagram requires a session: {exc}', DownloadErrorCategory.AUTHENTICATION_REQUIRED)
        except instaloader.PrivateProfileNotFollowedException as exc:
            self._fail(
                job, f'This profile is private and not followed by the configured session: {exc}',
                DownloadErrorCategory.AUTHENTICATION_REQUIRED,
            )
        except instaloader.TooManyRequestsException as exc:
            self._fail(job, f'Instagram is rate-limiting this session: {exc}', DownloadErrorCategory.RATE_LIMITED)
        except instaloader.ConnectionException as exc:
            self._fail(job, f'Could not reach Instagram: {exc}', DownloadErrorCategory.NETWORK_ERROR)
        except instaloader.InstaloaderException as exc:
            self._fail(job, f'Instagram download failed: {exc}', DownloadErrorCategory.UNKNOWN)
        except Exception as exc:  # noqa: BLE001 -- last resort, still recorded on the job rather than raised
            self._fail(job, f'Instagram download failed: {exc}', DownloadErrorCategory.UNKNOWN)
        else:
            output_path = result.output_path if result else None
            if not output_path or not Path(output_path).exists():
                self._fail(
                    job, 'Instagram download reported success but produced no file.',
                    DownloadErrorCategory.UNKNOWN,
                )
                job.finished_at = datetime.now(timezone.utc)
                await on_progress(job)
                return job
            job.status = DownloadStatus.COMPLETED
            job.progress = 100.0
            job.output_path = output_path
            # instaloader gives no progress bytes, so the UI showed "0 B" on a
            # finished download. Report the written file's size (both counters,
            # since it's complete) so it reads "5.2 MB / 5.2 MB". A carousel's
            # extra images aren't summed -- this is the primary file -- but any
            # real size beats a misleading zero.
            try:
                size = Path(output_path).stat().st_size
                job.downloaded_bytes = size
                job.total_bytes = size
            except OSError:
                pass
            job.error = None
            job.error_details = None
            job.error_category = None
            if collection_item_id and self.collection_repository and result is not None:
                await self.collection_repository.update_item_metadata(
                    collection_item_id, caption=result.caption, posted_at=result.posted_at,
                )

        job.finished_at = datetime.now(timezone.utc)
        await on_progress(job)
        return job

    @staticmethod
    def _fail(job: DownloadJob, message: str, category: DownloadErrorCategory) -> None:
        job.status = DownloadStatus.FAILED
        job.error = message
        job.error_details = message
        job.error_category = category

    async def cancel(self, job_id: str) -> None:
        # instaloader runs synchronously on a background thread
        # (asyncio.to_thread), not as a killable subprocess -- there is no
        # way to forcibly interrupt a request already in flight. A future
        # cooperative-cancellation flag checked between posts would only
        # help a multi-item download loop, which this single-item download()
        # does not have.
        return None
