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


class VariantStatus(StrEnum):
    """Progress of resolving a capture's quality variants.

    ``NONE`` means the question does not apply (a direct media or DASH
    capture, or an HLS media playlist that is not a master), and is distinct
    from ``FAILED``, where the master was worth reading but could not be.
    """

    PENDING = 'pending'
    READY = 'ready'
    FAILED = 'failed'
    NONE = 'none'


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


def make_variant_key(variant_url: str, page_url: str | None) -> str:
    """Key a master's variant the way an incoming capture of that same URL
    would be keyed, so the two can be matched and the duplicate card avoided.

    A variant sub-playlist is always ``hls``: the browser classifies it by its
    ``.m3u8`` extension exactly as it classified the master.
    """
    return make_source_key(variant_url, page_url, CaptureType.HLS)


@dataclass(slots=True)
class CaptureVariant:
    """One quality level of a captured HLS master, as stored against it.

    Variants are not captures of their own: they are never separate cards,
    and the browser's own capture of a variant URL is folded back into the
    master via :func:`make_variant_key`.
    """

    capture_id: str
    position: int
    variant_key: str
    url: str
    audio_url: str | None
    bandwidth_bps: int | None
    width: int | None
    height: int | None
    codecs: str | None
    frame_rate: float | None
    name: str | None


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
    variants_status: VariantStatus = VariantStatus.PENDING


# Configurable heuristics for the "very short/wrong capture" backlog item --
# deliberately a flag surfaced to the UI, never a hard delete, since a
# legitimate-looking request can still be exactly what the user wants even if
# it trips one of these signals.
SHORT_DURATION_SECONDS = 10.0
TINY_MEDIA_SIZE_BYTES = 50_000

# Mirrors the browser extension's client-side heuristic
# (apps/browser-extension/src/background.ts, isLikelyMediaSegment) as a
# backend-side backstop: captures made before that filter existed, or from
# any future non-extension client, still get flagged here.
_SEGMENT_PATH_RE = re.compile(r'/(?:segments?|chunks?|fragments?|init|init-segment|parts?)\b', re.IGNORECASE)
_SEGMENT_EXTENSION_RE = re.compile(r'\.(?:m4s|cmfv|cmfa|ts)(?:$|[?#])', re.IGNORECASE)
_SEGMENT_QUERY_RE = re.compile(r'[?&](?:segment|chunk|fragment|part|range|seg|frag)=', re.IGNORECASE)


def looks_like_media_segment(media_url: str) -> bool:
    return bool(
        _SEGMENT_PATH_RE.search(media_url)
        or _SEGMENT_EXTENSION_RE.search(media_url)
        or _SEGMENT_QUERY_RE.search(media_url)
    )


def is_suspicious_capture(capture: CapturedSource) -> bool:
    """True if this capture is likely a fragment/segment rather than the
    intended media, or otherwise implausibly short.

    Applies to every capture_type, unlike the duration-only, media-only check
    it replaces: an hls/dash capture whose *probed* duration turns out to be
    a couple of seconds -- the exact scenario CLAUDE.md's backlog cites --
    previously could never be flagged, since capture_type=media was the only
    kind checked at all.
    """
    if capture.duration_seconds is not None and capture.duration_seconds < SHORT_DURATION_SECONDS:
        return True
    if capture.capture_type is CaptureType.MEDIA and capture.size_bytes is not None and capture.size_bytes < TINY_MEDIA_SIZE_BYTES:
        return True
    return looks_like_media_segment(capture.media_url)
