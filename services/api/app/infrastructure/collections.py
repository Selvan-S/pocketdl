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
                    downloaded_job_id TEXT
                )'''
            )
            await db.execute('CREATE INDEX IF NOT EXISTS idx_collection_items_collection ON collection_items (collection_id)')
            await db.commit()

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
            downloaded_job_id=row['downloaded_job_id'],
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
                    thumbnail_url, external_id, added_at, downloaded_job_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    item.id, item.collection_id, item.source_url, item.content_type, item.author_username,
                    item.caption, item.thumbnail_url, item.external_id, item.added_at.isoformat(), item.downloaded_job_id,
                ),
            )
            await db.execute('UPDATE collections SET updated_at = ? WHERE id = ?', (item.added_at.isoformat(), item.collection_id))
            await db.commit()
        return item

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

    async def remove_item(self, collection_id: str, item_id: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('DELETE FROM collection_items WHERE id = ? AND collection_id = ?', (item_id, collection_id))
            await db.commit()

    async def mark_item_downloaded(self, item_id: str, job_id: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('UPDATE collection_items SET downloaded_job_id = ? WHERE id = ?', (job_id, item_id))
            await db.commit()
