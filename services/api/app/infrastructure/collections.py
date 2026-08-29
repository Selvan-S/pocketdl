from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from ..domain.collections import Collection, CollectionItem, Platform
from ..domain.ports import CollectionRepository


class SqliteCollectionRepository(CollectionRepository):
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                '''CREATE TABLE IF NOT EXISTS collections (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )'''
            )
            await db.execute(
                '''CREATE TABLE IF NOT EXISTS collection_items (
                    id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    author_username TEXT,
                    caption TEXT,
                    thumbnail_url TEXT,
                    external_id TEXT,
                    added_at TEXT NOT NULL,
                    posted_at TEXT,
                    downloaded_job_id TEXT,
                    profile_username TEXT
                )'''
            )
            await db.execute('CREATE INDEX IF NOT EXISTS idx_collection_items_collection ON collection_items (collection_id)')
            await self._ensure_columns(db)
            await self._ensure_item_uniqueness(db)
            await db.commit()

    # One row per piece of content per collection. external_id (the
    # platform's own id, e.g. an Instagram shortcode) is the real identity;
    # source_url is the fallback for an item that has none, since SQLite
    # treats NULLs in a unique index as distinct and would let them pile up.
    _ITEM_IDENTITY = 'collection_id, COALESCE(external_id, source_url)'

    @classmethod
    async def _ensure_item_uniqueness(cls, db: aiosqlite.Connection) -> None:
        """Previewing the same profile twice and adding the same items again
        used to silently duplicate every row, because nothing stopped it.

        Existing databases can already hold those duplicates, so they are
        collapsed before the index is created -- otherwise the CREATE would
        fail on exactly the databases that need it most. Keeps the
        earliest-added row of each group so a recorded downloaded_job_id
        isn't thrown away. Idempotent: a second run finds nothing to delete
        and the index already present.
        """
        await db.execute(
            f"""DELETE FROM collection_items WHERE id NOT IN (
                SELECT id FROM collection_items
                GROUP BY {cls._ITEM_IDENTITY}
                HAVING id = MIN(id) OR added_at = MIN(added_at)
            )""",
        )
        await db.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_collection_items_identity '
            f'ON collection_items ({cls._ITEM_IDENTITY})',
        )

    @staticmethod
    async def _ensure_columns(db: aiosqlite.Connection) -> None:
        cursor = await db.execute('PRAGMA table_info(collection_items)')
        columns = {row[1] for row in await cursor.fetchall()}
        migrations = {
            'posted_at': 'ALTER TABLE collection_items ADD COLUMN posted_at TEXT',
            'profile_username': 'ALTER TABLE collection_items ADD COLUMN profile_username TEXT',
        }
        for column, statement in migrations.items():
            if column not in columns:
                await db.execute(statement)

    @staticmethod
    def _row_to_collection(row: aiosqlite.Row) -> Collection:
        return Collection(
            id=row['id'],
            platform=Platform(row['platform']),
            name=row['name'],
            created_at=datetime.fromisoformat(row['created_at']),
            updated_at=datetime.fromisoformat(row['updated_at']),
        )

    @staticmethod
    def _row_to_item(row: aiosqlite.Row) -> CollectionItem:
        return CollectionItem(
            id=row['id'],
            collection_id=row['collection_id'],
            source_url=row['source_url'],
            content_type=row['content_type'],
            author_username=row['author_username'],
            caption=row['caption'],
            thumbnail_url=row['thumbnail_url'],
            external_id=row['external_id'],
            added_at=datetime.fromisoformat(row['added_at']),
            posted_at=datetime.fromisoformat(row['posted_at']) if row['posted_at'] else None,
            downloaded_job_id=row['downloaded_job_id'],
            profile_username=row['profile_username'] if 'profile_username' in row.keys() else None,
        )

    async def add_collection(self, collection: Collection) -> Collection:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                '''INSERT INTO collections (id, platform, name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)''',
                (
                    collection.id, collection.platform.value, collection.name,
                    collection.created_at.isoformat(), collection.updated_at.isoformat(),
                ),
            )
            await db.commit()
        return collection

    async def get_collection(self, collection_id: str) -> Collection | None:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM collections WHERE id = ?', (collection_id,))
            row = await cursor.fetchone()
            return self._row_to_collection(row) if row else None

    async def list_collections(self) -> list[Collection]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM collections ORDER BY updated_at DESC')
            return [self._row_to_collection(row) for row in await cursor.fetchall()]

    async def rename_collection(self, collection_id: str, name: str) -> Collection | None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('UPDATE collections SET name = ?, updated_at = ? WHERE id = ?', (name, now, collection_id))
            await db.commit()
        return await self.get_collection(collection_id)

    async def delete_collection(self, collection_id: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('DELETE FROM collections WHERE id = ?', (collection_id,))
            await db.execute('DELETE FROM collection_items WHERE collection_id = ?', (collection_id,))
            await db.commit()

    async def add_item(self, item: CollectionItem) -> CollectionItem:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                '''INSERT INTO collection_items (
                    id, collection_id, source_url, content_type, author_username, caption,
                    thumbnail_url, external_id, added_at, posted_at, downloaded_job_id,
                    profile_username
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT DO NOTHING''',
                (
                    item.id, item.collection_id, item.source_url, item.content_type, item.author_username,
                    item.caption, item.thumbnail_url, item.external_id, item.added_at.isoformat(),
                    item.posted_at.isoformat() if item.posted_at else None, item.downloaded_job_id,
                    item.profile_username,
                ),
            )
            await db.execute('UPDATE collections SET updated_at = ? WHERE id = ?', (item.added_at.isoformat(), item.collection_id))
            await db.commit()

            # Re-adding an item the collection already holds is a no-op, not
            # an error: the caller gets the row that is actually stored (with
            # its original id and any downloaded_job_id), so "add these 20"
            # after a second preview quietly keeps the 5 that are new.
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                'SELECT * FROM collection_items WHERE collection_id = ? '
                'AND COALESCE(external_id, source_url) = COALESCE(?, ?)',
                (item.collection_id, item.external_id, item.source_url),
            )
            row = await cursor.fetchone()
        return self._row_to_item(row) if row is not None else item

    async def get_item(self, item_id: str) -> CollectionItem | None:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM collection_items WHERE id = ?', (item_id,))
            row = await cursor.fetchone()
            return self._row_to_item(row) if row else None

    async def list_items(self, collection_id: str) -> list[CollectionItem]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                'SELECT * FROM collection_items WHERE collection_id = ? ORDER BY added_at', (collection_id,)
            )
            return [self._row_to_item(row) for row in await cursor.fetchall()]

    # The download-state filter for a paged item listing. "pending" and
    # "downloaded" are the two tabs a long playlist is split into; keyed on
    # downloaded_job_id, which mark_item_downloaded sets.
    _STATE_CLAUSES = {
        'all': '',
        'pending': ' AND downloaded_job_id IS NULL',
        'downloaded': ' AND downloaded_job_id IS NOT NULL',
    }

    async def list_items_page(
        self, collection_id: str, *, state: str = 'all', limit: int = 50, offset: int = 0,
    ) -> list[CollectionItem]:
        """A single page of one download-state, for a playlist too long to
        render in one scroll. Ordinary offset paging: unlike Round 9's
        remote Instagram feed there is no reverse-chronological cursor to
        work around, this is a plain local query."""
        clause = self._STATE_CLAUSES.get(state, '')
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                'SELECT * FROM collection_items WHERE collection_id = ?'
                f'{clause} ORDER BY added_at LIMIT ? OFFSET ?',
                (collection_id, max(0, limit), max(0, offset)),
            )
            return [self._row_to_item(row) for row in await cursor.fetchall()]

    async def collection_counts(self) -> dict[str, tuple[int, int]]:
        """(total, downloaded) item counts per collection, in one query.

        Built on every SSE snapshot -- which rebuilds on every download
        progress tick -- so this must not fan out into a per-collection
        query the way list_collections + list_items once did. A collection
        with no items simply does not appear; callers default it to (0, 0).
        """
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                '''SELECT collection_id,
                          COUNT(*) AS total,
                          SUM(CASE WHEN downloaded_job_id IS NOT NULL THEN 1 ELSE 0 END) AS downloaded
                   FROM collection_items GROUP BY collection_id''',
            )
            return {row[0]: (row[1], row[2] or 0) for row in await cursor.fetchall()}

    async def remove_item(self, collection_id: str, item_id: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('DELETE FROM collection_items WHERE id = ? AND collection_id = ?', (item_id, collection_id))
            await db.commit()

    async def update_item_metadata(
        self, item_id: str, *, caption: str | None, posted_at: datetime | None,
    ) -> None:
        """Backfill metadata that discovery could not supply cheaply.

        A reel preview comes from the Reels connection, which carries no
        caption and only an approximate date derived from the media id (see
        InstaloaderService._media_pk_to_datetime). Downloading the item
        fetches the real post anyway, so this is where the exact values
        become known. Only ever fills gaps or corrects the approximation --
        never overwrites a caption with nothing.
        """
        assignments: list[str] = []
        params: list[object] = []
        if caption is not None:
            assignments.append('caption = ?')
            params.append(caption)
        if posted_at is not None:
            assignments.append('posted_at = ?')
            params.append(posted_at.isoformat())
        if not assignments:
            return
        params.append(item_id)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(f'UPDATE collection_items SET {", ".join(assignments)} WHERE id = ?', params)
            await db.commit()

    async def mark_item_downloaded(self, item_id: str, job_id: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('UPDATE collection_items SET downloaded_job_id = ? WHERE id = ?', (job_id, item_id))
            await db.commit()
