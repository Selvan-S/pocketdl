import pytest

from app.application.instagram.discovery import ProfileDiscoveryService
from app.domain.collections import InstagramContentType, ProfileItemPreview


class FakeGalleryDl:
    def __init__(self, previews: list[ProfileItemPreview] | None = None) -> None:
        self.previews = previews or []
        self.calls: list[tuple[str, list[InstagramContentType]]] = []

    async def list_profile_items(self, profile_url: str, content_types: list[InstagramContentType]) -> list[ProfileItemPreview]:
        self.calls.append((profile_url, content_types))
        return self.previews


@pytest.mark.asyncio
async def test_preview_delegates_to_gallery_dl() -> None:
    preview = ProfileItemPreview(
        source_url='https://www.instagram.com/p/abc/', content_type='post', author_username='someuser',
        caption=None, thumbnail_url=None, external_id='abc',
    )
    gallery_dl = FakeGalleryDl([preview])
    service = ProfileDiscoveryService(gallery_dl)  # type: ignore[arg-type]

    result = await service.preview('https://www.instagram.com/someuser/', [InstagramContentType.POST])

    assert result == [preview]
    assert gallery_dl.calls == [('https://www.instagram.com/someuser/', [InstagramContentType.POST])]


@pytest.mark.asyncio
async def test_preview_rejects_a_non_instagram_url() -> None:
    service = ProfileDiscoveryService(FakeGalleryDl())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await service.preview('https://example.com/someuser/', [InstagramContentType.POST])


@pytest.mark.asyncio
async def test_preview_rejects_a_non_http_url() -> None:
    service = ProfileDiscoveryService(FakeGalleryDl())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await service.preview('ftp://www.instagram.com/someuser/', [InstagramContentType.POST])


@pytest.mark.asyncio
async def test_preview_requires_at_least_one_content_type() -> None:
    service = ProfileDiscoveryService(FakeGalleryDl())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await service.preview('https://www.instagram.com/someuser/', [])
