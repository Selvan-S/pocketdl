import asyncio
from collections.abc import Awaitable, Callable
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

# instaloader's own filename pattern language (see Instaloader.filename_pattern) --
# shortcode-based instead of the date_utc default, for stable, readable
# filenames matching this project's "no raw signed/opaque names" filename
# policy (see docs_POCKETDL_ROADMAP.md Phase 3).
_FILENAME_PATTERN = '{shortcode}_{typename}'

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


# When no `since` bound is given, there is nothing to naturally stop
# pagination early -- an active profile's full post/reel history can be
# dozens of pages. Cap to a recent window instead; explicitly narrowing
# the date range still works via the ordinary early-break above this.
_MAX_ITEMS_WITHOUT_DATE_RANGE = 50

# Reels are read by filtering the ordinary profile timeline rather than by
# instaloader's own `Profile.get_reels()` -- see `_collect_posts`. Filtering
# means the number of *posts scanned* is larger than the number of reels
# kept, so pagination needs its own separate ceiling: without one, a profile
# that posts rarely-but-not-never in video form would page through its whole
# history looking for reels that aren't there.
#
# Sized against _OVERALL_TIMEOUT_SECONDS rather than picked round: the
# timeline returns 12 items per request, and a request plus instaloader's
# rate-limit courtesy sleep was measured live at ~3.5s, so 200 posts is
# ~17 requests is ~60s -- inside the 90s budget with margin. Raising this
# without raising the timeout would just turn a truncated result into a
# timeout, which is strictly worse.
_MAX_POSTS_SCANNED = 200

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
            # save_metadata=False alone still leaves a per-post .txt caption
            # sidecar written by default (post_metadata_txt_pattern defaults
            # to '{caption}') -- caption is already stored in the DB
            # (CollectionItem.caption), so an extra file per download would
            # just clutter the folder.
            post_metadata_txt_pattern='',
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
    def _post_to_preview(post: instaloader.Post, bucket: InstagramContentType) -> ProfileItemPreview:
        return ProfileItemPreview(
            source_url=f'https://www.instagram.com/p/{post.shortcode}/',
            content_type=InstaloaderService._classify(post, bucket),
            author_username=post.owner_username,
            caption=post.caption or None,
            thumbnail_url=post.url,
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
    def _scan_timeline(
        posts,
        since: datetime | None,
        until: datetime | None,
        *,
        want_posts: bool,
        want_reels: bool,
    ) -> tuple[list[ProfileItemPreview], list[ProfileItemPreview]]:
        """Read the profile timeline once, filling the post and reel buckets
        together.

        Both buckets come from the same `Profile.get_posts()` stream, so
        scanning per-bucket paged the identical timeline twice and doubled
        both the wall-clock time and the rate-limit pressure for the common
        "everything" selection. Returns the two lists separately so the
        caller can order them by the content types it was asked for.

        A reel legitimately appears in both lists when both are requested:
        the reel bucket is a filtered view of the timeline, not a disjoint
        one, which is the pre-existing behaviour of asking for posts and
        reels at once.
        """
        post_previews: list[ProfileItemPreview] = []
        reel_previews: list[ProfileItemPreview] = []
        scanned = 0

        for post in posts:
            scanned += 1
            if scanned > _MAX_POSTS_SCANNED:
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

            is_clip = InstaloaderService._media_struct(post).get('product_type') == _CLIPS_PRODUCT_TYPE
            posts_open = want_posts and not (
                since is None and len(post_previews) >= _MAX_ITEMS_WITHOUT_DATE_RANGE
            )
            reels_open = want_reels and is_clip and not (
                since is None and len(reel_previews) >= _MAX_ITEMS_WITHOUT_DATE_RANGE
            )
            if posts_open:
                post_previews.append(InstaloaderService._post_to_preview(post, InstagramContentType.POST))
            if reels_open:
                reel_previews.append(InstaloaderService._post_to_preview(post, InstagramContentType.REEL))

            # With no lower date bound there is nothing to stop pagination
            # naturally -- live-verified as the dominant cause of a preview
            # taking minutes rather than a stalled connection, since
            # get_posts() will otherwise page an active profile's *entire*
            # history, one request plus a rate-limit courtesy sleep
            # (sleep=True) per page. Cap to a recent window for interactive
            # browsing; a real date range overrides it via the `break` above.
            if since is None:
                posts_done = not want_posts or len(post_previews) >= _MAX_ITEMS_WITHOUT_DATE_RANGE
                reels_done = not want_reels or len(reel_previews) >= _MAX_ITEMS_WITHOUT_DATE_RANGE
                if posts_done and reels_done:
                    break

        return post_previews, reel_previews

    @staticmethod
    def _collect_posts(
        posts,
        bucket: InstagramContentType,
        since: datetime | None,
        until: datetime | None,
        *,
        clips_only: bool = False,
    ) -> list[ProfileItemPreview]:
        """Single-bucket view of `_scan_timeline`, kept for callers (and
        tests) that only want one of the two."""
        post_previews, reel_previews = InstaloaderService._scan_timeline(
            posts, since, until, want_posts=not clips_only, want_reels=clips_only,
        )
        return reel_previews if clips_only else post_previews

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
    ) -> list[ProfileItemPreview]:
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
        seen_buckets: set[InstagramContentType] = set()
        timeline_buckets = {
            InstagramContentType.POST if content_type is InstagramContentType.CAROUSEL else content_type
            for content_type in content_types
        } & {InstagramContentType.POST, InstagramContentType.REEL}
        timeline_scan: tuple[list[ProfileItemPreview], list[ProfileItemPreview]] | None = None
        for content_type in content_types:
            bucket = InstagramContentType.POST if content_type is InstagramContentType.CAROUSEL else content_type
            if bucket in seen_buckets:
                continue
            seen_buckets.add(bucket)

            try:
                if bucket is InstagramContentType.STORY:
                    previews.extend(self._collect_stories(loader, profile))
                elif bucket is InstagramContentType.HIGHLIGHT:
                    previews.extend(self._collect_highlights(loader, profile))
                else:
                    # Both remaining buckets are views of the same timeline,
                    # so they are scanned together once, on whichever of the
                    # two is requested first.
                    #
                    # Deliberately NOT profile.get_reels() for the reel
                    # bucket: instaloader's reels connection returns a media
                    # struct with no taken_at/caption/owner, so its own
                    # node_wrapper issues a `Post.from_shortcode()` refetch
                    # per reel -- measured live at ~12s per reel including
                    # instaloader's rate-limit courtesy sleeps, i.e. ~10
                    # minutes for this module's 50-item cap. The ordinary
                    # timeline returns complete metadata 12 items per
                    # request, and its product_type=='clips' entries were
                    # verified to be exactly the same posts, in the same
                    # order, that get_reels() produced. See
                    # docs_POCKETDL_ROADMAP.md Phase 5 "Round 6".
                    if timeline_scan is None:
                        timeline_scan = self._scan_timeline(
                            profile.get_posts(), since, until,
                            want_posts=InstagramContentType.POST in timeline_buckets,
                            want_reels=InstagramContentType.REEL in timeline_buckets,
                        )
                    scanned_posts, scanned_reels = timeline_scan
                    previews.extend(scanned_reels if bucket is InstagramContentType.REEL else scanned_posts)
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

        return previews

    async def list_profile_items(
        self,
        profile_url: str,
        content_types: list[InstagramContentType],
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[ProfileItemPreview]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._list_profile_items_sync, profile_url, content_types, since, until),
                timeout=_OVERALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise InstaloaderTimeoutError(
                f'Instagram did not respond within {_OVERALL_TIMEOUT_SECONDS:.0f}s. It may be rate-limiting this '
                'session or temporarily slow -- try again shortly.',
            ) from exc

    def _target_directory(self, username: str | None, content_type: str | None) -> Path:
        folder = _CONTENT_TYPE_FOLDERS.get(content_type or '', 'Posts')
        directory = self.settings.download_directory.joinpath('Instagram', username or 'unknown', folder)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _download_sync(self, job: DownloadJob, username: str | None, content_type: str | None) -> str | None:
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
            matches = sorted(target_dir.glob(f'{shortcode}_*'), key=lambda p: p.stat().st_mtime, reverse=True)
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
            return str(matches[0])

        # Not a page URL -- a direct story/highlight media URL captured at
        # preview time (see _collect_stories/_collect_highlights). No
        # stable identifier to re-fetch through instaloader's own
        # structures, so this is a direct authenticated fetch of that exact
        # URL, which can fail if the story/highlight item is gone by now.
        stem = sanitize_filename(job.filename) if job.filename else sanitize_filename(job.title or f'instagram-{job.id[:8]}')
        extension = Path(parsed.path).suffix or '.mp4'
        output_path = target_dir / f'{stem}{extension}'
        loader.context.get_and_write_raw(job.url, str(output_path))
        return str(output_path)

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
                username = item.author_username
                content_type = item.content_type

        try:
            output_path = await asyncio.wait_for(
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
            job.error = None
            job.error_details = None
            job.error_category = None

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
