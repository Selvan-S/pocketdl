import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from ...domain.captures import (
    CaptureStatus,
    CaptureType,
    CaptureVariant,
    CapturedSource,
    MetadataStatus,
    VariantStatus,
    make_source_key,
    make_variant_key,
)
from ...domain.manifests import is_master_playlist, parse_master_playlist
from ...domain.models import RequestContext
from ...domain.ports import CaptureRepository
from ...infrastructure.manifest_fetch import ManifestFetcher
from ...infrastructure.media_probe import MediaProbeService


class CaptureService:
    _SENSITIVE = {'cookie', 'authorization', 'proxy-authorization', 'set-cookie'}
    _MAX_HEADERS = 64
    _MAX_HEADER_VALUE = 4000

    def __init__(
        self,
        repository: CaptureRepository,
        media_probe: MediaProbeService,
        manifest_fetcher: ManifestFetcher | None = None,
    ) -> None:
        self.repository = repository
        self.media_probe = media_probe
        self.manifest_fetcher = manifest_fetcher or ManifestFetcher()

    @staticmethod
    def _request_context(capture: CapturedSource) -> RequestContext:
        return RequestContext(
            page_url=capture.page_url,
            referer=capture.referer,
            origin=capture.origin,
            user_agent=capture.user_agent,
            headers=capture.headers,
        )

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

        # A player fetches the master playlist and then one or more of its
        # quality variants, so the variants arrive here as their own capture
        # requests. They are the same video: fold them into the master's card
        # instead of creating one card per quality.
        owning_master = await self.repository.find_by_variant_key(source_key)
        if owning_master is not None:
            owning_master.referer = referer or owning_master.referer
            owning_master.origin = origin or owning_master.origin
            owning_master.user_agent = user_agent[:500] if user_agent else owning_master.user_agent
            owning_master.headers = safe_headers or owning_master.headers
            owning_master.page_title = page_title[:500] if page_title else owning_master.page_title
            await self.repository.update(owning_master)
            return owning_master

        # For hls/dash, content_length_bytes is the Content-Length of the
        # fetched manifest text file, not the underlying media -- storing it
        # as size_bytes would show a tiny, misleading number (e.g. "500 B")
        # for a multi-hundred-MB stream. Only a direct media request's
        # Content-Length is the media's actual size; leave hls/dash size
        # unknown until ffprobe enrichment (or a future segment-enumeration
        # estimate) can determine it honestly.
        reported_size_bytes = content_length_bytes if capture_type is CaptureType.MEDIA else None
        # Only an HLS playlist can advertise variants; a DASH .mpd already
        # carries every representation in the one file the player fetches, and
        # a direct media URL has none.
        variants_status = VariantStatus.PENDING if capture_type is CaptureType.HLS else VariantStatus.NONE
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
            existing.size_bytes = reported_size_bytes or existing.size_bytes
            existing.duration_seconds = None
            existing.width = None
            existing.height = None
            existing.metadata_status = MetadataStatus.PENDING
            existing.metadata_error = None
            existing.status = CaptureStatus.CAPTURED
            existing.used_at = None
            existing.created_at = now
            existing.variants_status = variants_status
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
            size_bytes=reported_size_bytes,
            duration_seconds=None,
            width=None,
            height=None,
            metadata_status=MetadataStatus.PENDING,
            metadata_error=None,
            status=CaptureStatus.CAPTURED,
            created_at=now,
            used_at=None,
            variants_status=variants_status,
        )
        return await self.repository.add(capture)

    async def resolve_variants(self, capture_id: str) -> None:
        """Read a captured HLS playlist and record the qualities it offers.

        Failure is not an error the user has to act on -- the capture stays
        fully downloadable at the site's default quality -- so it is recorded
        as a status rather than raised.
        """
        capture = await self.repository.get(capture_id)
        if capture is None or capture.capture_type is not CaptureType.HLS:
            return

        try:
            playlist = await self.manifest_fetcher.fetch(capture.media_url, self._request_context(capture))
        except Exception:
            capture.variants_status = VariantStatus.FAILED
            await self.repository.update(capture)
            return

        if not is_master_playlist(playlist):
            # A media playlist: this capture is already one specific quality,
            # with nothing to choose between.
            capture.variants_status = VariantStatus.NONE
            await self.repository.update(capture)
            return

        streams = parse_master_playlist(playlist, capture.media_url)
        variants = [
            CaptureVariant(
                capture_id=capture.id,
                position=stream.index,
                variant_key=make_variant_key(stream.url, capture.page_url),
                url=stream.url,
                audio_url=stream.audio_url,
                bandwidth_bps=stream.bandwidth_bps,
                width=stream.width,
                height=stream.height,
                codecs=stream.codecs,
                frame_rate=stream.frame_rate,
                name=stream.name,
            )
            for stream in streams
        ]
        await self.repository.replace_variants(capture.id, variants)
        capture.variants_status = VariantStatus.READY if variants else VariantStatus.NONE
        await self.repository.update(capture)

    async def enrich_metadata(self, capture_id: str) -> None:
        capture = await self.repository.get(capture_id)
        if not capture:
            return
        try:
            result = await self.media_probe.probe(capture.media_url, self._request_context(capture))
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
