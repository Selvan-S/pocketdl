import asyncio

import pytest

from app.infrastructure.yt_dlp import YtDlpService


class _StubSettings:
    pass


class _StubCapturedMedia:
    pass


def _make_service(monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]) -> YtDlpService:
    service = YtDlpService(_StubSettings(), _StubCapturedMedia())  # type: ignore[arg-type]

    def fake_tool_version(command: list[str]) -> str | None:
        calls.append(command)
        return 'stub-version'

    monkeypatch.setattr(YtDlpService, '_tool_version', staticmethod(fake_tool_version))
    return service


@pytest.mark.asyncio
async def test_versions_are_cached_after_first_call(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: /system/status used to re-spawn yt-dlp/ffmpeg/aria2 version
    # checks on every poll (every 2s from the PWA). On a backgrounded
    # Android/Termux process this could take up to 30s (three sequential
    # subprocess timeouts), and polling faster than that made it worse by
    # piling up overlapping checks. Versions never change mid-session, so
    # they should only be computed once.
    calls: list[list[str]] = []
    service = _make_service(monkeypatch, calls)

    first = await service.versions()
    second = await service.versions()

    assert first == second == {'yt_dlp': 'stub-version', 'ffmpeg': 'stub-version', 'aria2': 'stub-version'}
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_concurrent_versions_calls_only_check_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    service = _make_service(monkeypatch, calls)

    results = await asyncio.gather(*(service.versions() for _ in range(5)))

    assert all(result == results[0] for result in results)
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_refresh_versions_forces_a_fresh_check(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    service = _make_service(monkeypatch, calls)

    await service.versions()
    await service.refresh_versions()

    assert len(calls) == 6
