from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from urllib.parse import urlparse, urlunparse
import hashlib


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


def normalize_media_url(media_url: str) -> str:
    parsed = urlparse(media_url)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, '', '', ''))


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
