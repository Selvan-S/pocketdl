from datetime import datetime, timezone

import pytest

from app.domain.collections import Collection, CollectionItem, InstagramContentType, Platform
from app.infrastructure.collections import SqliteCollectionRepository


def _now() -> datetime:
    return datetime.now(timezone.utc)


def build_collection(collection_id: str = 'c1', name: str = 'My Reels') -> Collection:
    now = _now()
    return Collection(id=collection_id, platform=Platform.INSTAGRAM, name=name, created_at=now, updated_at=now)


def build_item(item_id: str, collection_id: str, url: str = 'https://instagram.com/p/abc/') -> CollectionItem:
    return CollectionItem(
        id=item_id,
        collection_id=collection_id,
        source_url=url,
        content_type=InstagramContentType.REEL.value,
        author_username='someone',
        caption='a caption',
        thumbnail_url='https://cdn.example/thumb.jpg',
        external_id='abc',
        added_at=_now(),
    )


@pytest.mark.asyncio
async def test_collection_round_trip(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()

    await repository.add_collection(build_collection())
    fetched = await repository.get_collection('c1')
    assert fetched is not None
    assert fetched.name == 'My Reels'
    assert fetched.platform is Platform.INSTAGRAM

    listed = await repository.list_collections()
    assert [c.id for c in listed] == ['c1']


@pytest.mark.asyncio
async def test_rename_and_delete_collection(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())

    renamed = await repository.rename_collection('c1', 'Renamed')
    assert renamed is not None
    assert renamed.name == 'Renamed'

    await repository.delete_collection('c1')
    assert await repository.get_collection('c1') is None


@pytest.mark.asyncio
async def test_deleting_a_collection_deletes_its_items(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())
    await repository.add_item(build_item('i1', 'c1'))

    await repository.delete_collection('c1')

    assert await repository.list_items('c1') == []


@pytest.mark.asyncio
async def test_add_list_and_remove_items(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())
    await repository.add_item(build_item('i1', 'c1', 'https://instagram.com/p/one/'))
    await repository.add_item(build_item('i2', 'c1', 'https://instagram.com/p/two/'))

    items = await repository.list_items('c1')
    assert [item.id for item in items] == ['i1', 'i2']

    await repository.remove_item('c1', 'i1')
    remaining = await repository.list_items('c1')
    assert [item.id for item in remaining] == ['i2']


@pytest.mark.asyncio
async def test_mark_item_downloaded(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())
    await repository.add_item(build_item('i1', 'c1'))

    await repository.mark_item_downloaded('i1', 'job-123')

    item = await repository.get_item('i1')
    assert item is not None
    assert item.downloaded_job_id == 'job-123'


@pytest.mark.asyncio
async def test_initialize_is_idempotent(tmp_path) -> None:
    database = tmp_path / 'pocketdl.db'
    repository = SqliteCollectionRepository(database)
    await repository.initialize()
    await repository.initialize()

    await repository.add_collection(build_collection())
    assert len(await repository.list_collections()) == 1
