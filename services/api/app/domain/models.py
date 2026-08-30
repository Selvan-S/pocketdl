from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .errors import DownloadErrorCategory


class DownloadStatus(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    PAUSED = 'paused'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


class ImpersonationMode(StrEnum):
    NONE = 'none'
    AUTO = 'auto'
    CHROME = 'chrome'


class DownloadSourceType(StrEnum):
    STANDARD = 'standard'
    CAPTURED = 'captured'


class DownloadEngine(StrEnum):
    """Which tool runs the job -- a subprocess for YT_DLP/GALLERY_DL, an
    in-process library call for INSTALOADER. Orthogonal to
    DownloadSourceType: source_type is about how the URL was obtained (a
    pasted page/direct URL vs. a browser capture), engine is about which
    tool downloads it."""

    YT_DLP = 'yt_dlp'
    GALLERY_DL = 'gallery_dl'
    INSTALOADER = 'instaloader'


class ConflictStrategy(StrEnum):
    """What to do when the target file already exists.

    SKIP is the default and matches yt-dlp's own behaviour (don't re-download
    or clobber). OVERWRITE replaces it. RENAME writes a " (N)"-suffixed copy.
    """

    SKIP = 'skip'
    OVERWRITE = 'overwrite'
    RENAME = 'rename'


@dataclass(frozen=True, slots=True)
class MediaOptions:
    """Optional per-download media choices that only apply to standard
    (yt-dlp) downloads: subtitles and preferred audio-track language. Bundled
    so they can ride the create/download chain as one value instead of a
    growing list of scalars. Defaults are "no subtitles, no language
    preference", i.e. today's behaviour, so captured/collection downloads
    that never set them are unaffected.
    """

    subtitles: bool = False
    # Comma-separated language codes (e.g. "en,es") or "all". Only used when
    # subtitles is True.
    subtitle_langs: str = 'en'
    # Embed into the media container instead of writing a sidecar file.
    embed_subtitles: bool = False
    # Preferred audio-track language when a source offers several; maps to
    # yt-dlp's format sorting rather than a hard filter, so a source with a
    # single track is unaffected.
    audio_language: str | None = None
    # What to do when the output file already exists. A file-write concern
    # rather than a media one, but grouped here so it rides the same
    # create/download channel. Applied to standard (yt-dlp) downloads;
    # captured downloads already rename on conflict.
    conflict_strategy: ConflictStrategy = ConflictStrategy.SKIP


@dataclass(slots=True)
class RequestContext:
    page_url: str | None = None
    referer: str | None = None
    origin: str | None = None
    user_agent: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    impersonation: ImpersonationMode = ImpersonationMode.AUTO


@dataclass(slots=True)
class DownloadJob:
    id: str
    url: str
    filename: str | None
    title: str | None
    status: DownloadStatus
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
    source_type: DownloadSourceType
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    capture_id: str | None = None
    engine: DownloadEngine = DownloadEngine.YT_DLP
    collection_item_id: str | None = None
