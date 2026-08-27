import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from ..domain.captures import CaptureStatus, CaptureType, VariantStatus
from ..domain.errors import DownloadErrorCategory
from ..domain.models import ImpersonationMode, DownloadSourceType


class RequestContextRequest(BaseModel):
    page_url: str | None = Field(default=None, max_length=2000)
    referer: str | None = Field(default=None, max_length=2000)
    origin: str | None = Field(default=None, max_length=500)
    user_agent: str | None = Field(default=None, min_length=1, max_length=500)
    headers: dict[str, str] = Field(default_factory=dict)
    impersonation: Literal['none', 'auto', 'chrome'] = 'auto'

    @field_validator('page_url', 'referer', 'origin')
    @classmethod
    def validate_http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('URL must use http or https.')
        return value

    @field_validator('headers')
    @classmethod
    def reject_sensitive_headers(cls, value: dict[str, str]) -> dict[str, str]:
        sensitive = {'cookie', 'authorization', 'proxy-authorization', 'set-cookie'}
        rejected = [name for name in value if name.lower() in sensitive]
        if rejected:
            raise ValueError('Cookie and authorization headers are not supported yet.')
        return value


class DownloadCreateRequest(BaseModel):
    url: str
    filename: str | None = Field(default=None, min_length=1, max_length=200)
    preset: Literal['best', '1080p', '720p', '480p', 'audio'] = 'best'
    # A specific format_id from /api/analyze's format list, e.g. "137". Takes
    # priority over preset when set -- see YtDlpService._format_args. Only
    # meaningful for standard (non-captured) sources; ignored otherwise.
    format_id: str | None = Field(default=None, min_length=1, max_length=100)
    concurrent_fragments: int = Field(default=8, ge=1, le=32)
    retries: int = Field(default=10, ge=1, le=100)
    use_aria2: bool = False
    request_context: RequestContextRequest = Field(default_factory=RequestContextRequest)

    @field_validator('format_id')
    @classmethod
    def validate_format_id(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r'[A-Za-z0-9_.+-]{1,100}', value):
            raise ValueError('format_id must be a plain yt-dlp format identifier.')
        return value

    @field_validator('url')
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('URL must use http or https.')
        return value


class DownloadResponse(BaseModel):
    id: str
    url: str
    filename: str | None
    title: str | None
    status: str
    source_type: DownloadSourceType
    progress: float
    downloaded_bytes: int
    total_bytes: int | None
    speed_bytes: float | None
    eta_seconds: int | None
    output_path: str | None
    error: str | None
    error_details: str | None
    error_category: DownloadErrorCategory | None
    exit_code: int | None
    retry_count: int
    impersonation: ImpersonationMode
    referer: str | None
    origin: str | None
    user_agent: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    capture_id: str | None


class SystemStatusResponse(BaseModel):
    app_version: str
    yt_dlp_version: str | None
    ffmpeg_version: str | None
    aria2_version: str | None
    download_directory: str
    active_downloads: int
    queued_downloads: int


class AnalyzeRequest(BaseModel):
    url: str
    request_context: RequestContextRequest = Field(default_factory=RequestContextRequest)

    @field_validator('url')
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('URL must use http or https.')
        return value


class AnalyzedFormatResponse(BaseModel):
    format_id: str
    ext: str | None
    width: int | None
    height: int | None
    fps: float | None
    vcodec: str | None
    acodec: str | None
    filesize: int | None
    tbr: float | None
    protocol: str | None


class AnalyzeResponse(BaseModel):
    source_url: str
    webpage_url: str | None
    title: str | None
    uploader: str | None
    duration_seconds: float | None
    thumbnail: str | None
    extractor: str | None
    is_live: bool | None
    formats: list[AnalyzedFormatResponse]


class CaptureCreateRequest(BaseModel):
    media_url: str
    page_url: str | None = Field(default=None, max_length=2000)
    page_title: str | None = Field(default=None, max_length=500)
    referer: str | None = Field(default=None, max_length=2000)
    origin: str | None = Field(default=None, max_length=500)
    user_agent: str | None = Field(default=None, max_length=500)
    headers: dict[str, str] = Field(default_factory=dict)
    capture_type: Literal['hls', 'dash', 'media'] = 'hls'
    content_type: str | None = Field(default=None, max_length=300)
    content_length_bytes: int | None = Field(default=None, ge=0)

    @field_validator('media_url', 'page_url', 'referer')
    @classmethod
    def validate_http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('URL must use http or https.')
        return value

    @field_validator('headers')
    @classmethod
    def reject_sensitive_headers(cls, value: dict[str, str]) -> dict[str, str]:
        sensitive = {'cookie', 'authorization', 'proxy-authorization', 'set-cookie'}
        if any(name.lower() in sensitive for name in value):
            raise ValueError('Cookie and authorization headers are not supported by capture v0.2.')
        return value


class CaptureDownloadRequest(BaseModel):
    filename: str | None = Field(default=None, min_length=1, max_length=200)
    preset: Literal['best', '1080p', '720p', 'audio'] = 'best'
    concurrent_fragments: int = Field(default=8, ge=1, le=32)
    retries: int = Field(default=10, ge=1, le=100)
    variant_index: int | None = Field(default=None, ge=0)
    """Position of a quality from the capture's own variant list. Omitted
    downloads the master, letting the player's default quality apply."""


class CaptureVariantResponse(BaseModel):
    """One selectable quality of a captured HLS master."""

    index: int
    url: str
    quality_label: str
    bandwidth_bps: int | None
    width: int | None
    height: int | None
    codecs: str | None
    frame_rate: float | None
    name: str | None
    has_separate_audio: bool
    estimated_size_bytes: int | None
    """Bitrate x duration. Named as an estimate all the way to the UI because
    an HLS stream's exact byte size is not knowable before downloading it --
    it must never be shown as if it were a measured size."""


class CaptureResponse(BaseModel):
    id: str
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
    metadata_status: str
    metadata_error: str | None
    looks_suspicious: bool
    status: CaptureStatus
    created_at: datetime
    used_at: datetime | None
    variants_status: VariantStatus
    variants: list[CaptureVariantResponse] = Field(default_factory=list)


class SettingsResponse(BaseModel):
    download_directory: str
    default_download_directory: str


class SettingsUpdateRequest(BaseModel):
    download_directory: str = Field(min_length=1, max_length=2000)


class BrowseDirectoryResponse(BaseModel):
    path: str | None
    """The chosen absolute path, or None if the user cancelled the dialog."""


class InstagramProfilePreviewRequest(BaseModel):
    profile_url: str
    content_types: list[Literal['post', 'carousel', 'reel', 'story', 'highlight']] = Field(
        default_factory=lambda: ['post', 'reel', 'story', 'highlight'],
    )
    # Only applied to posts/reels -- stories/highlights aren't meaningfully
    # date-bounded browsing, see InstaloaderService._collect_posts.
    posted_after: datetime | None = None
    posted_before: datetime | None = None

    @field_validator('profile_url')
    @classmethod
    def validate_profile_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('profile_url must use http or https.')
        return value

    @field_validator('content_types')
    @classmethod
    def validate_content_types(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError('At least one content type must be requested.')
        return value


class ProfileItemPreviewResponse(BaseModel):
    source_url: str
    content_type: str
    author_username: str | None
    caption: str | None
    thumbnail_url: str | None
    external_id: str | None
    posted_at: datetime | None = None


class InstagramProfilePreviewResponse(BaseModel):
    items: list[ProfileItemPreviewResponse]


class InstagramSessionRequest(BaseModel):
    """Write-only: the raw pasted Cookie header value is validated and
    stored, never echoed back by any response -- see
    InstagramSessionStatusResponse."""

    cookie_header: str = Field(min_length=1, max_length=20000)


class InstagramSessionStatusResponse(BaseModel):
    configured: bool
    # Set only right after a successful save, or by the explicit verify
    # endpoint -- a real call to Instagram, not made on every status poll.
    verified_username: str | None = None


class CollectionCreateRequest(BaseModel):
    platform: Literal['instagram'] = 'instagram'
    name: str = Field(min_length=1, max_length=200)


class CollectionRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CollectionResponse(BaseModel):
    id: str
    platform: str
    name: str
    item_count: int
    created_at: datetime
    updated_at: datetime


class CollectionItemAddRequest(BaseModel):
    source_url: str
    content_type: Literal['post', 'carousel', 'reel', 'story', 'highlight']
    author_username: str | None = Field(default=None, max_length=200)
    caption: str | None = Field(default=None, max_length=5000)
    thumbnail_url: str | None = Field(default=None, max_length=2000)
    external_id: str | None = Field(default=None, max_length=200)
    posted_at: datetime | None = None

    @field_validator('source_url')
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('source_url must use http or https.')
        return value


class CollectionItemResponse(BaseModel):
    id: str
    collection_id: str
    source_url: str
    content_type: str
    author_username: str | None
    caption: str | None
    thumbnail_url: str | None
    external_id: str | None
    added_at: datetime
    posted_at: datetime | None
    downloaded_job_id: str | None


class CollectionDownloadRequest(BaseModel):
    item_ids: list[str] | None = None
    preset: Literal['best', '1080p', '720p', 'audio'] = 'best'
    concurrent_fragments: int = Field(default=8, ge=1, le=32)
    retries: int = Field(default=10, ge=1, le=100)
