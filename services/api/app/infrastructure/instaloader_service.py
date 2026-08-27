import asyncio
from collections.abc import Awaitable, Callable
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


class InstaloaderService:
    """Instagram-specific engine: precise, typed exceptions and native
    date filtering, in exchange for running in-process (a library call on a
    background thread via asyncio.to_thread) rather than as a subprocess --
    see domain/models.py's DownloadEngine docstring.
    """

    def __init__(self, settings: Settings, collection_repository: CollectionRepository | None = None) -> None:
        self.settings = settings
        self.collection_repository = collection_repository

    @staticmethod
    def version() -> str:
        return instaloader.__version__

    def _build_loader(self) -> instaloader.Instaloader:
        loader = instaloader.Instaloader(
            sleep=True,
            quiet=True,
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
        )
        pairs = load_cookie_pairs(self.settings.database_path, 'instagram')
        if pairs:
            loader.context.update_cookies(pairs)
        return loader

    async def test_session(self) -> str | None:
        """Verify the stored session cookie actually authenticates,
        returning the logged-in username, or None if it does not (missing,
        expired, or rejected). Lets the UI confirm a pasted cookie works
        immediately instead of finding out mid-preview."""
        return await asyncio.to_thread(self._test_session_sync)

    def _test_session_sync(self) -> str | None:
        loader = self._build_loader()
        if not load_cookie_pairs(self.settings.database_path, 'instagram'):
            return None
        return loader.context.test_login()

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
    def _collect_posts(
        posts, bucket: InstagramContentType, since: datetime | None, until: datetime | None,
    ) -> list[ProfileItemPreview]:
        previews: list[ProfileItemPreview] = []
        for post in posts:
            post_date = post.date_utc.replace(tzinfo=timezone.utc)
            if until is not None and post_date > until:
                continue
            if since is not None and post_date < since:
                # Instagram feeds are reverse-chronological -- everything
                # after this point is even older, so stop reading instead
                # of paging through a profile's entire history.
                break
            previews.append(InstaloaderService._post_to_preview(post, bucket))
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
                elif bucket is InstagramContentType.REEL:
                    previews.extend(self._collect_posts(profile.get_reels(), bucket, since, until))
                else:
                    previews.extend(self._collect_posts(profile.get_posts(), bucket, since, until))
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
        return await asyncio.to_thread(self._list_profile_items_sync, profile_url, content_types, since, until)

    def _target_directory(self, username: str | None, content_type: str | None) -> Path:
        folder = _CONTENT_TYPE_FOLDERS.get(content_type or '', 'Posts')
        directory = self.settings.download_directory.joinpath('Instagram', username or 'unknown', folder)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _download_sync(self, job: DownloadJob, username: str | None, content_type: str | None) -> str | None:
        loader = self._build_loader()
        target_dir = self._target_directory(username, content_type)

        parsed = urlparse(job.url)
        is_page_url = 'instagram.com' in parsed.netloc and ('/p/' in parsed.path or '/reel/' in parsed.path)
        if is_page_url:
            shortcode = [part for part in parsed.path.split('/') if part][-1]
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
            loader.download_post(post, target=str(target_dir))
            # A carousel post downloads multiple files (one per sidecar
            # item); job.output_path only shows one representative file --
            # all of them still land on disk, this just doesn't enumerate
            # them for display, matching output_path's existing single-path
            # shape everywhere else in this codebase.
            matches = sorted(target_dir.glob(f'{shortcode}_*'), key=lambda p: p.stat().st_mtime, reverse=True)
            return str(matches[0]) if matches else None

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
            output_path = await asyncio.to_thread(self._download_sync, job, username, content_type)
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
