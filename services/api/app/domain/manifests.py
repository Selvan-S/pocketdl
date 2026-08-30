"""HLS master-playlist parsing.

A master playlist advertises the same content at several qualities, each as
its own sub-playlist URL. Players fetch the master and then one or more
variants, so browser capture sees each of them as a separate media request
and -- before this module existed -- created a separate card per quality for
what is really one video.

Parsing the master is the only reliable way to know that
``.../720p/index.m3u8`` and ``.../1080p/index.m3u8`` are the same title:
their paths differ genuinely, so URL normalization (which handles rotating
signed tokens) cannot and must not collapse them.

Scope is deliberately HLS-only. A DASH ``.mpd`` already carries every
representation inside a single manifest file, so a player fetches exactly one
URL and the duplicate-card problem does not arise there.
"""

from dataclasses import dataclass
from urllib.parse import urljoin
import re

MASTER_TAG = '#EXT-X-STREAM-INF'
_MEDIA_TAG = '#EXT-X-MEDIA'

# Attribute lists are comma-separated, but quoted values may themselves
# contain commas (CODECS="avc1.4d401f,mp4a.40.2"), so a plain split(',') is
# wrong. This matches NAME=value pairs where value is either a quoted string
# or a run of unquoted non-comma characters.
_ATTRIBUTE_RE = re.compile(r'([A-Za-z0-9_-]+)=("[^"]*"|[^,]*)')
_RESOLUTION_RE = re.compile(r'^(\d+)x(\d+)$', re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class VariantStream:
    """One quality level advertised by a master playlist."""

    index: int
    url: str
    bandwidth_bps: int | None
    width: int | None
    height: int | None
    codecs: str | None
    frame_rate: float | None
    name: str | None
    audio_url: str | None
    """Sub-playlist of the matching ``#EXT-X-MEDIA`` audio rendition, when the
    variant references an audio group instead of muxing audio into its own
    segments. Downloading the variant URL alone in that case yields a silent
    file, so the audio playlist has to be fetched as a second input."""


def parse_attributes(value: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for name, raw in _ATTRIBUTE_RE.findall(value):
        attributes[name.upper()] = raw.strip().strip('"')
    return attributes


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_resolution(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    match = _RESOLUTION_RE.match(value.strip())
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def is_master_playlist(text: str) -> bool:
    """True when the playlist advertises variant streams rather than segments."""
    return any(line.strip().upper().startswith(MASTER_TAG) for line in text.splitlines())


def _audio_renditions(lines: list[str], base_url: str) -> dict[str, str]:
    """Map audio GROUP-ID -> rendition playlist URL (default rendition wins)."""
    renditions: dict[str, str] = {}
    defaults: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped.upper().startswith(_MEDIA_TAG):
            continue
        attributes = parse_attributes(stripped.split(':', 1)[-1])
        if attributes.get('TYPE', '').upper() != 'AUDIO':
            continue
        group_id = attributes.get('GROUP-ID')
        uri = attributes.get('URI')
        if not group_id or not uri:
            # An audio rendition with no URI is muxed into the video segments,
            # so there is nothing extra to download for that group.
            continue
        is_default = attributes.get('DEFAULT', '').upper() == 'YES'
        if group_id in defaults and not is_default:
            continue
        renditions[group_id] = urljoin(base_url, uri)
        if is_default:
            defaults.add(group_id)
    return renditions


@dataclass(frozen=True, slots=True)
class SubtitleRendition:
    """One ``#EXT-X-MEDIA:TYPE=SUBTITLES`` track from a master playlist."""

    url: str
    language: str | None
    name: str | None
    is_default: bool


def parse_subtitle_renditions(text: str, base_url: str) -> list[SubtitleRendition]:
    """Subtitle tracks advertised by a master playlist, in file order.

    Empty for a media playlist or one with no subtitle renditions -- most
    captures have none, and that is not an error."""
    renditions: list[SubtitleRendition] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith(_MEDIA_TAG):
            continue
        attributes = parse_attributes(stripped.split(':', 1)[-1])
        if attributes.get('TYPE', '').upper() != 'SUBTITLES':
            continue
        uri = attributes.get('URI')
        if not uri:
            continue
        renditions.append(SubtitleRendition(
            url=urljoin(base_url, uri),
            language=attributes.get('LANGUAGE') or None,
            name=attributes.get('NAME') or None,
            is_default=attributes.get('DEFAULT', '').upper() == 'YES',
        ))
    return renditions


def pick_subtitle_rendition(renditions: list[SubtitleRendition], language: str | None) -> SubtitleRendition | None:
    """Choose a subtitle track: an exact/prefix language match if a language
    was asked for, else the default track, else the first one."""
    if not renditions:
        return None
    if language:
        wanted = language.lower()
        for rendition in renditions:
            if rendition.language and rendition.language.lower().startswith(wanted):
                return rendition
    for rendition in renditions:
        if rendition.is_default:
            return rendition
    return renditions[0]


def parse_master_playlist(text: str, base_url: str) -> list[VariantStream]:
    """Parse the variant streams of a master playlist.

    Returns an empty list for a media (segment) playlist or unparseable text,
    so callers can treat "not a master" and "nothing to group" identically.
    """
    lines = text.splitlines()
    renditions = _audio_renditions(lines, base_url)
    variants: list[VariantStream] = []

    index = 0
    pending: dict[str, str] | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper().startswith(MASTER_TAG):
            pending = parse_attributes(stripped.split(':', 1)[-1])
            continue
        if stripped.startswith('#'):
            continue
        if pending is None:
            continue

        width, height = _parse_resolution(pending.get('RESOLUTION'))
        audio_group = pending.get('AUDIO')
        variants.append(
            VariantStream(
                index=index,
                url=urljoin(base_url, stripped),
                bandwidth_bps=_parse_int(pending.get('AVERAGE-BANDWIDTH') or pending.get('BANDWIDTH')),
                width=width,
                height=height,
                codecs=pending.get('CODECS') or None,
                frame_rate=_parse_float(pending.get('FRAME-RATE')),
                name=pending.get('NAME') or None,
                audio_url=renditions.get(audio_group) if audio_group else None,
            )
        )
        index += 1
        pending = None

    return variants


def quality_label(variant: VariantStream) -> str:
    """Human-facing name for a quality option.

    Prefers the encoded height (what users think in), then the playlist's own
    NAME, then bitrate. Never returns an empty string, so the UI always has
    something to render on the chip.
    """
    if variant.height:
        return f'{variant.height}p'
    if variant.name:
        return variant.name
    if variant.bandwidth_bps:
        return f'{variant.bandwidth_bps / 1_000_000:.1f} Mbps'
    return f'Variant {variant.index + 1}'


def estimated_size_bytes(bandwidth_bps: int | None, duration_seconds: float | None) -> int | None:
    """Bitrate x duration, for a variant whose real byte size is unknown.

    HLS/DASH sizes cannot be known exactly before downloading, so this is only
    ever an estimate -- it is deliberately returned under a name the API and
    UI carry through as such, rather than being written into ``size_bytes``
    where it would be indistinguishable from a real Content-Length.
    """
    if not bandwidth_bps or not duration_seconds or duration_seconds <= 0:
        return None
    return int(bandwidth_bps * duration_seconds / 8)
