from datetime import datetime
from pathlib import Path

import aiosqlite

from ..domain.presets import DownloadPreset
from ..domain.ports import DownloadPresetRepository


class SqliteDownloadPresetRepository(DownloadPresetRepository):
    """Named, reusable download-option sets. A plain table: presets are few,
    small, and only change on an explicit user action."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                '''CREATE TABLE IF NOT EXISTS download_presets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    preset TEXT NOT NULL,
                    concurrent_fragments INTEGER NOT NULL,
                    retries INTEGER NOT NULL,
                    use_aria2 INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )'''
            )
            await db.commit()

    @staticmethod
    def _row_to_preset(row: aiosqlite.Row) -> DownloadPreset:
        return DownloadPreset(
            id=row['id'],
            name=row['name'],
            preset=row['preset'],
            concurrent_fragments=row['concurrent_fragments'],
            retries=row['retries'],
            use_aria2=bool(row['use_aria2']),
            created_at=datetime.fromisoformat(row['created_at']),
        )

    async def add(self, preset: DownloadPreset) -> DownloadPreset:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                '''INSERT INTO download_presets
                    (id, name, preset, concurrent_fragments, retries, use_aria2, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (
                    preset.id, preset.name, preset.preset, preset.concurrent_fragments,
                    preset.retries, int(preset.use_aria2), preset.created_at.isoformat(),
                ),
            )
            await db.commit()
        return preset

    async def list(self) -> list[DownloadPreset]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM download_presets ORDER BY created_at')
            return [self._row_to_preset(row) for row in await cursor.fetchall()]

    async def get(self, preset_id: str) -> DownloadPreset | None:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute('SELECT * FROM download_presets WHERE id = ?', (preset_id,))
            row = await cursor.fetchone()
            return self._row_to_preset(row) if row else None

    async def delete(self, preset_id: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute('DELETE FROM download_presets WHERE id = ?', (preset_id,))
            await db.commit()
