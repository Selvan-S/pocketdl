"""The PWA polls a handful of endpoints every 2 seconds (see App.tsx's
refresh loop). None of them may reach Instagram: instaloader's session is a
real account credential and Instagram rate-limits aggressively, so a poll
that quietly made a network call would throttle -- or get -- the user's
account banned for simply leaving the tab open.

`GET /api/instagram/session` is the one that looks tempting to "improve" by
verifying the cookie so the badge is always accurate. It deliberately does
not (see the route's own comment, and Round 3 in
docs/docs_POCKETDL_ROADMAP.md). These tests make that a contract rather than
a comment.
"""

import pytest

from app.core.session_store import save_session_cookie
from app.infrastructure.instaloader_service import InstaloaderService

# Every endpoint the PWA's 2s refresh loop calls, plus the Instagram session
# status the panel reads on mount. Keep in sync with App.tsx's refresh().
POLLED_PATHS = [
    '/api/downloads',
    '/api/system/status',
    '/api/captures',
    '/api/settings',
    '/api/instagram/session',
]


@pytest.fixture
def instagram_tripwire(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fails loudly if anything reaches instaloader, at either the network
    layer or this project's own wrapper."""
    calls: list[str] = []

    def trip(name: str):
        def _tripped(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f'{name} was called while serving a polled endpoint')
        return _tripped

    monkeypatch.setattr(InstaloaderService, 'test_session', trip('InstaloaderService.test_session'))
    monkeypatch.setattr(InstaloaderService, 'list_profile_items', trip('InstaloaderService.list_profile_items'))
    monkeypatch.setattr(InstaloaderService, '_build_loader', trip('InstaloaderService._build_loader'))
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('path', POLLED_PATHS)
async def test_polled_endpoint_never_touches_instagram(path: str, api_client, instagram_tripwire: list[str]) -> None:
    response = await api_client.get(path)

    assert response.status_code == 200, response.text
    assert instagram_tripwire == []


@pytest.mark.asyncio
async def test_instagram_session_status_reports_configured_without_verifying(api_client, instagram_tripwire) -> None:
    # The badge may say "configured"; it must not say "verified", because
    # confirming that costs a request to Instagram.
    body = (await api_client.get('/api/instagram/session')).json()

    assert 'configured' in body
    assert body['verified_username'] is None
    assert instagram_tripwire == []


@pytest.mark.asyncio
async def test_explicit_verify_is_the_only_route_that_may_call_instagram(api_client, monkeypatch) -> None:
    # The counterpart: verification must still happen when the user actually
    # asks for it, so the tripwire above can't be satisfied by breaking it.
    called: list[str] = []

    async def fake_test_session(self):
        called.append('test_session')
        return 'someuser'

    monkeypatch.setattr(InstaloaderService, 'test_session', fake_test_session)
    # The route short-circuits when nothing is stored, so give it a session.
    save_session_cookie(
        api_client.app_settings.database_path, 'instagram', '.instagram.com', 'sessionid=abc; csrftoken=def',
    )

    response = await api_client.post('/api/instagram/session/verify')

    assert response.status_code == 200
    assert called == ['test_session']
