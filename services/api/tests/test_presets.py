"""Saved download presets (product-polish Round 2).

A preset is a named, reusable set of download options (quality + performance
knobs) so a user can apply "Reel -> best MP4" in one tap. Format_id is never
part of one -- it belongs to a single analyzed URL.
"""

import pytest

from app.infrastructure.presets import SqliteDownloadPresetRepository


@pytest.mark.asyncio
async def test_preset_repository_round_trip(tmp_path) -> None:
    repository = SqliteDownloadPresetRepository(tmp_path / 'pocketdl.db')
    await repository.initialize()
    await repository.initialize()  # idempotent

    from datetime import datetime, timezone

    from app.domain.presets import DownloadPreset

    preset = DownloadPreset(
        id='p1', name='Audio only', preset='audio', concurrent_fragments=4,
        retries=5, use_aria2=True, created_at=datetime.now(timezone.utc),
    )
    await repository.add(preset)

    listed = await repository.list()
    assert [p.id for p in listed] == ['p1']
    fetched = await repository.get('p1')
    assert fetched is not None
    assert fetched.preset == 'audio'
    assert fetched.use_aria2 is True
    assert fetched.concurrent_fragments == 4

    await repository.delete('p1')
    assert await repository.get('p1') is None
    assert await repository.list() == []


@pytest.mark.asyncio
async def test_presets_api_create_list_delete(api_client) -> None:
    created = await api_client.post('/api/presets', json={'name': 'Best MP4', 'preset': 'best'})
    assert created.status_code == 201, created.text
    preset_id = created.json()['id']
    assert created.json()['use_aria2'] is False
    assert created.json()['concurrent_fragments'] == 8

    listed = await api_client.get('/api/presets')
    assert [p['id'] for p in listed.json()] == [preset_id]

    deleted = await api_client.delete(f'/api/presets/{preset_id}')
    assert deleted.status_code == 200
    assert (await api_client.get('/api/presets')).json() == []


@pytest.mark.asyncio
async def test_deleting_an_unknown_preset_is_404(api_client) -> None:
    assert (await api_client.delete('/api/presets/nope')).status_code == 404


@pytest.mark.asyncio
async def test_creating_a_preset_rejects_an_empty_name(api_client) -> None:
    response = await api_client.post('/api/presets', json={'name': '', 'preset': 'best'})
    assert response.status_code == 422
