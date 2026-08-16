from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MediaFormat:
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


@dataclass(frozen=True, slots=True)
class MediaAnalysis:
    source_url: str
    webpage_url: str | None
    title: str | None
    uploader: str | None
    duration_seconds: float | None
    thumbnail: str | None
    extractor: str | None
    is_live: bool | None
    formats: list[MediaFormat]


def _as_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_float(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_media_analysis(payload: dict[str, Any], source_url: str) -> MediaAnalysis:
    raw_formats = payload.get('formats')
    formats: list[MediaFormat] = []
    if isinstance(raw_formats, list):
        for item in raw_formats:
            if not isinstance(item, dict):
                continue
            format_id = item.get('format_id')
            if format_id is None:
                continue
            formats.append(
                MediaFormat(
                    format_id=str(format_id),
                    ext=str(item['ext']) if item.get('ext') else None,
                    width=_as_int(item.get('width')),
                    height=_as_int(item.get('height')),
                    fps=_as_float(item.get('fps')),
                    vcodec=str(item['vcodec']) if item.get('vcodec') else None,
                    acodec=str(item['acodec']) if item.get('acodec') else None,
                    filesize=_as_int(item.get('filesize') or item.get('filesize_approx')),
                    tbr=_as_float(item.get('tbr')),
                    protocol=str(item['protocol']) if item.get('protocol') else None,
                )
            )

    formats.sort(
        key=lambda item: (
            item.height or -1,
            item.width or -1,
            item.tbr or -1,
            item.format_id,
        ),
        reverse=True,
    )

    return MediaAnalysis(
        source_url=source_url,
        webpage_url=str(payload['webpage_url']) if payload.get('webpage_url') else None,
        title=str(payload['title']) if payload.get('title') else None,
        uploader=str(payload['uploader']) if payload.get('uploader') else None,
        duration_seconds=_as_float(payload.get('duration')),
        thumbnail=str(payload['thumbnail']) if payload.get('thumbnail') else None,
        extractor=str(payload['extractor_key'] or payload['extractor']) if payload.get('extractor_key') or payload.get('extractor') else None,
        is_live=payload.get('is_live') if isinstance(payload.get('is_live'), bool) else None,
        formats=formats[:40],
    )
