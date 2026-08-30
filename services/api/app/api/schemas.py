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
    # Subtitles / audio-track options. Only applied to standard (yt-dlp)
    # downloads; ignored for captured sources.
    subtitles: bool = False
    subtitle_langs: str = Field(default='en', min_length=1, max_length=100)
    embed_subtitles: bool = False
    audio_language: str | None = Field(default=None, max_length=20)
    # What to do if the output file already exists (standard downloads).
    conflict_strategy: Literal['skip', 'overwrite', 'rename'] = 'skip'
    request_context: RequestContextRequest = Field(default_factory=RequestContextRequest)

    @field_validator('subtitle_langs')
    @classmethod
    def validate_subtitle_langs(cls, value: str) -> str:
        # "all" or a comma-separated list of language codes -- the same shape
        # yt-dlp's --sub-langs accepts. Kept strict so it can't inject flags.
        if value != 'all' and not re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?(?:,[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?)*', value):
            raise ValueError('subtitle_langs must be "all" or comma-separated language codes like "en,es".')
        return value

    @field_validator('audio_language')
    @classmethod
    def validate_audio_language(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?', value):
            raise ValueError('audio_language must be a language code like "en" or "pt-BR".')
        return value

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


class UpdateCheckResponse(BaseModel):
    current: str | None
    latest: str | None
    update_available: bool
    error: str | None = None


class DownloadHistoryResponse(BaseModel):
    items: list[DownloadResponse]
    # True when older finished downloads exist beyond this page.
    has_more: bool


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
    subtitles: bool = False
    """Include a subtitle track from the HLS master (if it advertises any).
    No-op for non-HLS captures or masters without subtitles."""
    subtitle_language: str | None = Field(default=None, max_length=20)
    embed_subtitles: bool = True
    """True embeds the subtitle into the mp4; False writes a sidecar .srt
    next to the video. Only meaningful when subtitles is true."""


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
    filename_template: str = 'title'
    clean_titles: bool = True


class SettingsUpdateRequest(BaseModel):
    download_directory: str = Field(min_length=1, max_length=2000)
    # Output-naming preferences. Optional so a caller can update just the
    # directory (the existing behaviour) without touching them.
    filename_template: Literal['title', 'uploader-title', 'date-title', 'title-id'] | None = None
    clean_titles: bool | None = None


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
    # Doubles as the paging cursor: ask again with the oldest posted_at you
    # already have to get the page behind it. See
    # InstaloaderService.ProfileItemPage.next_posted_before for why the
    # cursor is a date rather than an opaque handle.
    posted_before: datetime | None = None
    # Omitted means the default page size. Raising it costs proportionally
    # more requests to Instagram and is clamped server-side, but is much
    # cheaper than paging repeatedly, since each page re-scans the ones
    # above it.
    limit: int | None = Field(default=None, ge=1, le=200)

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
    profile_username: str | None = None
    caption: str | None
    thumbnail_url: str | None
    external_id: str | None
    posted_at: datetime | None = None


class InstagramProfilePreviewResponse(BaseModel):
    items: list[ProfileItemPreviewResponse]
    # True when a bucket exactly filled its page, i.e. there is genuinely
    # more behind this. Previously the result was silently truncated with no
    # way to tell, and no way to ask for the rest.
    has_more: bool = False
    # Pass back as `posted_before` to fetch the next page. Null when this
    # page is the end. Callers must de-duplicate by external_id, since items
    # sharing a timestamp with the last of this page can reappear.
    next_posted_before: datetime | None = None


class CollectionAddProfileItemsRequest(InstagramProfilePreviewRequest):
    """Run a profile query server-side and add everything it matches.

    The point is that choosing "all of it" should not require rendering all
    of it first: a profile with 128 reels needed three manual pages and 128
    cards on screen before the user could select them.
    """


class CollectionAddProfileItemsResponse(BaseModel):
    added: int
    already_present: int
    # True when the query filled its page, i.e. items matching the filters
    # were left behind. Reported rather than hidden so the UI can say so and
    # suggest narrowing the date range.
    has_more: bool
    next_posted_before: datetime | None = None


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
    platform: Literal['instagram', 'generic'] = 'instagram'
    name: str = Field(min_length=1, max_length=200)


class CollectionRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CollectionAddUrlsRequest(BaseModel):
    """Add plain URLs to a generic playlist. Each becomes an item downloaded
    via yt-dlp, the same as a paste-a-URL download."""

    urls: list[str] = Field(min_length=1, max_length=500)

    @field_validator('urls')
    @classmethod
    def validate_urls(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in value:
            url = raw.strip()
            if not url:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                raise ValueError(f'Not an http(s) URL: {url[:80]}')
            cleaned.append(url)
        if not cleaned:
            raise ValueError('No valid URLs provided.')
        return cleaned


class CollectionAddUrlsResponse(BaseModel):
    added: int
    already_present: int


class CollectionResponse(BaseModel):
    id: str
    platform: str
    name: str
    item_count: int
    # How many of item_count have completed a download. Lets a client show
    # "Pending 78 / Downloaded 50" and drive a live badge without shipping
    # every row to compute it.
    downloaded_count: int = 0
    created_at: datetime
    updated_at: datetime


class CollectionItemAddRequest(BaseModel):
    source_url: str
    content_type: Literal['post', 'carousel', 'reel', 'story', 'highlight']
    author_username: str | None = Field(default=None, max_length=200)
    profile_username: str | None = Field(default=None, max_length=200)
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
    profile_username: str | None = None
    caption: str | None
    thumbnail_url: str | None
    external_id: str | None
    added_at: datetime
    posted_at: datetime | None
    downloaded_job_id: str | None


class FolderUsageResponse(BaseModel):
    name: str
    bytes: int
    file_count: int


class StorageUsageResponse(BaseModel):
    directory: str
    total_bytes: int
    free_bytes: int
    disk_total_bytes: int
    folders: list[FolderUsageResponse]


class DownloadPresetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    preset: Literal['best', '1080p', '720p', '480p', 'audio'] = 'best'
    concurrent_fragments: int = Field(default=8, ge=1, le=32)
    retries: int = Field(default=10, ge=1, le=100)
    use_aria2: bool = False


class DownloadPresetResponse(BaseModel):
    id: str
    name: str
    preset: str
    concurrent_fragments: int
    retries: int
    use_aria2: bool
    created_at: datetime


class CollectionDownloadRequest(BaseModel):
    item_ids: list[str] | None = None
    preset: Literal['best', '1080p', '720p', 'audio'] = 'best'
    concurrent_fragments: int = Field(default=8, ge=1, le=32)
    retries: int = Field(default=10, ge=1, le=100)


# --- Import / export bundle (product-polish Round 2) ------------------------

class SettingsExport(BaseModel):
    download_directory: str | None = None


class PresetExport(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    preset: Literal['best', '1080p', '720p', '480p', 'audio'] = 'best'
    concurrent_fragments: int = Field(default=8, ge=1, le=32)
    retries: int = Field(default=10, ge=1, le=100)
    use_aria2: bool = False


class CollectionItemExport(BaseModel):
    source_url: str = Field(max_length=2000)
    content_type: Literal['post', 'carousel', 'reel', 'story', 'highlight']
    author_username: str | None = Field(default=None, max_length=200)
    profile_username: str | None = Field(default=None, max_length=200)
    caption: str | None = Field(default=None, max_length=5000)
    thumbnail_url: str | None = Field(default=None, max_length=2000)
    external_id: str | None = Field(default=None, max_length=200)
    posted_at: datetime | None = None


class CollectionExport(BaseModel):
    platform: Literal['instagram'] = 'instagram'
    name: str = Field(min_length=1, max_length=200)
    items: list[CollectionItemExport] = Field(default_factory=list)


class ExportBundle(BaseModel):
    """The full backup/restore document. Doubles as the import request body;
    pydantic ignores unknown fields, so a newer export stays loadable."""

    pocketdl_export_version: int = 1
    exported_at: datetime | None = None
    settings: SettingsExport | None = None
    presets: list[PresetExport] = Field(default_factory=list)
    collections: list[CollectionExport] = Field(default_factory=list)


class ImportResultResponse(BaseModel):
    imported_presets: int
    imported_collections: int
    imported_items: int
    settings_applied: bool
    notes: list[str] = Field(default_factory=list)
