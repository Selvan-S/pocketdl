"""Retrying a failed or cancelled download (product-polish Round 1).

A retry re-queues the existing job with the options and context it was
created with -- for a standard yt-dlp job that also resumes its partial
.part file, since yt-dlp's --continue is on by default and the output
template is unchanged. Retry state lives only in memory, so it is available
exactly while the job stays retryable and is dropped once it completes or is
forgotten.
"""

import pytest

from app.application.downloads.service import QueueService
from app.domain.models import DownloadJob, DownloadStatus, RequestContext


class InMemoryDownloadRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, DownloadJob] = {}

    async def add(self, job: DownloadJob) -> None:
        self.jobs[job.id] = job

    async def get(self, job_id: str) -> DownloadJob | None:
        return self.jobs.get(job_id)

    async def list(self) -> list[DownloadJob]:
        return list(self.jobs.values())

    async def update(self, job: DownloadJob) -> None:
        self.jobs[job.id] = job

    async def delete(self, job_id: str) -> None:
        self.jobs.pop(job_id, None)


class ScriptedDownloader:
    """Ends each attempt with the next status from a list, so a job can be
    made to fail once then succeed on retry. Records how many runs happened."""

    def __init__(self, statuses: list[DownloadStatus]) -> None:
        self._statuses = list(statuses)
        self.runs = 0

    async def download(self, job: DownloadJob, *, on_progress, **kwargs) -> DownloadJob:
        job.status = self._statuses[min(self.runs, len(self._statuses) - 1)]
        self.runs += 1
        await on_progress(job)
        return job

    async def cancel(self, job_id: str) -> None:
        pass


async def _make_failed_job() -> tuple[QueueService, ScriptedDownloader, DownloadJob]:
    repository = InMemoryDownloadRepository()
    downloader = ScriptedDownloader([DownloadStatus.FAILED, DownloadStatus.COMPLETED])
    service = QueueService(repository, downloader, max_concurrent=1)
    job = await service.create(
        url='https://example.com/video',
        filename=None,
        preset='best',
        concurrent_fragments=1,
        retries=1,
        use_aria2=False,
        request_context=RequestContext(),
    )
    await service.tasks[job.id]
    assert job.status is DownloadStatus.FAILED
    return service, downloader, job


@pytest.mark.asyncio
async def test_retry_reruns_a_failed_job() -> None:
    service, downloader, job = await _make_failed_job()

    retried = await service.retry(job.id)
    assert retried is not None
    await service.tasks[job.id]

    assert downloader.runs == 2
    assert (await service.repository.get(job.id)).status is DownloadStatus.COMPLETED


@pytest.mark.asyncio
async def test_retry_clears_prior_error_state() -> None:
    service, _downloader, job = await _make_failed_job()
    job.error = 'ERROR: boom'
    job.error_details = 'stack trace'
    await service.repository.update(job)

    await service.retry(job.id)
    reset = await service.repository.get(job.id)

    assert reset.error is None
    assert reset.error_details is None
    assert reset.error_category is None
    assert reset.exit_code is None
    assert reset.finished_at is None


@pytest.mark.asyncio
async def test_retry_of_a_completed_job_is_rejected() -> None:
    repository = InMemoryDownloadRepository()
    downloader = ScriptedDownloader([DownloadStatus.COMPLETED])
    service = QueueService(repository, downloader, max_concurrent=1)
    job = await service.create(
        url='https://example.com/video', filename=None, preset='best',
        concurrent_fragments=1, retries=1, use_aria2=False, request_context=RequestContext(),
    )
    await service.tasks[job.id]

    with pytest.raises(ValueError):
        await service.retry(job.id)


@pytest.mark.asyncio
async def test_completed_job_drops_its_retry_state() -> None:
    # A completed job never needs retrying, so its options/context are not
    # retained -- this is what bounds retention to the retryable set.
    repository = InMemoryDownloadRepository()
    downloader = ScriptedDownloader([DownloadStatus.COMPLETED])
    service = QueueService(repository, downloader, max_concurrent=1)
    job = await service.create(
        url='https://example.com/video', filename=None, preset='best',
        concurrent_fragments=1, retries=1, use_aria2=False, request_context=RequestContext(),
    )
    await service.tasks[job.id]

    assert job.id not in service.options
    assert job.id not in service.contexts


@pytest.mark.asyncio
async def test_forget_drops_retained_retry_state() -> None:
    service, _downloader, job = await _make_failed_job()
    assert job.id in service.options

    service.forget(job.id)

    assert job.id not in service.options
    assert job.id not in service.contexts
    with pytest.raises(ValueError):
        await service.retry(job.id)


@pytest.mark.asyncio
async def test_retry_of_an_unknown_job_returns_none() -> None:
    repository = InMemoryDownloadRepository()
    service = QueueService(repository, ScriptedDownloader([DownloadStatus.COMPLETED]), max_concurrent=1)

    assert await service.retry('nope') is None
