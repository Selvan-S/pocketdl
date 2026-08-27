import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..application.downloads.errors import classify_download_error
from ..core.config import Settings
from ..core.filenames import sanitize_filename
from ..core.media_paths import platform_media_path
from ..core.session_store import has_session_cookie, scrub_cookie_values, session_cookie_file
from ..domain.collections import InstagramContentType, ProfileItemPreview
from ..domain.models import DownloadJob, DownloadStatus, RequestContext
from ..domain.ports import CollectionRepository

ProgressCallback = Callable[[DownloadJob], Awaitable[None]]

# Instagram content_type values (see domain/collections.py) mapped to the
# folder-tree names from docs/instagram-full-profile-plan.md's "Folder
# organization" section.
_CONTENT_TYPE_FOLDERS = {
    'post': 'Posts',
    'carousel': 'Posts',
    'reel': 'Reels',
    'story': 'Stories',
    'highlight': 'Highlights',
}

# gallery-dl's --resolve-json/-J wire format is a stable, documented
# protocol (gallery_dl.extractor.message.Message): each top-level array
# entry is a tuple whose first element identifies the message kind.
_MESSAGE_DIRECTORY = 2  # (2, kwdict) -- grouping metadata, not an item
_MESSAGE_URL = 3  # (3, url, kwdict) -- one downloadable item
_MESSAGE_QUEUE = 6  # (6, url, kwdict) -- unresolved child extractor
_MESSAGE_ERROR = -1  # (-1, {"error": ..., "message": ...}) -- our own sentinel, see DataJob.run()

# Experimentally verified (2026-08-27, gallery-dl 1.32.9, no session cookie):
# a request against a real public Instagram profile does not come back as an
# ordinary 404/403 -- it comes back as this exact error, indistinguishable at
# a glance from "the username is actually wrong". Instagram's public,
# unauthenticated GraphQL lookup is effectively gone; every profile fetch
# needs a session cookie today, not just Stories/Highlights as originally
# assumed when this feature was designed. See
# docs/docs_POCKETDL_ROADMAP.md Phase 5 for the full note.
_AUTH_REQUIRED_MARKERS = ('notfounderror', 'login', 'checkpoint', '401', '403')


class InstagramAuthRequiredError(RuntimeError):
    """gallery-dl could not complete the request in a way that, in current
    practice, means the profile needs an authenticated session cookie."""


class GalleryDlService:
    """Mirrors YtDlpService's shape for the second (gallery-dl) engine:
    list_profile_items() for metadata-only discovery, download() for an
    actual fetch, version() for /system/status."""

    def __init__(self, settings: Settings, collection_repository: CollectionRepository | None = None) -> None:
        self.settings = settings
        self.collection_repository = collection_repository
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    @staticmethod
    def _tool_version_sync() -> str | None:
        try:
            import subprocess
            result = subprocess.run(
                [sys.executable, '-m', 'gallery_dl', '--version'],
                capture_output=True, text=True, timeout=10, check=False,
            )
            output = (result.stdout or result.stderr).splitlines()
            return output[0].strip() if output else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    async def version(self) -> str | None:
        return await asyncio.to_thread(self._tool_version_sync)

    def _cookie_args(self, platform: str) -> list[str]:
        if has_session_cookie(self.settings.database_path, platform):
            return ['--cookies', str(session_cookie_file(self.settings.database_path, platform))]
        return []

    @staticmethod
    def _profile_username(profile_url: str) -> str:
        parsed = urlparse(profile_url)
        username = parsed.path.strip('/').split('/')[0] if parsed.path else ''
        if not username:
            raise ValueError('profile_url must include a username, e.g. https://www.instagram.com/someuser/')
        return username

    @classmethod
    def _content_type_url(cls, profile_url: str, content_type: InstagramContentType) -> str:
        parsed = urlparse(profile_url)
        username = cls._profile_username(profile_url)
        root = f'{parsed.scheme}://{parsed.netloc}'
        if content_type is InstagramContentType.STORY:
            return f'{root}/stories/{username}/'
        if content_type is InstagramContentType.REEL:
            return f'{root}/{username}/reels/'
        if content_type is InstagramContentType.HIGHLIGHT:
            return f'{root}/{username}/highlights/'
        # POST and CAROUSEL share the same grid listing -- a carousel is a
        # kind of post, distinguished per item in _classify, not by URL.
        return f'{root}/{username}/posts/'

    @staticmethod
    def _classify(kwdict: dict, bucket: InstagramContentType) -> str:
        if bucket is not InstagramContentType.POST:
            return bucket.value
        if kwdict.get('typename') == 'GraphSidecar' or kwdict.get('sidecar_shortcode'):
            return InstagramContentType.CAROUSEL.value
        return InstagramContentType.POST.value

    def _preview_args(self, url: str) -> list[str]:
        return [
            sys.executable, '-m', 'gallery_dl',
            '--resolve-json',
            *self._cookie_args('instagram'),
            url,
        ]

    async def _run_json(self, args: list[str]) -> tuple[int, list, str]:
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
        stderr_text = stderr.decode(errors='replace').strip()
        if process.returncode != 0 and not stdout.strip():
            return process.returncode, [], stderr_text or f'gallery-dl exited with code {process.returncode}'
        try:
            payload = json.loads(stdout.decode(errors='replace') or '[]')
        except json.JSONDecodeError:
            return process.returncode, [], 'gallery-dl returned invalid JSON output.'
        return process.returncode, payload if isinstance(payload, list) else [], stderr_text

    async def list_profile_items(
        self, profile_url: str, content_types: list[InstagramContentType],
    ) -> list[ProfileItemPreview]:
        """Metadata-only discovery (``--resolve-json``, no download) for the
        requested content types. Nothing is persisted here -- the caller
        turns a chosen subset of the returned previews into CollectionItems.
        """
        previews: list[ProfileItemPreview] = []
        errors: list[str] = []
        fetched_urls: set[str] = set()

        for content_type in content_types:
            url = self._content_type_url(profile_url, content_type)
            if url in fetched_urls:
                continue
            fetched_urls.add(url)

            bucket = InstagramContentType.POST if content_type is InstagramContentType.CAROUSEL else content_type
            _, payload, stderr_text = await self._run_json(self._preview_args(url))
            if stderr_text and not payload:
                errors.append(stderr_text)

            for entry in payload:
                if not entry:
                    continue
                message_id = entry[0]
                if message_id == _MESSAGE_ERROR:
                    detail = entry[1] if len(entry) > 1 else {}
                    errors.append(f"{detail.get('error', 'Error')}: {detail.get('message', 'unknown error')}")
                    continue
                if message_id != _MESSAGE_URL:
                    continue  # Directory/Queue entries carry no downloadable item on their own

                url_value = entry[1] if len(entry) > 1 else url
                kwdict = entry[2] if len(entry) > 2 else {}
                shortcode = kwdict.get('post_shortcode') or kwdict.get('shortcode')
                previews.append(ProfileItemPreview(
                    source_url=kwdict.get('post_url') or url_value,
                    content_type=self._classify(kwdict, bucket),
                    author_username=kwdict.get('username'),
                    caption=kwdict.get('description') or kwdict.get('caption') or None,
                    thumbnail_url=kwdict.get('display_url') or kwdict.get('thumbnail') or None,
                    external_id=str(shortcode) if shortcode else None,
                ))

        if not previews and errors:
            joined = '; '.join(dict.fromkeys(errors))
            if any(marker in joined.lower() for marker in _AUTH_REQUIRED_MARKERS):
                raise InstagramAuthRequiredError(joined)
            raise RuntimeError(joined)
        return previews

    def _build_download_args(self, job: DownloadJob, username: str | None, content_type: str | None) -> list[str]:
        stem = sanitize_filename(job.filename) if job.filename else sanitize_filename(job.title or f'instagram-{job.id[:8]}')
        folder = _CONTENT_TYPE_FOLDERS.get(content_type or '', 'Posts')
        subfolders = [part for part in (username, folder) if part]
        # {extension} is gallery-dl's own filename-format placeholder, left
        # literal here for gallery-dl's -f to substitute -- the real
        # extension isn't known until gallery-dl inspects the post.
        target = platform_media_path(
            self.settings.download_directory, 'Instagram', *subfolders, filename=f'{stem}.{{extension}}',
        )
        return [
            sys.executable, '-m', 'gallery_dl',
            '--no-mtime',
            '-D', str(target.parent),
            '-f', target.name,
            *self._cookie_args('instagram'),
            job.url,
        ]

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

        args = self._build_download_args(job, username, content_type)
        output_lines: list[str] = []
        last_line = ''

        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        self._processes[job.id] = process
        try:
            assert process.stdout is not None
            async for raw_line in process.stdout:
                line = raw_line.decode(errors='replace').rstrip()
                if line:
                    output_lines.append(line)
                    last_line = line
                    # gallery-dl has no byte-level progress in its default
                    # (non-verbose) output -- each printed line is roughly
                    # one completed file, a coarser signal than yt-dlp's
                    # percent updates. See instagram-full-profile-plan.md.
                    job.progress = min(95.0, job.progress + 5.0)
                await on_progress(job)
            return_code = await process.wait()
        finally:
            self._processes.pop(job.id, None)

        if job.status is DownloadStatus.CANCELLED:
            return job

        combined_output = '\n'.join(output_lines)
        scrubbed_output = scrub_cookie_values(combined_output, self.settings.database_path, 'instagram')
        job.exit_code = return_code
        if return_code == 0:
            job.status = DownloadStatus.COMPLETED
            job.progress = 100.0
            job.output_path = last_line or None
            job.error = None
            job.error_details = None
            job.error_category = None
        else:
            job.status = DownloadStatus.FAILED
            job.error = f'gallery-dl exited with code {return_code}.'
            job.error_details = scrubbed_output.strip() or job.error
            job.error_category = classify_download_error(scrubbed_output)
        job.finished_at = datetime.now(timezone.utc)
        await on_progress(job)
        return job

    async def cancel(self, job_id: str) -> None:
        process = self._processes.get(job_id)
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
