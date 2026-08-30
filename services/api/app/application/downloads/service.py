import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from ...core.filenames import sanitize_filename
from ...domain.errors import DownloadErrorCategory
from ...domain.models import DownloadEngine, DownloadJob, DownloadSourceType, DownloadStatus, MediaOptions, RequestContext
from ...domain.ports import CaptureRepository, CollectionRepository, DownloadRepository, Downloader


# The terminal states a download can be retried from. A running/queued job
# is already in flight; a completed one has nothing to redo.
_RETRYABLE_STATUSES = {DownloadStatus.FAILED, DownloadStatus.CANCELLED}


@dataclass(frozen=True, slots=True)
class JobOptions:
    """Per-job downloader settings held until the queued job actually runs."""

    preset: str
    format_id: str | None
    concurrent_fragments: int
    retries: int
    use_aria2: bool
    source_type: DownloadSourceType
    capture_id: str | None
    audio_url: str | None
    collection_item_id: str | None
    media_options: MediaOptions = MediaOptions()


class QueueService:
    def __init__(
        self,
        repository: DownloadRepository,
        downloader: Downloader,
        max_concurrent: int,
        capture_repository: CaptureRepository | None = None,
        collection_repository: CollectionRepository | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        # Fired on every progress update so a subscriber (the SSE stream) can
        # push instead of being polled. Progress changes state without any
        # HTTP request, so it is the one place the request middleware cannot
        # cover. Optional so tests can construct a queue without one.
        self._on_change = on_change
        self.repository = repository
        self.downloader = downloader
        self.capture_repository = capture_repository
        self.collection_repository = collection_repository
        self.semaphore = asyncio.Semaphore(max(1, max_concurrent))
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.contexts: dict[str, RequestContext] = {}
        self.options: dict[str, JobOptions] = {}

    async def _record_progress(self, job: DownloadJob) -> None:
        await self.repository.update(job)
        if self._on_change is not None:
            self._on_change()

    async def create(
        self,
        url: str,
        filename: str | None,
        preset: str,
        concurrent_fragments: int,
        retries: int,
        use_aria2: bool,
        request_context: RequestContext,
        source_type: DownloadSourceType = DownloadSourceType.STANDARD,
        capture_id: str | None = None,
        title: str | None = None,
        format_id: str | None = None,
        audio_url: str | None = None,
        engine: DownloadEngine = DownloadEngine.YT_DLP,
        collection_item_id: str | None = None,
        media_options: MediaOptions = MediaOptions(),
    ) -> DownloadJob:
        normalized_filename = sanitize_filename(filename) if filename else None
        if not normalized_filename and title:
            normalized_filename = sanitize_filename(title)
        job = DownloadJob(
            id=uuid.uuid4().hex,
            url=url,
            filename=normalized_filename,
            title=title,
            status=DownloadStatus.QUEUED,
            progress=0,
            downloaded_bytes=0,
            total_bytes=None,
            speed_bytes=None,
            eta_seconds=None,
            output_path=None,
            error=None,
            error_details=None,
            error_category=None,
            exit_code=None,
            retry_count=0,
            impersonation=request_context.impersonation,
            referer=request_context.referer,
            origin=request_context.origin,
            user_agent=request_context.user_agent,
            source_type=source_type,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            finished_at=None,
            capture_id=capture_id,
            engine=engine,
            collection_item_id=collection_item_id,
        )
        await self.repository.add(job)
        self.contexts[job.id] = request_context
        self.options[job.id] = JobOptions(
            preset=preset,
            format_id=format_id,
            concurrent_fragments=concurrent_fragments,
            retries=retries,
            use_aria2=use_aria2,
            source_type=source_type,
            capture_id=capture_id,
            audio_url=audio_url,
            collection_item_id=collection_item_id,
            media_options=media_options,
        )
        self.tasks[job.id] = asyncio.create_task(self._run(job.id))
        return job

    async def _run(self, job_id: str) -> None:
        try:
            async with self.semaphore:
                latest = await self.repository.get(job_id)
                if latest is None:
                    return
                options = self.options[job_id]
                capture_id = options.capture_id
                collection_item_id = options.collection_item_id
                request_context = self.contexts[job_id]
                await self.downloader.download(
                    latest,
                    preset=options.preset,
                    format_id=options.format_id,
                    concurrent_fragments=options.concurrent_fragments,
                    retries=options.retries,
                    use_aria2=options.use_aria2,
                    request_context=request_context,
                    source_type=options.source_type,
                    capture_id=capture_id,
                    audio_url=options.audio_url,
                    collection_item_id=collection_item_id,
                    media_options=options.media_options,
                    on_progress=self._record_progress,
                )
                if capture_id and self.capture_repository:
                    finished = await self.repository.get(job_id)
                    if finished is not None and finished.status is DownloadStatus.COMPLETED:
                        await self.capture_repository.mark_downloaded(capture_id)
                if collection_item_id and self.collection_repository:
                    finished = await self.repository.get(job_id)
                    if finished is not None and finished.status is DownloadStatus.COMPLETED:
                        await self.collection_repository.mark_item_downloaded(collection_item_id, job_id)
                        # The COMPLETED progress tick already fired on_change,
                        # but that was *before* this row moved to downloaded --
                        # so a playlist's downloaded_count would otherwise lag
                        # to the next heartbeat. Nudge the stream again now.
                        if self._on_change is not None:
                            self._on_change()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A downloader that raises instead of returning a failed job (a
            # missing ffmpeg/yt-dlp binary is the common case) used to leave
            # the job sitting at "running" forever, with the reason visible
            # only in the server log.
            job = await self.repository.get(job_id)
            if job is not None and job.status not in {DownloadStatus.COMPLETED, DownloadStatus.CANCELLED}:
                job.status = DownloadStatus.FAILED
                job.error = f'{type(exc).__name__}: {exc}'
                job.error_details = str(exc)
                job.error_category = DownloadErrorCategory.UNKNOWN
                job.finished_at = datetime.now(timezone.utc)
                await self.repository.update(job)
        finally:
            self.tasks.pop(job_id, None)
            # Keep a job's context and options iff it ended FAILED or
            # CANCELLED, so it can be retried -- and, for yt-dlp, resume its
            # partial .part file, which survives on disk. A COMPLETED job
            # never needs them again, so those are dropped, bounding retention
            # to the small set of retryable jobs. delete() -> forget() clears
            # the rest. (Retry state is in-memory only: a backend restart
            # loses it, same as the queue's running tasks.)
            final = await self.repository.get(job_id)
            if final is None or final.status not in _RETRYABLE_STATUSES:
                self.contexts.pop(job_id, None)
                self.options.pop(job_id, None)

    async def cancel(self, job_id: str) -> DownloadJob | None:
        job = await self.repository.get(job_id)
        if job is None:
            return None
        if job.status in {DownloadStatus.QUEUED, DownloadStatus.RUNNING}:
            job.status = DownloadStatus.CANCELLED
            job.finished_at = datetime.now(timezone.utc)
            await self.repository.update(job)
            await self.downloader.cancel(job_id)
        return job

    async def retry(self, job_id: str) -> DownloadJob | None:
        """Re-queue a failed or cancelled job with its original options.

        For a standard (yt-dlp) job this resumes the partial download rather
        than starting over: yt-dlp's `--continue` is on by default and the
        output template is unchanged, so it picks up the `.part` file left on
        disk. Captured (ffmpeg) jobs restart, since ffmpeg has no equivalent.

        Raises ValueError (surfaced as 409) when the job is not in a
        retryable state, or when its retry state is gone -- options and
        context live only in memory, so a job cannot be retried after a
        backend restart; re-adding it is the path then.
        """
        job = await self.repository.get(job_id)
        if job is None:
            return None
        if job.status not in _RETRYABLE_STATUSES:
            raise ValueError('Only a failed or cancelled download can be retried.')
        if job_id not in self.options or job_id not in self.contexts:
            raise ValueError('This download can no longer be retried; re-add it instead.')

        job.status = DownloadStatus.QUEUED
        job.error = None
        job.error_details = None
        job.error_category = None
        job.exit_code = None
        job.progress = 0.0
        job.downloaded_bytes = 0
        job.speed_bytes = None
        job.eta_seconds = None
        job.started_at = None
        job.finished_at = None
        await self.repository.update(job)
        self.tasks[job_id] = asyncio.create_task(self._run(job_id))
        if self._on_change is not None:
            self._on_change()
        return job

    def forget(self, job_id: str) -> None:
        """Drop retained retry state for a job being deleted, so the option
        and context maps don't hold rows for downloads that no longer exist."""
        self.contexts.pop(job_id, None)
        self.options.pop(job_id, None)

    async def shutdown(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        self.contexts.clear()
        self.options.clear()
