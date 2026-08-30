"""Import / export of settings, presets, and playlists (product-polish
Round 2). Round-trips as a single JSON bundle; import is additive and
idempotent so re-importing changes nothing."""

import pytest


async def _seed(api_client) -> None:
    await api_client.post('/api/presets', json={'name': 'Audio', 'preset': 'audio'})
    created = await api_client.post('/api/collections', json={'platform': 'instagram', 'name': 'Faves'})
    collection_id = created.json()['id']
    await api_client.post(f'/api/collections/{collection_id}/items', json={
        'source_url': 'https://www.instagram.com/p/abc/', 'content_type': 'reel', 'external_id': 'abc',
    })


@pytest.mark.asyncio
async def test_export_contains_presets_and_collections(api_client) -> None:
    await _seed(api_client)

    bundle = (await api_client.get('/api/export')).json()

    assert bundle['pocketdl_export_version'] == 1
    assert [p['name'] for p in bundle['presets']] == ['Audio']
    assert [c['name'] for c in bundle['collections']] == ['Faves']
    assert bundle['collections'][0]['items'][0]['external_id'] == 'abc'
    assert bundle['settings']['download_directory']


@pytest.mark.asyncio
async def test_import_restores_into_an_empty_instance(api_client) -> None:
    bundle = {
        'pocketdl_export_version': 1,
        'presets': [{'name': 'Best', 'preset': 'best'}],
        'collections': [{
            'platform': 'instagram', 'name': 'Restored',
            'items': [{'source_url': 'https://www.instagram.com/p/xyz/', 'content_type': 'post', 'external_id': 'xyz'}],
        }],
    }

    result = (await api_client.post('/api/import', json=bundle)).json()

    assert result['imported_presets'] == 1
    assert result['imported_collections'] == 1
    assert result['imported_items'] == 1
    assert [p['name'] for p in (await api_client.get('/api/presets')).json()] == ['Best']
    collections = (await api_client.get('/api/collections')).json()
    assert collections[0]['name'] == 'Restored'
    assert collections[0]['item_count'] == 1


@pytest.mark.asyncio
async def test_reimport_is_idempotent(api_client) -> None:
    await _seed(api_client)
    bundle = (await api_client.get('/api/export')).json()

    first = (await api_client.post('/api/import', json=bundle)).json()
    second = (await api_client.post('/api/import', json=bundle)).json()

    # First re-import: preset name already present -> skipped; collection
    # matched by name -> not recreated; item de-duped by content -> 0 new.
    assert first['imported_presets'] == 0
    assert first['imported_collections'] == 0
    assert first['imported_items'] == 0
    assert second == first
    # And nothing multiplied.
    assert len((await api_client.get('/api/presets')).json()) == 1
    assert len((await api_client.get('/api/collections')).json()) == 1


@pytest.mark.asyncio
async def test_import_round_trips_through_export(api_client) -> None:
    await _seed(api_client)
    bundle = (await api_client.get('/api/export')).json()

    reimported = (await api_client.post('/api/import', json=bundle)).json()

    assert reimported['settings_applied'] is True  # the exported dir is this instance's own, so valid
