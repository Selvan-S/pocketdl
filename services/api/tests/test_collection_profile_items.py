"""Adding a whole profile query to a playlist in one call.

Selecting "everything" used to mean paging a profile by hand and holding
every card on screen just to tick them -- a real profile with 128 reels
needed three manual pages. This route runs the same query server-side and
adds what it matches, so the browser never has to render any of it.
"""

from datetime import datetime, timezone

import pytest

from app.domain.collections import InstagramContentType, ProfileItemPreview
from app.infrastructure.instaloader_service import InstaloaderService, ProfileItemPage


def _preview(external_id: str, day: int = 20) -> ProfileItemPreview:
    return ProfileItemPreview(
        source_url=f'https://www.instagram.com/reel/{external_id}/',
        content_type=InstagramContentType.REEL.value,
        author_username='someuser',
        profile_username='someuser',
        caption=None,
        thumbnail_url='https://cdn.example/t.jpg',
        external_id=external_id,
        posted_at=datetime(2026, 8, day, tzinfo=timezone.utc),
    )


@pytest.fixture
def stub_discovery(monkeypatch):
    """Replace the engine so these tests exercise the route and the
    collection service, not Instagram."""
    state: dict = {'page': ProfileItemPage(items=[], has_more=False), 'calls': []}

    async def fake_list(self, profile_url, content_types, since=None, until=None, limit=50):
        state['calls'].append({'limit': limit, 'until': until, 'content_types': list(content_types)})
        return state['page']

    monkeypatch.setattr(InstaloaderService, 'list_profile_items', fake_list)
    return state


async def _new_collection(api_client) -> str:
    response = await api_client.post('/api/collections', json={'platform': 'instagram', 'name': 'Everything'})
    assert response.status_code in (200, 201), response.text
    return response.json()['id']


@pytest.mark.asyncio
async def test_adds_every_matching_item_in_one_call(api_client, stub_discovery) -> None:
    stub_discovery['page'] = ProfileItemPage(items=[_preview(f'r{n}') for n in range(30)], has_more=False)
    collection_id = await _new_collection(api_client)

    response = await api_client.post(f'/api/collections/{collection_id}/profile-items', json={
        'profile_url': 'https://www.instagram.com/someuser/', 'content_types': ['reel'], 'limit': 200,
    })

    assert response.status_code == 200, response.text
    assert response.json()['added'] == 30
    assert response.json()['already_present'] == 0
    items = (await api_client.get(f'/api/collections/{collection_id}/items')).json()
    assert len(items) == 30


@pytest.mark.asyncio
async def test_adding_twice_reports_what_was_already_there(api_client, stub_discovery) -> None:
    # "Added 50" followed by an unchanged playlist was the confusing part;
    # the counts now distinguish new from already-held.
    stub_discovery['page'] = ProfileItemPage(items=[_preview(f'r{n}') for n in range(5)], has_more=False)
    collection_id = await _new_collection(api_client)
    body = {'profile_url': 'https://www.instagram.com/someuser/', 'content_types': ['reel']}

    first = await api_client.post(f'/api/collections/{collection_id}/profile-items', json=body)
    second = await api_client.post(f'/api/collections/{collection_id}/profile-items', json=body)

    assert first.json() == {**first.json(), 'added': 5, 'already_present': 0}
    assert second.json() == {**second.json(), 'added': 0, 'already_present': 5}
    assert len((await api_client.get(f'/api/collections/{collection_id}/items')).json()) == 5


@pytest.mark.asyncio
async def test_reports_when_it_stopped_short_of_everything(api_client, stub_discovery) -> None:
    # Silent truncation is the bug this whole change exists to remove: if
    # matching items were left behind, the caller has to be able to say so.
    stub_discovery['page'] = ProfileItemPage(
        items=[_preview(f'r{n}', day=20 - n) for n in range(3)], has_more=True,
    )
    collection_id = await _new_collection(api_client)

    response = await api_client.post(f'/api/collections/{collection_id}/profile-items', json={
        'profile_url': 'https://www.instagram.com/someuser/', 'content_types': ['reel'],
    })

    body = response.json()
    assert body['has_more'] is True
    assert body['next_posted_before'].startswith('2026-08-18')


@pytest.mark.asyncio
async def test_passes_the_requested_limit_through(api_client, stub_discovery) -> None:
    collection_id = await _new_collection(api_client)

    await api_client.post(f'/api/collections/{collection_id}/profile-items', json={
        'profile_url': 'https://www.instagram.com/someuser/', 'content_types': ['reel'], 'limit': 200,
    })

    assert stub_discovery['calls'][-1]['limit'] == 200


@pytest.mark.asyncio
async def test_rejects_a_limit_above_the_maximum(api_client, stub_discovery) -> None:
    collection_id = await _new_collection(api_client)

    response = await api_client.post(f'/api/collections/{collection_id}/profile-items', json={
        'profile_url': 'https://www.instagram.com/someuser/', 'content_types': ['reel'], 'limit': 5000,
    })

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_collection_is_a_404_not_a_silent_success(api_client, stub_discovery) -> None:
    response = await api_client.post('/api/collections/does-not-exist/profile-items', json={
        'profile_url': 'https://www.instagram.com/someuser/', 'content_types': ['reel'],
    })

    assert response.status_code == 404
    # And it must not have gone to Instagram for a playlist that isn't there.
    assert stub_discovery['calls'] == []


@pytest.mark.asyncio
async def test_a_bad_profile_url_is_rejected_before_any_fetch(api_client, stub_discovery) -> None:
    collection_id = await _new_collection(api_client)

    response = await api_client.post(f'/api/collections/{collection_id}/profile-items', json={
        'profile_url': 'not-a-url', 'content_types': ['reel'],
    })

    assert response.status_code == 422
    assert stub_discovery['calls'] == []


# --- the paginated preview response ---


@pytest.mark.asyncio
async def test_preview_reports_more_and_a_cursor(api_client, stub_discovery) -> None:
    stub_discovery['page'] = ProfileItemPage(
        items=[_preview('r1', day=20), _preview('r2', day=14)], has_more=True,
    )

    response = await api_client.post('/api/instagram/profile/preview', json={
        'profile_url': 'https://www.instagram.com/someuser/', 'content_types': ['reel'],
    })

    body = response.json()
    assert body['has_more'] is True
    assert body['next_posted_before'].startswith('2026-08-14')
    assert [item['external_id'] for item in body['items']] == ['r1', 'r2']


@pytest.mark.asyncio
async def test_preview_passes_the_cursor_back_as_an_upper_bound(api_client, stub_discovery) -> None:
    await api_client.post('/api/instagram/profile/preview', json={
        'profile_url': 'https://www.instagram.com/someuser/',
        'content_types': ['reel'],
        'posted_before': '2026-08-14T00:00:00Z',
    })

    assert stub_discovery['calls'][-1]['until'] == datetime(2026, 8, 14, tzinfo=timezone.utc)
