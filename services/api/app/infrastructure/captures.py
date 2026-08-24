import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from ..domain.captures import (
    CaptureStatus,
    CaptureType,
    CaptureVariant,
    CapturedSource,
    MetadataStatus,
    VariantStatus,
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
            await db.execute(
                '''CREATE TABLE IF NOT EXISTS capture_variants (
                    capture_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    variant_key TEXT NOT NULL,
                    url TEXT NOT NULL,
                    audio_url TEXT,
                    bandwidth_bps INTEGER,
                    width INTEGER,
                    height INTEGER,
                    codecs TEXT,
                    frame_rate REAL,
                    name TEXT,
                    PRIMARY KEY (capture_id, position)
                )'''
            )
            await db.execute('CREATE INDEX IF NOT EXISTS idx_capture_variants_key ON capture_variants (variant_key)')
            await self._ensure_columns(db)
            await self._deduplicate_and_rekey(db)
            await self._absorb_variant_duplicates(db)
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
            'variants_status': "ALTER TABLE captures ADD COLUMN variants_status TEXT NOT NULL DEFAULT 'pending'",
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

        try:
            variants_status = VariantStatus(row['variants_status'] or VariantStatus.PENDING.value)
        except (ValueError, IndexError, KeyError):
            variants_status = VariantStatus.PENDING

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
            variants_status=variants_status,
        )

    @staticmethod
    def _row_to_variant(row: aiosqlite.Row) -> CaptureVariant:
        return CaptureVariant(
            capture_id=row['capture_id'],
            position=row['position'],
            variant_key=row['variant_key'],
            url=row['url'],
            audio_url=row['audio_url'],
            bandwidth_bps=row['bandwidth_bps'],
            width=row['width'],
            height=row['height'],
            codecs=row['codecs'],
            frame_rate=row['frame_rate'],
            name=row['name'],
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

    @staticmethod
    async def _absorb_variant_duplicates(db: aiosqlite.Connection) -> None:
        """Delete capture rows that are really a known master's variant.

        Self-heals captures stored before variant grouping existed, and any
        variant captured in the window between a master being stored and its
        playlist being parsed.
        """
        await db.execute(
            '''DELETE FROM captures WHERE source_key IN (
                SELECT variant_key FROM capture_variants
            ) AND id NOT IN (SELECT capture_id FROM capture_variants)'''
        )

    async def add(self, capture: CapturedSource) -> CapturedSource:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                '''INSERT INTO captures (
                    id, source_key, media_url, page_url, page_title, referer, origin, user_agent, headers_json,
                    capture_type, content_type, size_bytes, duration_seconds, width, height, metadata_status, metadata_error,
                    status, created_at, used_at, variants_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    capture.id, capture.source_key, capture.media_url, capture.page_url, capture.page_title,
                    capture.referer, capture.origin, capture.user_agent,
                    json.dumps(capture.headers, separators=(',', ':')),
                    capture.capture_type.value, capture.content_type, capture.size_bytes, capture.duration_seconds,
                    capture.width, capture.height, capture.metadata_status.value, capture.metadata_error,
                    capture.status.value, capture.created_at.isoformat(), capture.used_at.isoformat() if capture.used_at else None,
                    capture.variants_status.value,
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
                metadata_status=?, metadata_error=?, status=?, created_at=?, used_at=?, variants_status=? WHERE id=?''',
                (
                    capture.source_key, capture.media_url, capture.page_url, capture.page_title, capture.referer, capture.origin,
                    capture.user_agent, json.dumps(capture.headers, separators=(',', ':')), capture.capture_type.value,
                    capture.content_type, capture.size_bytes, capture.duration_seconds, capture.width, capture.height,
                    capture.metadata_status.value, capture.metadata_error, capture.status.value, capture.created_at.isoformat(),
                    capture.used_at.isoformat() if capture.used_at else None, capture.variants_status.value, capture.id,
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
            await db.execute('DELETE FROM capture_variants WHERE capture_id = ?', (capture_id,))
            await db.commit()

    # `list` is shadowed by this class's own `list` method, so the
    # annotations below have to stay strings.
    async def replace_variants(self, capture_id: str, variants: 'list[CaptureVariant]') -> None:
        """Store a master's variant list, and remove any card duplicating one.

        Replacing rather than merging keeps the stored list an exact mirror of
        the playlist as last read: a quality the site has dropped should stop
        being offered, not linger as an unplayable option.
        """
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('DELETE FROM capture_variants WHERE capture_id = ?', (capture_id,))
            await db.executemany(
                '''INSERT INTO capture_variants (
                    capture_id, position, variant_key, url, audio_url, bandwidth_bps, width, height, codecs, frame_rate, name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                [
                    (
                        variant.capture_id, variant.position, variant.variant_key, variant.url, variant.audio_url,
                        variant.bandwidth_bps, variant.width, variant.height, variant.codecs, variant.frame_rate, variant.name,
                    )
                    for variant in variants
                ],
            )
            if variants:
                placeholders = ','.join('?' for _ in variants)
                await db.execute(
                    f'DELETE FROM captures WHERE source_key IN ({placeholders}) AND id != ?',
                    [variant.variant_key for variant in variants] + [capture_id],
                )
            await db.commit()

    async def list_variants(self, capture_id: str) -> 'list[CaptureVariant]':
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                'SELECT * FROM capture_variants WHERE capture_id = ? ORDER BY position', (capture_id,)
            )
            return [self._row_to_variant(row) for row in await cursor.fetchall()]

    async def variants_for(self, capture_ids: 'list[str]') -> 'dict[str, list[CaptureVariant]]':
        """Batch lookup for the list endpoint, so rendering N cards stays two
        queries rather than N + 1."""
        if not capture_ids:
            return {}
        grouped: 'dict[str, list[CaptureVariant]]' = {capture_id: [] for capture_id in capture_ids}
        placeholders = ','.join('?' for _ in capture_ids)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f'SELECT * FROM capture_variants WHERE capture_id IN ({placeholders}) ORDER BY position', capture_ids
            )
            for row in await cursor.fetchall():
                grouped[row['capture_id']].append(self._row_to_variant(row))
        return grouped

    async def find_by_variant_key(self, variant_key: str) -> CapturedSource | None:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                '''SELECT captures.* FROM captures
                JOIN capture_variants ON capture_variants.capture_id = captures.id
                WHERE capture_variants.variant_key = ? LIMIT 1''',
                (variant_key,),
            )
            row = await cursor.fetchone()
            return self._row_to_capture(row) if row else None
