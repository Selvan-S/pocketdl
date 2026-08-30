import pytest

from app.application.downloads.service import QueueService
from app.domain.models import DownloadEngine, DownloadJob, DownloadStatus, RequestContext


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


class FakeCollectionRepository:
    def __init__(self) -> None:
        self.marked_downloaded: list[tuple[str, str]] = []

    async def mark_item_downloaded(self, item_id: str, job_id: str) -> None:
        self.marked_downloaded.append((item_id, job_id))


class FakeDownloader:
    """Simulates GalleryDlService.download without spawning a real process."""

    def __init__(self, final_status: DownloadStatus) -> None:
        self.final_status = final_status

    async def download(self, job: DownloadJob, *, on_progress, **kwargs) -> DownloadJob:
        job.status = self.final_status
        await on_progress(job)
        return job

    async def cancel(self, job_id: str) -> None:
        pass


async def _run_collection_download(final_status: DownloadStatus) -> tuple[FakeCollectionRepository, DownloadJob]:
    repository = InMemoryDownloadRepository()
    collection_repository = FakeCollectionRepository()
    downloader = FakeDownloader(final_status)
    service = QueueService(repository, downloader, max_concurrent=1, collection_repository=collection_repository)

    job = await service.create(
        url='https://www.instagram.com/p/abc123/',
        filename=None,
        preset='best',
        concurrent_fragments=1,
        retries=1,
        use_aria2=False,
        request_context=RequestContext(),
        engine=DownloadEngine.GALLERY_DL,
        collection_item_id='item-123',
    )
    await service.tasks[job.id]
    return collection_repository, job


@pytest.mark.asyncio
async def test_completed_collection_download_marks_item_downloaded() -> None:
    collection_repository, job = await _run_collection_download(DownloadStatus.COMPLETED)

    assert collection_repository.marked_downloaded == [('item-123', job.id)]
    assert job.collection_item_id == 'item-123'
    assert job.engine is DownloadEngine.GALLERY_DL


@pytest.mark.asyncio
async def test_failed_collection_download_does_not_mark_item_downloaded() -> None:
    collection_repository, _job = await _run_collection_download(DownloadStatus.FAILED)

    assert collection_repository.marked_downloaded == []


@pytest.mark.asyncio
async def test_standard_download_without_collection_item_id_never_touches_collection_repository() -> None:
    repository = InMemoryDownloadRepository()
    collection_repository = FakeCollectionRepository()
    downloader = FakeDownloader(DownloadStatus.COMPLETED)
    service = QueueService(repository, downloader, max_concurrent=1, collection_repository=collection_repository)

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

    assert collection_repository.marked_downloaded == []
    assert job.collection_item_id is None
