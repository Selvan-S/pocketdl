import pytest

from app.application.collections.service import CollectionService
from app.application.downloads.service import QueueService
from app.domain.collections import Platform, ProfileItemPreview
from app.domain.models import DownloadEngine, DownloadJob, DownloadStatus, RequestContext
from support import InMemoryCollectionRepository


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


class ImmediatelyCompletingDownloader:
    async def download(self, job: DownloadJob, *, on_progress, **kwargs) -> DownloadJob:
        job.status = DownloadStatus.COMPLETED
        await on_progress(job)
        return job

    async def cancel(self, job_id: str) -> None:
        pass


def _make_preview(url: str = 'https://www.instagram.com/p/abc123/', content_type: str = 'reel') -> ProfileItemPreview:
    return ProfileItemPreview(
        source_url=url, content_type=content_type, author_username='someuser',
        caption='a caption', thumbnail_url='https://cdn.example/thumb.jpg', external_id='abc123',
    )


def _make_service() -> tuple[CollectionService, InMemoryCollectionRepository]:
    repository = InMemoryCollectionRepository()
    queue = QueueService(InMemoryDownloadRepository(), ImmediatelyCompletingDownloader(), max_concurrent=2, collection_repository=repository)
    return CollectionService(repository, queue), repository


@pytest.mark.asyncio
async def test_create_collection() -> None:
    service, _ = _make_service()
    collection = await service.create_collection(Platform.INSTAGRAM, '  My Reels  ')
    assert collection.name == 'My Reels'
    assert collection.platform is Platform.INSTAGRAM


@pytest.mark.asyncio
async def test_create_collection_rejects_empty_name() -> None:
    service, _ = _make_service()
    with pytest.raises(ValueError):
        await service.create_collection(Platform.INSTAGRAM, '   ')


@pytest.mark.asyncio
async def test_add_item_requires_an_existing_collection() -> None:
    service, _ = _make_service()
    with pytest.raises(ValueError):
        await service.add_item('missing-collection', _make_preview())


@pytest.mark.asyncio
async def test_add_and_list_and_remove_items() -> None:
    service, _ = _make_service()
    collection = await service.create_collection(Platform.INSTAGRAM, 'Reels')

    item = await service.add_item(collection.id, _make_preview())
    assert (await service.list_items(collection.id)) == [item]

    await service.remove_item(collection.id, item.id)
    assert await service.list_items(collection.id) == []


@pytest.mark.asyncio
async def test_rename_collection() -> None:
    service, _ = _make_service()
    collection = await service.create_collection(Platform.INSTAGRAM, 'Old name')
    renamed = await service.rename_collection(collection.id, 'New name')
    assert renamed.name == 'New name'


@pytest.mark.asyncio
async def test_rename_missing_collection_raises() -> None:
    service, _ = _make_service()
    with pytest.raises(ValueError):
        await service.rename_collection('missing', 'New name')


@pytest.mark.asyncio
async def test_deleting_a_collection_deletes_its_items() -> None:
    service, _ = _make_service()
    collection = await service.create_collection(Platform.INSTAGRAM, 'Reels')
    await service.add_item(collection.id, _make_preview())

    await service.delete_collection(collection.id)

    assert await service.list_items(collection.id) == []


@pytest.mark.asyncio
async def test_download_collection_fans_out_one_job_per_item_via_gallery_dl_engine() -> None:
    service, _ = _make_service()
    collection = await service.create_collection(Platform.INSTAGRAM, 'Reels')
    first = await service.add_item(collection.id, _make_preview('https://www.instagram.com/p/one/'))
    second = await service.add_item(collection.id, _make_preview('https://www.instagram.com/p/two/'))

    jobs = await service.download_collection(collection.id, None, request_context=RequestContext())

    assert {job.url for job in jobs} == {first.source_url, second.source_url}
    assert all(job.engine is DownloadEngine.GALLERY_DL for job in jobs)
    assert {job.collection_item_id for job in jobs} == {first.id, second.id}


@pytest.mark.asyncio
async def test_download_collection_honors_an_explicit_item_id_subset() -> None:
    service, _ = _make_service()
    collection = await service.create_collection(Platform.INSTAGRAM, 'Reels')
    first = await service.add_item(collection.id, _make_preview('https://www.instagram.com/p/one/'))
    await service.add_item(collection.id, _make_preview('https://www.instagram.com/p/two/'))

    jobs = await service.download_collection(collection.id, [first.id], request_context=RequestContext())

    assert len(jobs) == 1
    assert jobs[0].collection_item_id == first.id


@pytest.mark.asyncio
async def test_download_collection_skips_already_downloaded_items() -> None:
    service, repository = _make_service()
    collection = await service.create_collection(Platform.INSTAGRAM, 'Reels')
    item = await service.add_item(collection.id, _make_preview())

    first_run = await service.download_collection(collection.id, None, request_context=RequestContext())
    assert len(first_run) == 1
    await service.queue.tasks[first_run[0].id]  # wait for the fake downloader's task to finish and mark the item

    second_run = await service.download_collection(collection.id, None, request_context=RequestContext())
    assert second_run == []
    stored_item = await repository.get_item(item.id)
    assert stored_item.downloaded_job_id == first_run[0].id


@pytest.mark.asyncio
async def test_download_collection_requires_an_existing_collection() -> None:
    service, _ = _make_service()
    with pytest.raises(ValueError):
        await service.download_collection('missing', None, request_context=RequestContext())
