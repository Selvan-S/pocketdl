from urllib.parse import urlparse

from ...domain.collections import InstagramContentType, ProfileItemPreview
from ...infrastructure.gallery_dl import GalleryDlService


class ProfileDiscoveryService:
    """Metadata-only browsing of an Instagram profile -- nothing is
    persisted here. A caller turns a chosen subset of the returned previews
    into CollectionItems via CollectionService."""

    def __init__(self, gallery_dl: GalleryDlService) -> None:
        self.gallery_dl = gallery_dl

    @staticmethod
    def _validate_profile_url(value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('profile_url must use http or https.')
        if 'instagram.com' not in parsed.netloc.lower():
            raise ValueError('profile_url must be an instagram.com profile URL.')

    async def preview(self, profile_url: str, content_types: list[InstagramContentType]) -> list[ProfileItemPreview]:
        self._validate_profile_url(profile_url)
        if not content_types:
            raise ValueError('At least one content type must be requested.')
        return await self.gallery_dl.list_profile_items(profile_url, content_types)
