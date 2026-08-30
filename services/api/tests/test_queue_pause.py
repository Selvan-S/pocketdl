"""Pause and resume a download (product-polish Round 4). Pause keeps the
partial file and marks the job PAUSED (not FAILED); resume re-queues it, and
for yt-dlp continues the .part."""

import asyncio

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


class BlockingDownloader:
    """Runs until cancel() releases it, then reports FAILED as a real
    downloader would when its process is killed."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self._release = asyncio.Event()
        self.cancelled = False

    async def download(self, job: DownloadJob, *, on_progress, **kwargs) -> DownloadJob:
        job.status = DownloadStatus.RUNNING
        await on_progress(job)
        self.started.set()
        await self._release.wait()
        job.status = DownloadStatus.FAILED
        await on_progress(job)
        return job

    async def cancel(self, job_id: str) -> None:
        self.cancelled = True
        self._release.set()


class ScriptedDownloader:
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


async def _create(service: QueueService) -> DownloadJob:
    return await service.create(
        url='https://example.com/video', filename=None, preset='best',
        concurrent_fragments=1, retries=1, use_aria2=False, request_context=RequestContext(),
    )


@pytest.mark.asyncio
async def test_pausing_a_running_job_records_paused_not_failed() -> None:
    repository = InMemoryDownloadRepository()
    downloader = BlockingDownloader()
    service = QueueService(repository, downloader, max_concurrent=1)

    job = await _create(service)
    await asyncio.wait_for(downloader.started.wait(), timeout=2)

    paused = await service.pause(job.id)
    assert paused is not None and paused.status is DownloadStatus.PAUSED
    assert downloader.cancelled is True

    await asyncio.wait_for(service.tasks[job.id], timeout=2)
    # download() reported FAILED on the kill; the queue overrode it to PAUSED.
    assert (await repository.get(job.id)).status is DownloadStatus.PAUSED
    # Options retained so resume can re-run.
    assert job.id in service.options


@pytest.mark.asyncio
async def test_resume_requeues_a_paused_job() -> None:
    repository = InMemoryDownloadRepository()
    downloader = ScriptedDownloader([DownloadStatus.FAILED, DownloadStatus.COMPLETED])
    service = QueueService(repository, downloader, max_concurrent=1)

    job = await _create(service)
    await service.tasks[job.id]
    # Simulate the failed run having been a pause instead.
    stored = await repository.get(job.id)
    stored.status = DownloadStatus.PAUSED
    await repository.update(stored)

    resumed = await service.resume(job.id)
    assert resumed is not None
    await service.tasks[job.id]

    assert (await repository.get(job.id)).status is DownloadStatus.COMPLETED
    assert downloader.runs == 2


@pytest.mark.asyncio
async def test_resume_rejects_a_non_paused_job() -> None:
    repository = InMemoryDownloadRepository()
    service = QueueService(repository, ScriptedDownloader([DownloadStatus.FAILED]), max_concurrent=1)
    job = await _create(service)
    await service.tasks[job.id]  # FAILED, not paused

    with pytest.raises(ValueError):
        await service.resume(job.id)


@pytest.mark.asyncio
async def test_pausing_a_completed_job_is_a_no_op() -> None:
    repository = InMemoryDownloadRepository()
    service = QueueService(repository, ScriptedDownloader([DownloadStatus.COMPLETED]), max_concurrent=1)
    job = await _create(service)
    await service.tasks[job.id]

    result = await service.pause(job.id)
    assert result.status is DownloadStatus.COMPLETED
