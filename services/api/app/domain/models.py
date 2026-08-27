from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .errors import DownloadErrorCategory


class DownloadStatus(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
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
    """Which subprocess runs the job. Orthogonal to DownloadSourceType:
    source_type is about how the URL was obtained (a pasted page/direct URL
    vs. a browser capture), engine is about which tool downloads it."""

    YT_DLP = 'yt_dlp'
    GALLERY_DL = 'gallery_dl'


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
