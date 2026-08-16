import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from ...domain.captures import (
    CaptureStatus,
    CaptureType,
    CapturedSource,
    MetadataStatus,
    make_source_key,
)
from ...domain.models import RequestContext
from ...domain.ports import CaptureRepository
from ...infrastructure.media_probe import MediaProbeService


class CaptureService:
    _SENSITIVE = {'cookie', 'authorization', 'proxy-authorization', 'set-cookie'}
    _MAX_HEADERS = 64
    _MAX_HEADER_VALUE = 4000

    def __init__(self, repository: CaptureRepository, media_probe: MediaProbeService) -> None:
        self.repository = repository
        self.media_probe = media_probe

    @classmethod
    def _safe_headers(cls, headers: dict[str, str]) -> dict[str, str]:
        safe: dict[str, str] = {}
        for name, value in headers.items():
            key = name.strip()
            if not key or key.lower() in cls._SENSITIVE:
                continue
            if len(safe) >= cls._MAX_HEADERS:
                break
            safe[key] = value[: cls._MAX_HEADER_VALUE]
        return safe

    @staticmethod
    def _validate_url(value: str, field: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError(f'{field} must use http or https.')

    async def capture(
        self,
        *,
        media_url: str,
        page_url: str | None,
        page_title: str | None,
        referer: str | None,
        origin: str | None,
        user_agent: str | None,
        headers: dict[str, str],
        capture_type: CaptureType,
        content_type: str | None,
        content_length_bytes: int | None,
    ) -> CapturedSource:
        self._validate_url(media_url, 'media_url')
        if page_url:
            self._validate_url(page_url, 'page_url')
        if referer:
            self._validate_url(referer, 'referer')
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                raise ValueError('origin must be an http/https origin.')

        source_key = make_source_key(media_url, page_url, capture_type)
        now = datetime.now(timezone.utc)
        safe_headers = self._safe_headers(headers)
        existing = await self.repository.find_by_source_key(source_key)
        if existing:
            existing.media_url = media_url
            existing.page_url = page_url or existing.page_url
            existing.page_title = page_title[:500] if page_title else existing.page_title
            existing.referer = referer or existing.referer
            existing.origin = origin or existing.origin
            existing.user_agent = user_agent[:500] if user_agent else existing.user_agent
            existing.headers = safe_headers or existing.headers
            existing.content_type = content_type or existing.content_type
            existing.size_bytes = content_length_bytes or existing.size_bytes
            existing.duration_seconds = None
            existing.width = None
            existing.height = None
            existing.metadata_status = MetadataStatus.PENDING
            existing.metadata_error = None
            existing.status = CaptureStatus.CAPTURED
            existing.used_at = None
            existing.created_at = now
            await self.repository.update(existing)
            return existing

        capture = CapturedSource(
            id=uuid.uuid4().hex,
            source_key=source_key,
            media_url=media_url,
            page_url=page_url,
            page_title=page_title[:500] if page_title else None,
            referer=referer,
            origin=origin,
            user_agent=user_agent[:500] if user_agent else None,
            headers=safe_headers,
            capture_type=capture_type,
            content_type=content_type,
            size_bytes=content_length_bytes,
            duration_seconds=None,
            width=None,
            height=None,
            metadata_status=MetadataStatus.PENDING,
            metadata_error=None,
            status=CaptureStatus.CAPTURED,
            created_at=now,
            used_at=None,
        )
        return await self.repository.add(capture)

    async def enrich_metadata(self, capture_id: str) -> None:
        capture = await self.repository.get(capture_id)
        if not capture:
            return
        context = RequestContext(
            page_url=capture.page_url,
            referer=capture.referer,
            origin=capture.origin,
            user_agent=capture.user_agent,
            headers=capture.headers,
        )
        try:
            result = await self.media_probe.probe(capture.media_url, context)
            capture.size_bytes = result.size_bytes or capture.size_bytes
            capture.duration_seconds = result.duration_seconds
            capture.width = result.width
            capture.height = result.height
            capture.metadata_status = MetadataStatus.READY
            capture.metadata_error = None
        except Exception as exc:
            capture.metadata_status = MetadataStatus.FAILED
            capture.metadata_error = str(exc)[:1000]
        await self.repository.update(capture)
