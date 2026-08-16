import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from ..domain.captures import CaptureStatus, CaptureType, CapturedSource
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
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    used_at TEXT
                )'''
            )
            await self._ensure_columns(db)
            await db.commit()

    @staticmethod
    async def _ensure_columns(db: aiosqlite.Connection) -> None:
        cursor = await db.execute('PRAGMA table_info(captures)')
        columns = {row[1] for row in await cursor.fetchall()}
        if 'page_title' not in columns:
            await db.execute('ALTER TABLE captures ADD COLUMN page_title TEXT')

    @staticmethod
    def _row_to_capture(row: aiosqlite.Row) -> CapturedSource:
        def parse(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        try:
            headers = json.loads(row['headers_json'])
        except (json.JSONDecodeError, TypeError):
            headers = {}
        if not isinstance(headers, dict):
            headers = {}
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
            status=CaptureStatus(row['status']),
            created_at=parse(row['created_at']) or datetime.now(timezone.utc),
            used_at=parse(row['used_at']),
        )

    async def add(self, capture: CapturedSource) -> CapturedSource:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                '''INSERT INTO captures (
                    id, source_key, media_url, page_url, page_title, referer, origin, user_agent, headers_json,
                    capture_type, content_type, status, created_at, used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    capture.id, capture.source_key, capture.media_url, capture.page_url, capture.page_title,
                    capture.referer, capture.origin, capture.user_agent,
                    json.dumps(capture.headers, separators=(',', ':')),
                    capture.capture_type.value, capture.content_type, capture.status.value,
                    capture.created_at.isoformat(), capture.used_at.isoformat() if capture.used_at else None,
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
                """UPDATE captures SET media_url=?, page_url=?, page_title=?, referer=?, origin=?, user_agent=?,
                headers_json=?, capture_type=?, content_type=?, status=?, created_at=?, used_at=? WHERE id=?""",
                (
                    capture.media_url, capture.page_url, capture.page_title, capture.referer, capture.origin, capture.user_agent,
                    json.dumps(capture.headers, separators=(',', ':')), capture.capture_type.value, capture.content_type,
                    capture.status.value, capture.created_at.isoformat(), capture.used_at.isoformat() if capture.used_at else None,
                    capture.id,
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
