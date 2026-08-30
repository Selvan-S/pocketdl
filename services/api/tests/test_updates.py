"""yt-dlp update check (product-polish Round 3). Compares installed vs the
latest on PyPI; best-effort, never raises."""

import pytest

from app.infrastructure import updates
from app.infrastructure.updates import check_yt_dlp_update


def test_update_available_when_latest_is_newer(monkeypatch) -> None:
    monkeypatch.setattr(updates, '_fetch_latest_yt_dlp', lambda: '2030.01.01')
    status = check_yt_dlp_update('2024.08.06')
    assert status.update_available is True
    assert status.latest == '2030.01.01'
    assert status.error is None


def test_no_update_when_current_is_latest(monkeypatch) -> None:
    monkeypatch.setattr(updates, '_fetch_latest_yt_dlp', lambda: '2024.08.06')
    status = check_yt_dlp_update('2024.08.06')
    assert status.update_available is False


def test_network_failure_is_reported_not_raised(monkeypatch) -> None:
    def boom() -> str:
        raise OSError('no network')

    monkeypatch.setattr(updates, '_fetch_latest_yt_dlp', boom)
    status = check_yt_dlp_update('2024.08.06')
    assert status.update_available is False
    assert status.latest is None
    assert 'no network' in (status.error or '')


def test_unknown_current_version_is_not_an_update(monkeypatch) -> None:
    monkeypatch.setattr(updates, '_fetch_latest_yt_dlp', lambda: '2030.01.01')
    assert check_yt_dlp_update(None).update_available is False


@pytest.mark.asyncio
async def test_update_check_endpoint(api_client, monkeypatch) -> None:
    monkeypatch.setattr(updates, '_fetch_latest_yt_dlp', lambda: '9999.12.31')
    response = await api_client.get('/api/system/update-check')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['latest'] == '9999.12.31'
    assert body['update_available'] is True


def test_zero_padding_is_not_treated_as_an_update(monkeypatch) -> None:
    # PyPI reports "2026.8.19"; `yt-dlp --version` prints "2026.08.19" for the
    # same release. Must NOT flag an update.
    monkeypatch.setattr(updates, '_fetch_latest_yt_dlp', lambda: '2026.8.19')
    assert check_yt_dlp_update('2026.08.19').update_available is False


def test_numeric_component_update_is_detected(monkeypatch) -> None:
    monkeypatch.setattr(updates, '_fetch_latest_yt_dlp', lambda: '2026.9.1')
    assert check_yt_dlp_update('2026.08.19').update_available is True
