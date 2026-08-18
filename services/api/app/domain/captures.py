from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlparse, urlunparse
import hashlib
import re


class CaptureType(StrEnum):
    HLS = 'hls'
    DASH = 'dash'
    MEDIA = 'media'


class CaptureStatus(StrEnum):
    CAPTURED = 'captured'
    USED = 'used'


class MetadataStatus(StrEnum):
    PENDING = 'pending'
    READY = 'ready'
    FAILED = 'failed'


_UUID_SEGMENT_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
_HEX_TOKEN_SEGMENT_RE = re.compile(r'^[0-9a-f]{20,}$', re.IGNORECASE)
_OPAQUE_TOKEN_SEGMENT_RE = re.compile(r'^[A-Za-z0-9_-]{24,}$')


def _looks_like_signed_token(segment: str) -> bool:
    """Best-effort heuristic for a request-scoped signed token embedded in a
    URL path segment, as opposed to a stable, meaningful slug or filename.

    Deliberately conservative: pure-digit segments are never treated as
    tokens (they are more often stable numeric content IDs than rotating
    signed tokens), and the length/character-mix thresholds are high enough
    that ordinary path segments (filenames, quality labels, short slugs)
    should never match. The known failure mode this accepts in exchange is
    two genuinely different videos on the same page whose manifest paths
    differ only in an opaque, UUID-like *stable* identifier in the same
    position — those would incorrectly collapse into one capture. Signed
    tokens confined to the query string (the common case) were already
    handled before this existed, since the query string is dropped entirely.
    """
    if not segment or segment.isdigit():
        return False
    if _UUID_SEGMENT_RE.match(segment):
        return True
    if _HEX_TOKEN_SEGMENT_RE.match(segment):
        return True
    if _OPAQUE_TOKEN_SEGMENT_RE.match(segment) and any(c.isdigit() for c in segment) and any(c.isalpha() for c in segment):
        return True
    return False


def normalize_media_url(media_url: str) -> str:
    parsed = urlparse(media_url)
    segments = parsed.path.split('/')
    normalized_segments = ['{token}' if _looks_like_signed_token(segment) else segment for segment in segments]
    normalized_path = '/'.join(normalized_segments)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), normalized_path, '', '', ''))


def normalize_page_url(page_url: str | None) -> str:
    if not page_url:
        return ''
    parsed = urlparse(page_url)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, '', '', ''))


def make_source_key(media_url: str, page_url: str | None, capture_type: CaptureType) -> str:
    value = f'{capture_type.value}\n{normalize_page_url(page_url)}\n{normalize_media_url(media_url)}'
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


@dataclass(slots=True)
class CapturedSource:
    id: str
    source_key: str
    media_url: str
    page_url: str | None
    page_title: str | None
    referer: str | None
    origin: str | None
    user_agent: str | None
    headers: dict[str, str]
    capture_type: CaptureType
    content_type: str | None
    size_bytes: int | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    metadata_status: MetadataStatus
    metadata_error: str | None
    status: CaptureStatus
    created_at: datetime
    used_at: datetime | None
