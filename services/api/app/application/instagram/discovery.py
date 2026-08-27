from datetime import datetime
from urllib.parse import urlparse

from ...domain.collections import InstagramContentType, ProfileItemPreview
from ...infrastructure.instaloader_service import InstaloaderService


class ProfileDiscoveryService:
    """Metadata-only browsing of an Instagram profile -- nothing is
    persisted here. A caller turns a chosen subset of the returned previews
    into CollectionItems via CollectionService."""

    def __init__(self, instaloader_service: InstaloaderService) -> None:
        self.instaloader_service = instaloader_service

    @staticmethod
    def _validate_profile_url(value: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('profile_url must use http or https.')
        if 'instagram.com' not in parsed.netloc.lower():
            raise ValueError('profile_url must be an instagram.com profile URL.')

    @staticmethod
    def _validate_range(since: datetime | None, until: datetime | None) -> None:
        if since is not None and until is not None and since > until:
            raise ValueError('posted_after must not be later than posted_before.')

    async def preview(
        self,
        profile_url: str,
        content_types: list[InstagramContentType],
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[ProfileItemPreview]:
        self._validate_profile_url(profile_url)
        if not content_types:
            raise ValueError('At least one content type must be requested.')
        self._validate_range(since, until)
        return await self.instaloader_service.list_profile_items(profile_url, content_types, since, until)

    async def verify_session(self) -> str | None:
        """Returns the username the stored session cookie authenticates as,
        or None if there is no session configured or it does not work."""
        return await self.instaloader_service.test_session()
