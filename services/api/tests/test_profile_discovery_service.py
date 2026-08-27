from datetime import datetime, timezone

import pytest

from app.application.instagram.discovery import ProfileDiscoveryService
from app.domain.collections import InstagramContentType, ProfileItemPreview


class FakeInstaloaderService:
    def __init__(self, previews: list[ProfileItemPreview] | None = None, username: str | None = None) -> None:
        self.previews = previews or []
        self.username = username
        self.calls: list[tuple] = []

    async def list_profile_items(self, profile_url, content_types, since=None, until=None) -> list[ProfileItemPreview]:
        self.calls.append((profile_url, content_types, since, until))
        return self.previews

    async def test_session(self) -> str | None:
        return self.username


@pytest.mark.asyncio
async def test_preview_delegates_to_instaloader_service() -> None:
    preview = ProfileItemPreview(
        source_url='https://www.instagram.com/p/abc/', content_type='post', author_username='someuser',
        caption=None, thumbnail_url=None, external_id='abc',
    )
    service_double = FakeInstaloaderService([preview])
    service = ProfileDiscoveryService(service_double)  # type: ignore[arg-type]

    result = await service.preview('https://www.instagram.com/someuser/', [InstagramContentType.POST])

    assert result == [preview]
    assert service_double.calls == [('https://www.instagram.com/someuser/', [InstagramContentType.POST], None, None)]


@pytest.mark.asyncio
async def test_preview_passes_date_range_through() -> None:
    service_double = FakeInstaloaderService()
    service = ProfileDiscoveryService(service_double)  # type: ignore[arg-type]
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    until = datetime(2026, 3, 1, tzinfo=timezone.utc)

    await service.preview('https://www.instagram.com/someuser/', [InstagramContentType.POST], since, until)

    assert service_double.calls == [('https://www.instagram.com/someuser/', [InstagramContentType.POST], since, until)]


@pytest.mark.asyncio
async def test_preview_rejects_since_after_until() -> None:
    service = ProfileDiscoveryService(FakeInstaloaderService())  # type: ignore[arg-type]
    since = datetime(2026, 3, 1, tzinfo=timezone.utc)
    until = datetime(2026, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        await service.preview('https://www.instagram.com/someuser/', [InstagramContentType.POST], since, until)


@pytest.mark.asyncio
async def test_preview_rejects_a_non_instagram_url() -> None:
    service = ProfileDiscoveryService(FakeInstaloaderService())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await service.preview('https://example.com/someuser/', [InstagramContentType.POST])


@pytest.mark.asyncio
async def test_preview_rejects_a_non_http_url() -> None:
    service = ProfileDiscoveryService(FakeInstaloaderService())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await service.preview('ftp://www.instagram.com/someuser/', [InstagramContentType.POST])


@pytest.mark.asyncio
async def test_preview_requires_at_least_one_content_type() -> None:
    service = ProfileDiscoveryService(FakeInstaloaderService())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await service.preview('https://www.instagram.com/someuser/', [])


@pytest.mark.asyncio
async def test_verify_session_returns_the_authenticated_username() -> None:
    service = ProfileDiscoveryService(FakeInstaloaderService(username='someuser'))  # type: ignore[arg-type]
    assert await service.verify_session() == 'someuser'


@pytest.mark.asyncio
async def test_verify_session_returns_none_when_not_authenticated() -> None:
    service = ProfileDiscoveryService(FakeInstaloaderService(username=None))  # type: ignore[arg-type]
    assert await service.verify_session() is None
