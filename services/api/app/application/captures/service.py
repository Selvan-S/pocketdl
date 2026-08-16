import hashlib
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

from ...domain.captures import CaptureStatus, CaptureType, CapturedSource
from ...domain.ports import CaptureRepository


class CaptureService:
    _SENSITIVE = {'cookie', 'authorization', 'proxy-authorization', 'set-cookie'}
    _MAX_HEADERS = 64
    _MAX_HEADER_VALUE = 4000

    def __init__(self, repository: CaptureRepository) -> None:
        self.repository = repository

    @staticmethod
    def _normalize_media_url(media_url: str) -> str:
        parsed = urlparse(media_url)
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, '', '', ''))

    @classmethod
    def _source_key(cls, media_url: str, page_url: str | None, capture_type: CaptureType) -> str:
        normalized_media = cls._normalize_media_url(media_url)
        parsed_page = urlparse(page_url) if page_url else None
        normalized_page = ''
        if parsed_page:
            normalized_page = urlunparse((parsed_page.scheme.lower(), parsed_page.netloc.lower(), parsed_page.path, '', '', ''))
        value = f'{capture_type.value}\n{normalized_page}\n{normalized_media}'
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

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

        source_key = self._source_key(media_url, page_url, capture_type)
        now = datetime.now(timezone.utc)
        safe_headers = self._safe_headers(headers)
        existing = await self.repository.find_by_source_key(source_key)
        if existing:
            existing.media_url = media_url
            existing.page_url = page_url or existing.page_url
            existing.page_title = (page_title[:500] if page_title else existing.page_title)
            existing.referer = referer or existing.referer
            existing.origin = origin or existing.origin
            existing.user_agent = user_agent[:500] if user_agent else existing.user_agent
            existing.headers = safe_headers or existing.headers
            existing.content_type = content_type or existing.content_type
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
            status=CaptureStatus.CAPTURED,
            created_at=now,
            used_at=None,
        )
        return await self.repository.add(capture)
