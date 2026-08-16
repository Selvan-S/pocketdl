from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class CaptureType(StrEnum):
    HLS = 'hls'
    DASH = 'dash'
    MEDIA = 'media'


class CaptureStatus(StrEnum):
    CAPTURED = 'captured'
    USED = 'used'


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
    status: CaptureStatus
    created_at: datetime
    used_at: datetime | None
