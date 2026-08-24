import json
import sqlite3
from datetime import datetime, timezone

import pytest

from app.domain.captures import (
    CaptureStatus,
    CaptureType,
    CaptureVariant,
    CapturedSource,
    MetadataStatus,
    VariantStatus,
    make_source_key,
    make_variant_key,
)
from app.infrastructure.captures import SqliteCaptureRepository

PAGE_URL = 'https://site.example/watch/1'
MASTER_URL = 'https://cdn.example/hls/master.m3u8'
VARIANT_URL = 'https://cdn.example/hls/720p/index.m3u8'

# The capture table as it shipped before variant grouping existed, used to
# prove the migration runs against a real historical database.
LEGACY_SCHEMA = """CREATE TABLE captures (
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
)"""


def build_capture(capture_id: str, media_url: str) -> CapturedSource:
    return CapturedSource(
        id=capture_id,
        source_key=make_source_key(media_url, PAGE_URL, CaptureType.HLS),
        media_url=media_url,
        page_url=PAGE_URL,
        page_title='Example',
        referer='https://site.example/',
        origin='https://site.example',
        user_agent='Chrome',
        headers={'X-Test': 'ok'},
        capture_type=CaptureType.HLS,
        content_type='application/vnd.apple.mpegurl',
        size_bytes=None,
        duration_seconds=None,
        width=None,
        height=None,
        metadata_status=MetadataStatus.PENDING,
        metadata_error=None,
        status=CaptureStatus.CAPTURED,
        created_at=datetime.now(timezone.utc),
        used_at=None,
        variants_status=VariantStatus.PENDING,
    )


def build_variant(capture_id: str, position: int, url: str) -> CaptureVariant:
    return CaptureVariant(
        capture_id=capture_id,
        position=position,
        variant_key=make_variant_key(url, PAGE_URL),
        url=url,
        audio_url=None,
        bandwidth_bps=1_280_000,
        width=1280,
        height=720,
        codecs='avc1.4d401f',
        frame_rate=30.0,
        name=None,
    )


@pytest.mark.asyncio
async def test_variants_round_trip_and_are_found_by_key(tmp_path) -> None:
    repository = SqliteCaptureRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add(build_capture('master-1', MASTER_URL))

    await repository.replace_variants('master-1', [build_variant('master-1', 0, VARIANT_URL)])

    (stored,) = await repository.list_variants('master-1')
    assert stored.url == VARIANT_URL
    assert stored.bandwidth_bps == 1_280_000

    owner = await repository.find_by_variant_key(make_variant_key(VARIANT_URL, PAGE_URL))
    assert owner is not None and owner.id == 'master-1'
    assert await repository.find_by_variant_key('no-such-key') is None


@pytest.mark.asyncio
async def test_storing_variants_removes_a_card_that_duplicates_one(tmp_path) -> None:
    repository = SqliteCaptureRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add(build_capture('master-1', MASTER_URL))
    await repository.add(build_capture('variant-card', VARIANT_URL))

    await repository.replace_variants('master-1', [build_variant('master-1', 0, VARIANT_URL)])

    assert [item.id for item in await repository.list()] == ['master-1']


@pytest.mark.asyncio
async def test_deleting_a_capture_deletes_its_variants(tmp_path) -> None:
    database = tmp_path / 'pocketdl.db'
    repository = SqliteCaptureRepository(database)
    await repository.initialize()
    await repository.add(build_capture('master-1', MASTER_URL))
    await repository.replace_variants('master-1', [build_variant('master-1', 0, VARIANT_URL)])

    await repository.delete('master-1')

    assert await repository.list_variants('master-1') == []
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT COUNT(*) FROM capture_variants').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_variants_for_batches_lookups_and_covers_captures_without_variants(tmp_path) -> None:
    repository = SqliteCaptureRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.add(build_capture('master-1', MASTER_URL))
    await repository.add(build_capture('master-2', 'https://cdn.example/other/master.m3u8'))
    await repository.replace_variants('master-1', [build_variant('master-1', 0, VARIANT_URL)])

    grouped = await repository.variants_for(['master-1', 'master-2'])

    assert len(grouped['master-1']) == 1
    assert grouped['master-2'] == []
    assert await repository.variants_for([]) == {}


@pytest.mark.asyncio
async def test_initialize_migrates_a_pre_variant_database_and_is_idempotent(tmp_path) -> None:
    database = tmp_path / 'pocketdl.db'
    with sqlite3.connect(database) as db:
        db.execute(LEGACY_SCHEMA)
        db.execute(
            'INSERT INTO captures (id, source_key, media_url, page_url, headers_json, capture_type, status, created_at)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (
                'legacy-1', make_source_key(MASTER_URL, PAGE_URL, CaptureType.HLS), MASTER_URL, PAGE_URL,
                json.dumps({}), 'hls', 'captured', datetime.now(timezone.utc).isoformat(),
            ),
        )

    repository = SqliteCaptureRepository(database)
    await repository.initialize()
    await repository.initialize()

    legacy = await repository.get('legacy-1')
    assert legacy is not None
    assert legacy.variants_status is VariantStatus.PENDING


@pytest.mark.asyncio
async def test_startup_absorbs_a_historical_card_that_duplicates_a_known_variant(tmp_path) -> None:
    """Captures stored before grouping existed self-heal on the next start."""
    database = tmp_path / 'pocketdl.db'
    repository = SqliteCaptureRepository(database)
    await repository.initialize()
    await repository.add(build_capture('master-1', MASTER_URL))
    await repository.replace_variants('master-1', [build_variant('master-1', 0, VARIANT_URL)])
    await repository.add(build_capture('variant-card', VARIANT_URL))

    await repository.initialize()

    assert [item.id for item in await repository.list()] == ['master-1']
