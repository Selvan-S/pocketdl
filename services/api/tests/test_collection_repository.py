import sqlite3
from datetime import datetime, timezone

import pytest

from app.domain.collections import Collection, CollectionItem, InstagramContentType, Platform
from app.infrastructure.collections import SqliteCollectionRepository

# The collection_items table as it shipped before posted_at existed, used to
# prove the migration runs against a real historical database.
LEGACY_SCHEMA = """CREATE TABLE collection_items (
    id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    content_type TEXT NOT NULL,
    author_username TEXT,
    caption TEXT,
    thumbnail_url TEXT,
    external_id TEXT,
    added_at TEXT NOT NULL,
    downloaded_job_id TEXT
)"""


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


@pytest.mark.asyncio
async def test_posted_at_round_trips_through_add_and_get(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())
    item = build_item('i1', 'c1')
    item.posted_at = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)

    await repository.add_item(item)

    fetched = await repository.get_item('i1')
    assert fetched is not None
    assert fetched.posted_at == datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_posted_at_defaults_to_none_when_unset(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())

    await repository.add_item(build_item('i1', 'c1'))

    fetched = await repository.get_item('i1')
    assert fetched is not None
    assert fetched.posted_at is None


@pytest.mark.asyncio
async def test_initialize_migrates_a_pre_posted_at_database_and_is_idempotent(tmp_path) -> None:
    database = tmp_path / 'pocketdl.db'
    with sqlite3.connect(database) as db:
        db.execute('''CREATE TABLE collections (
            id TEXT PRIMARY KEY, platform TEXT NOT NULL, name TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )''')
        db.execute(LEGACY_SCHEMA)
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            'INSERT INTO collections (id, platform, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
            ('c1', 'instagram', 'Legacy', now, now),
        )
        db.execute(
            '''INSERT INTO collection_items (id, collection_id, source_url, content_type, added_at)
            VALUES (?, ?, ?, ?, ?)''',
            ('legacy-1', 'c1', 'https://instagram.com/p/legacy/', 'post', now),
        )

    repository = SqliteCollectionRepository(database)
    await repository.initialize()
    await repository.initialize()

    legacy = await repository.get_item('legacy-1')
    assert legacy is not None
    assert legacy.posted_at is None
