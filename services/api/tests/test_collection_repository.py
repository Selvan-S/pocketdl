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


def build_item(
    item_id: str, collection_id: str, url: str = 'https://instagram.com/p/abc/', external_id: str | None = None,
) -> CollectionItem:
    return CollectionItem(
        id=item_id,
        collection_id=collection_id,
        source_url=url,
        content_type=InstagramContentType.REEL.value,
        author_username='someone',
        caption='a caption',
        thumbnail_url='https://cdn.example/thumb.jpg',
        # Defaults to the item id so two items built for one collection are
        # distinct content by default; pass external_id explicitly to model
        # the same post being added twice.
        external_id=external_id if external_id is not None else item_id,
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


# --- Round 7: one row per piece of content per collection ---


@pytest.mark.asyncio
async def test_adding_the_same_content_twice_is_a_no_op(tmp_path) -> None:
    # Previewing a profile again and re-adding the same selection used to
    # duplicate every row, because nothing stopped it.
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())

    first = await repository.add_item(build_item('i1', 'c1', external_id='shortcode-1'))
    second = await repository.add_item(build_item('i2', 'c1', external_id='shortcode-1'))

    items = await repository.list_items('c1')
    assert len(items) == 1
    # The caller gets back the row that is actually stored, not the rejected one.
    assert first.id == 'i1'
    assert second.id == 'i1'


@pytest.mark.asyncio
async def test_the_same_content_in_two_collections_is_allowed(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection('c1'))
    await repository.add_collection(build_collection('c2', name='Another'))

    await repository.add_item(build_item('i1', 'c1', external_id='shortcode-1'))
    await repository.add_item(build_item('i2', 'c2', external_id='shortcode-1'))

    assert len(await repository.list_items('c1')) == 1
    assert len(await repository.list_items('c2')) == 1


@pytest.mark.asyncio
async def test_items_without_an_external_id_dedupe_on_source_url(tmp_path) -> None:
    # Stories and highlights have no stable shortcode, so they fall back to
    # the media URL -- SQLite treats NULLs in a unique index as distinct and
    # would otherwise let them pile up.
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())

    same_url = 'https://cdn.example/story.mp4'
    first = build_item('i1', 'c1', url=same_url)
    first.external_id = None
    second = build_item('i2', 'c1', url=same_url)
    second.external_id = None
    await repository.add_item(first)
    await repository.add_item(second)

    assert len(await repository.list_items('c1')) == 1


@pytest.mark.asyncio
async def test_initialize_collapses_duplicates_already_in_the_database(tmp_path) -> None:
    # A database written before the index existed can already hold
    # duplicates; creating the index would fail on exactly those unless they
    # are collapsed first. The earliest row wins so a recorded
    # downloaded_job_id is not thrown away.
    database = tmp_path / 'pocketdl.db'
    repository = SqliteCollectionRepository(database)
    await repository.initialize()
    await repository.add_collection(build_collection())

    with sqlite3.connect(database) as raw:
        raw.execute('DROP INDEX idx_collection_items_identity')
        for item_id in ('i1', 'i2', 'i3'):
            raw.execute(
                'INSERT INTO collection_items (id, collection_id, source_url, content_type, external_id, added_at) '
                "VALUES (?, 'c1', 'https://instagram.com/p/dupe/', 'reel', 'dupe', ?)",
                (item_id, f'2026-08-2{item_id[-1]}T00:00:00+00:00'),
            )
        raw.commit()

    await repository.initialize()

    items = await repository.list_items('c1')
    assert [item.id for item in items] == ['i1']


@pytest.mark.asyncio
async def test_initialize_is_idempotent_after_collapsing(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())
    await repository.add_item(build_item('i1', 'c1', external_id='shortcode-1'))

    await repository.initialize()
    await repository.initialize()

    assert [item.id for item in await repository.list_items('c1')] == ['i1']


@pytest.mark.asyncio
async def test_update_item_metadata_fills_gaps(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())
    item = build_item('i1', 'c1', external_id='shortcode-1')
    item.caption = None
    item.posted_at = None
    await repository.add_item(item)

    exact = datetime(2026, 8, 23, 11, 9, 1, tzinfo=timezone.utc)
    await repository.update_item_metadata('i1', caption='the real caption', posted_at=exact)

    stored = (await repository.list_items('c1'))[0]
    assert stored.caption == 'the real caption'
    assert stored.posted_at == exact


# --- Round 10: state-filtered paging and by-state counts ---


@pytest.mark.asyncio
async def test_collection_counts_reports_total_and_downloaded(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection('c1'))
    await repository.add_collection(build_collection('c2', name='Other'))
    await repository.add_item(build_item('i1', 'c1', external_id='a'))
    await repository.add_item(build_item('i2', 'c1', external_id='b'))
    await repository.add_item(build_item('i3', 'c1', external_id='c'))
    await repository.add_item(build_item('i4', 'c2', external_id='d'))
    await repository.mark_item_downloaded('i1', 'job-1')
    await repository.mark_item_downloaded('i2', 'job-2')

    counts = await repository.collection_counts()

    assert counts['c1'] == (3, 2)
    assert counts['c2'] == (1, 0)
    # A collection with no items simply does not appear.
    await repository.add_collection(build_collection('c3', name='Empty'))
    assert 'c3' not in await repository.collection_counts()


@pytest.mark.asyncio
async def test_list_items_page_filters_by_state(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())
    for suffix in ('a', 'b', 'c', 'd'):
        await repository.add_item(build_item(f'i-{suffix}', 'c1', external_id=suffix))
    await repository.mark_item_downloaded('i-a', 'job-1')
    await repository.mark_item_downloaded('i-c', 'job-2')

    pending = await repository.list_items_page('c1', state='pending')
    downloaded = await repository.list_items_page('c1', state='downloaded')
    everything = await repository.list_items_page('c1', state='all')

    assert {item.id for item in pending} == {'i-b', 'i-d'}
    assert {item.id for item in downloaded} == {'i-a', 'i-c'}
    assert len(everything) == 4


@pytest.mark.asyncio
async def test_list_items_page_paginates_in_added_order(tmp_path) -> None:
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())
    for index in range(5):
        item = build_item(f'i{index}', 'c1', external_id=str(index))
        item.added_at = datetime(2026, 8, 20, 12, index, tzinfo=timezone.utc)
        await repository.add_item(item)

    first = await repository.list_items_page('c1', limit=2, offset=0)
    second = await repository.list_items_page('c1', limit=2, offset=2)

    assert [item.id for item in first] == ['i0', 'i1']
    assert [item.id for item in second] == ['i2', 'i3']


@pytest.mark.asyncio
async def test_update_item_metadata_never_blanks_an_existing_caption(tmp_path) -> None:
    # A reel with no caption must not wipe one that discovery did supply.
    repository = SqliteCollectionRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add_collection(build_collection())
    await repository.add_item(build_item('i1', 'c1', external_id='shortcode-1'))

    await repository.update_item_metadata('i1', caption=None, posted_at=None)

    stored = (await repository.list_items('c1'))[0]
    assert stored.caption == 'a caption'
