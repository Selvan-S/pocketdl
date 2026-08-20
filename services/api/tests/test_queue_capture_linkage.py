import pytest

from app.application.downloads.service import QueueService
from app.domain.models import DownloadJob, DownloadSourceType, DownloadStatus, RequestContext


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


class FakeCaptureRepository:
    def __init__(self) -> None:
        self.marked_downloaded: list[str] = []

    async def mark_downloaded(self, capture_id: str):
        self.marked_downloaded.append(capture_id)
        return None


class FakeDownloader:
    """Simulates yt_dlp.YtDlpService.download without spawning a real process."""

    def __init__(self, final_status: DownloadStatus) -> None:
        self.final_status = final_status

    async def download(self, job: DownloadJob, *, on_progress, **kwargs) -> DownloadJob:
        job.status = self.final_status
        await on_progress(job)
        return job

    async def cancel(self, job_id: str) -> None:
        pass


async def _run_capture_download(final_status: DownloadStatus) -> tuple[QueueService, FakeCaptureRepository, DownloadJob]:
    repository = InMemoryDownloadRepository()
    capture_repository = FakeCaptureRepository()
    downloader = FakeDownloader(final_status)
    service = QueueService(repository, downloader, max_concurrent=1, capture_repository=capture_repository)

    job = await service.create(
        url='https://cdn.example/video/master.m3u8',
        filename=None,
        preset='best',
        concurrent_fragments=1,
        retries=1,
        use_aria2=False,
        request_context=RequestContext(),
        source_type=DownloadSourceType.CAPTURED,
        capture_id='capture-123',
    )
    task = service.tasks[job.id]
    await task
    return service, capture_repository, job


@pytest.mark.asyncio
async def test_completed_captured_download_marks_capture_used() -> None:
    _, capture_repository, job = await _run_capture_download(DownloadStatus.COMPLETED)

    assert capture_repository.marked_downloaded == ['capture-123']
    assert job.capture_id == 'capture-123'


@pytest.mark.asyncio
async def test_failed_captured_download_does_not_mark_capture_used() -> None:
    _, capture_repository, _job = await _run_capture_download(DownloadStatus.FAILED)

    assert capture_repository.marked_downloaded == []


@pytest.mark.asyncio
async def test_standard_download_without_capture_id_never_touches_capture_repository() -> None:
    repository = InMemoryDownloadRepository()
    capture_repository = FakeCaptureRepository()
    downloader = FakeDownloader(DownloadStatus.COMPLETED)
    service = QueueService(repository, downloader, max_concurrent=1, capture_repository=capture_repository)

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

    assert capture_repository.marked_downloaded == []
    assert job.capture_id is None
