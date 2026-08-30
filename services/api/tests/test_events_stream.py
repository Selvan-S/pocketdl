"""The SSE stream that replaced the PWA's 2s poll of four endpoints.

Two properties matter: it must push promptly when state actually changes,
and it must stay quiet when nothing does -- the whole point was to stop
waking the client, and re-rendering its lists, on a timer.

The stream is driven through the route's own body iterator rather than over
HTTP, because httpx's ASGITransport buffers a response to completion before
returning it and therefore cannot consume an endless stream at all. The
route function and its generator are the real code either way; only the
transport is skipped.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api.routes import events
from app.application.events import ChangeNotifier


async def _frames(app, *, count: int, timeout: float = 10.0) -> tuple[list[dict], int]:
    """Pull `count` data frames off the stream, counting keepalives separately."""
    response = await events(SimpleNamespace(app=app))
    assert response.media_type == 'text/event-stream'

    payloads: list[dict] = []
    keepalives = 0

    async def pump():
        nonlocal keepalives
        async for chunk in response.body_iterator:
            text = chunk.decode() if isinstance(chunk, bytes) else chunk
            for frame in text.split('\n\n'):
                frame = frame.strip()
                if not frame or frame.startswith('retry:'):
                    continue
                if frame.startswith(':'):
                    keepalives += 1
                    continue
                for line in frame.splitlines():
                    if line.startswith('data: '):
                        payloads.append(json.loads(line[len('data: '):]))
            if len(payloads) >= count:
                return

    try:
        await asyncio.wait_for(pump(), timeout=timeout)
    finally:
        await response.body_iterator.aclose()
    return payloads, keepalives


def live_app():
    """The app the api_client fixture just built. Depends on api_client
    having run first, which every caller below arranges by requesting it."""
    import app.main

    return app.main.app


@pytest.mark.asyncio
async def test_stream_sends_the_current_state_immediately(api_client) -> None:
    payloads, _ = await _frames(live_app(), count=1)

    snapshot = payloads[0]
    assert snapshot['downloads'] == []
    assert snapshot['captures'] == []
    assert snapshot['settings']['download_directory']
    assert snapshot['status']['app_version']


@pytest.mark.asyncio
async def test_stream_carries_collection_summaries(api_client) -> None:
    # Round 10: playlists must update live, which means their summaries have
    # to be on the snapshot. Items deliberately are not -- only counts.
    async def mutate():
        await asyncio.sleep(0.3)
        created = await api_client.post('/api/collections', json={'platform': 'instagram', 'name': 'Reels'})
        assert created.status_code == 201, created.text

    reader = asyncio.create_task(_frames(live_app(), count=2))
    await mutate()
    payloads, _ = await reader

    assert payloads[0]['collections'] == []
    summary = payloads[1]['collections'][0]
    assert summary['name'] == 'Reels'
    assert summary['item_count'] == 0
    assert summary['downloaded_count'] == 0


@pytest.mark.asyncio
async def test_stream_pushes_again_once_state_changes(api_client, tmp_path) -> None:
    moved_to = str(tmp_path / 'somewhere-else')

    async def mutate():
        # Give the stream a moment to emit its first snapshot first.
        await asyncio.sleep(0.3)
        response = await api_client.put('/api/settings', json={'download_directory': moved_to})
        assert response.status_code == 200, response.text

    reader = asyncio.create_task(_frames(live_app(), count=2))
    await mutate()
    payloads, _ = await reader

    assert payloads[0]['settings']['download_directory'] != moved_to
    assert payloads[1]['settings']['download_directory'] == moved_to


@pytest.mark.asyncio
async def test_an_idle_stream_repeats_nothing(api_client) -> None:
    # Regression on the actual complaint: the old loop re-sent all four
    # payloads every 2s whether or not anything had changed, so the client
    # re-rendered constantly. Asking for a second data frame while nothing
    # changes must time out -- only keepalives are produced.
    with pytest.raises(asyncio.TimeoutError):
        await _frames(live_app(), count=2, timeout=2.0)


@pytest.mark.asyncio
async def test_mutating_requests_wake_the_notifier(api_client, monkeypatch) -> None:
    # The middleware is what saves every future mutating route from having to
    # remember to notify.
    notified: list[int] = []
    monkeypatch.setattr(live_app().state.change_notifier, 'notify', lambda: notified.append(1))

    await api_client.get('/api/downloads')
    assert notified == []

    await api_client.post('/api/collections', json={'platform': 'instagram', 'name': 'X'})
    assert notified == [1]


@pytest.mark.asyncio
async def test_a_rejected_mutation_does_not_wake_the_notifier(api_client, monkeypatch) -> None:
    notified: list[int] = []
    monkeypatch.setattr(live_app().state.change_notifier, 'notify', lambda: notified.append(1))

    response = await api_client.post('/api/collections', json={'platform': 'instagram', 'name': '   '})

    assert response.status_code >= 400
    assert notified == []


@pytest.mark.asyncio
async def test_notifier_wakes_every_waiter_and_deregisters_them() -> None:
    notifier = ChangeNotifier()

    waiters = [asyncio.create_task(notifier.wait(since=0, timeout=5)) for _ in range(3)]
    await asyncio.sleep(0.05)
    assert notifier.subscriber_count == 3

    notifier.notify()

    assert await asyncio.gather(*waiters) == [True, True, True]
    # Waiters remove themselves, so a long-lived server does not leak one per
    # browser reconnect.
    assert notifier.subscriber_count == 0


@pytest.mark.asyncio
async def test_notifier_wait_reports_a_timeout_as_a_heartbeat() -> None:
    notifier = ChangeNotifier()

    assert await notifier.wait(since=notifier.version, timeout=0.05) is False
    assert notifier.subscriber_count == 0


@pytest.mark.asyncio
async def test_a_change_during_the_throttle_window_is_not_lost() -> None:
    # The race the stream actually hits: it spends most of its cycle building
    # and writing a snapshot, not waiting. An edge-triggered broadcast fired
    # in that window was dropped, stranding the client until the next
    # heartbeat -- 15s of apparently frozen UI. Caught by
    # test_stream_pushes_again_once_state_changes before this existed.
    notifier = ChangeNotifier()

    seen = notifier.version
    notifier.notify()  # fired while the subscriber is "busy"

    assert await notifier.wait(since=seen, timeout=0.05) is True
