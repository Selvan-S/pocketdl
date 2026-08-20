import asyncio
import uuid
from datetime import datetime, timezone

from ...core.filenames import sanitize_filename
from ...domain.models import DownloadJob, DownloadSourceType, DownloadStatus, RequestContext
from ...domain.ports import CaptureRepository, DownloadRepository, Downloader


class QueueService:
    def __init__(
        self,
        repository: DownloadRepository,
        downloader: Downloader,
        max_concurrent: int,
        capture_repository: CaptureRepository | None = None,
    ) -> None:
        self.repository = repository
        self.downloader = downloader
        self.capture_repository = capture_repository
        self.semaphore = asyncio.Semaphore(max(1, max_concurrent))
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.contexts: dict[str, RequestContext] = {}
        self.options: dict[str, tuple[str, str | None, int, int, bool, DownloadSourceType, str | None]] = {}

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
        )
        await self.repository.add(job)
        self.contexts[job.id] = request_context
        self.options[job.id] = (preset, format_id, concurrent_fragments, retries, use_aria2, source_type, capture_id)
        self.tasks[job.id] = asyncio.create_task(self._run(job.id))
        return job

    async def _run(self, job_id: str) -> None:
        try:
            async with self.semaphore:
                latest = await self.repository.get(job_id)
                if latest is None:
                    return
                preset, format_id, concurrent_fragments, retries, use_aria2, source_type, capture_id = self.options[job_id]
                request_context = self.contexts[job_id]
                await self.downloader.download(
                    latest,
                    preset=preset,
                    format_id=format_id,
                    concurrent_fragments=concurrent_fragments,
                    retries=retries,
                    use_aria2=use_aria2,
                    request_context=request_context,
                    source_type=source_type,
                    capture_id=capture_id,
                    on_progress=self.repository.update,
                )
                if capture_id and self.capture_repository:
                    finished = await self.repository.get(job_id)
                    if finished is not None and finished.status is DownloadStatus.COMPLETED:
                        await self.capture_repository.mark_downloaded(capture_id)
        finally:
            self.tasks.pop(job_id, None)
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

    async def shutdown(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
        self.tasks.clear()
        self.contexts.clear()
        self.options.clear()
