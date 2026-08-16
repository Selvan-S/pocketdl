import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from ..domain.captures import (
    CaptureStatus,
    CaptureType,
    CapturedSource,
    MetadataStatus,
    make_source_key,
)
from ..domain.ports import CaptureRepository


class SqliteCaptureRepository(CaptureRepository):
    def __init__(self, database_path: Path):
        self.database_path = database_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                '''CREATE TABLE IF NOT EXISTS captures (
                    id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL UNIQUE,
                    media_url TEXT NOT NULL,
                    page_url TEXT,
                    page_title TEXT,
                    referer TEXT,
                    origin TEXT,
                    user_agent TEXT,
                    headers_json TEXT NOT NULL,
                    capture_type TEXT NOT NULL,
                    content_type TEXT,
                    size_bytes INTEGER,
                    duration_seconds REAL,
                    width INTEGER,
                    height INTEGER,
                    metadata_status TEXT NOT NULL DEFAULT 'pending',
                    metadata_error TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    used_at TEXT
                )'''
            )
            await self._ensure_columns(db)
            await self._deduplicate_and_rekey(db)
            await db.commit()

    @staticmethod
    async def _ensure_columns(db: aiosqlite.Connection) -> None:
        cursor = await db.execute('PRAGMA table_info(captures)')
        columns = {row[1] for row in await cursor.fetchall()}
        migrations = {
            'page_title': 'ALTER TABLE captures ADD COLUMN page_title TEXT',
            'size_bytes': 'ALTER TABLE captures ADD COLUMN size_bytes INTEGER',
            'duration_seconds': 'ALTER TABLE captures ADD COLUMN duration_seconds REAL',
            'width': 'ALTER TABLE captures ADD COLUMN width INTEGER',
            'height': 'ALTER TABLE captures ADD COLUMN height INTEGER',
            'metadata_status': "ALTER TABLE captures ADD COLUMN metadata_status TEXT NOT NULL DEFAULT 'pending'",
            'metadata_error': 'ALTER TABLE captures ADD COLUMN metadata_error TEXT',
        }
        for column, statement in migrations.items():
            if column not in columns:
                await db.execute(statement)

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime:
        return datetime.fromisoformat(value) if value else datetime.now(timezone.utc)

    @staticmethod
    def _row_to_capture(row: aiosqlite.Row) -> CapturedSource:
        try:
            headers = json.loads(row['headers_json'])
        except (json.JSONDecodeError, TypeError):
            headers = {}
        if not isinstance(headers, dict):
            headers = {}

        raw_status = row['metadata_status'] or MetadataStatus.PENDING.value
        try:
            metadata_status = MetadataStatus(raw_status)
        except ValueError:
            metadata_status = MetadataStatus.PENDING

        return CapturedSource(
            id=row['id'],
            source_key=row['source_key'],
            media_url=row['media_url'],
            page_url=row['page_url'],
            page_title=row['page_title'],
            referer=row['referer'],
            origin=row['origin'],
            user_agent=row['user_agent'],
            headers={str(k): str(v) for k, v in headers.items()},
            capture_type=CaptureType(row['capture_type']),
            content_type=row['content_type'],
            size_bytes=row['size_bytes'],
            duration_seconds=row['duration_seconds'],
            width=row['width'],
            height=row['height'],
            metadata_status=metadata_status,
            metadata_error=row['metadata_error'],
            status=CaptureStatus(row['status']),
            created_at=SqliteCaptureRepository._parse_datetime(row['created_at']),
            used_at=datetime.fromisoformat(row['used_at']) if row['used_at'] else None,
        )

    async def _deduplicate_and_rekey(self, db: aiosqlite.Connection) -> None:
        """Collapse historical duplicates created by older source-key logic."""
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('SELECT * FROM captures ORDER BY created_at DESC')
        rows = await cursor.fetchall()
        winners: dict[str, aiosqlite.Row] = {}
        duplicate_ids: list[str] = []

        for row in rows:
            try:
                capture_type = CaptureType(row['capture_type'])
            except ValueError:
                duplicate_ids.append(row['id'])
                continue
            key = make_source_key(row['media_url'], row['page_url'], capture_type)
            if key in winners:
                duplicate_ids.append(row['id'])
                continue
            winners[key] = row

        if duplicate_ids:
            placeholders = ','.join('?' for _ in duplicate_ids)
            await db.execute(f'DELETE FROM captures WHERE id IN ({placeholders})', duplicate_ids)

        for source_key, row in winners.items():
            if row['source_key'] != source_key:
                await db.execute('UPDATE captures SET source_key = ? WHERE id = ?', (source_key, row['id']))

    async def add(self, capture: CapturedSource) -> CapturedSource:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                '''INSERT INTO captures (
                    id, source_key, media_url, page_url, page_title, referer, origin, user_agent, headers_json,
                    capture_type, content_type, size_bytes, duration_seconds, width, height, metadata_status, metadata_error,
                    status, created_at, used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    capture.id, capture.source_key, capture.media_url, capture.page_url, capture.page_title,
                    capture.referer, capture.origin, capture.user_agent,
                    json.dumps(capture.headers, separators=(',', ':')),
                    capture.capture_type.value, capture.content_type, capture.size_bytes, capture.duration_seconds,
                    capture.width, capture.height, capture.metadata_status.value, capture.metadata_error,
                    capture.status.value, capture.created_at.isoformat(), capture.used_at.isoformat() if capture.used_at else None,
                ),
            )
            await db.commit()
        return capture

    async def get(self, capture_id: str) -> CapturedSource | None:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM captures WHERE id = ?', (capture_id,))
            row = await cursor.fetchone()
            return self._row_to_capture(row) if row else None

    async def list(self, limit: int = 50) -> list[CapturedSource]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM captures ORDER BY created_at DESC LIMIT ?', (max(1, min(limit, 200)),))
            return [self._row_to_capture(row) for row in await cursor.fetchall()]

    async def find_by_source_key(self, source_key: str) -> CapturedSource | None:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM captures WHERE source_key = ?', (source_key,))
            row = await cursor.fetchone()
            return self._row_to_capture(row) if row else None

    async def update(self, capture: CapturedSource) -> CapturedSource:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                '''UPDATE captures SET source_key=?, media_url=?, page_url=?, page_title=?, referer=?, origin=?, user_agent=?,
                headers_json=?, capture_type=?, content_type=?, size_bytes=?, duration_seconds=?, width=?, height=?,
                metadata_status=?, metadata_error=?, status=?, created_at=?, used_at=? WHERE id=?''',
                (
                    capture.source_key, capture.media_url, capture.page_url, capture.page_title, capture.referer, capture.origin,
                    capture.user_agent, json.dumps(capture.headers, separators=(',', ':')), capture.capture_type.value,
                    capture.content_type, capture.size_bytes, capture.duration_seconds, capture.width, capture.height,
                    capture.metadata_status.value, capture.metadata_error, capture.status.value, capture.created_at.isoformat(),
                    capture.used_at.isoformat() if capture.used_at else None, capture.id,
                ),
            )
            await db.commit()
        return capture

    async def mark_downloaded(self, capture_id: str) -> CapturedSource | None:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('UPDATE captures SET status = ?, used_at = ? WHERE id = ?', ('used', now, capture_id))
            await db.commit()
        return await self.get(capture_id)

    async def delete(self, capture_id: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('DELETE FROM captures WHERE id = ?', (capture_id,))
            await db.commit()
