import pytest

from app.application.captures.service import CaptureService
from app.domain.captures import CaptureType, MetadataStatus
from support import FakeMediaProbe, InMemoryCaptureRepository


@pytest.mark.asyncio
async def test_capture_filters_sensitive_headers_and_deduplicates() -> None:
    repo = InMemoryCaptureRepository()
    service = CaptureService(repo, FakeMediaProbe())
    first = await service.capture(
        media_url='https://cdn.example/video/master.m3u8?x=1',
        page_url='https://site.example/video',
        page_title='Example',
        referer='https://site.example/',
        origin='https://site.example',
        user_agent='Chrome',
        headers={'Origin': 'https://site.example', 'Cookie': 'secret', 'X-Test': 'ok'},
        capture_type=CaptureType.HLS,
        content_type='application/vnd.apple.mpegurl',
        content_length_bytes=500,
    )
    second = await service.capture(
        media_url='https://cdn.example/video/master.m3u8?token=2',
        page_url=first.page_url,
        page_title='Example',
        referer=first.referer,
        origin=first.origin,
        user_agent=first.user_agent,
        headers={'X-Test': 'ok'},
        capture_type=CaptureType.HLS,
        content_type=first.content_type,
        content_length_bytes=700,
    )
    assert first.id == second.id
    assert second.media_url.endswith('token=2')
    assert 'Cookie' not in first.headers
    assert first.headers['X-Test'] == 'ok'


@pytest.mark.asyncio
async def test_capture_deduplicates_signed_token_embedded_in_path() -> None:
    repo = InMemoryCaptureRepository()
    service = CaptureService(repo, FakeMediaProbe())
    first = await service.capture(
        media_url='https://cdn.example/media/8f7a2b91c3d445fabb0e7a1c9d4e6f21/master.m3u8',
        page_url='https://site.example/video',
        page_title='Example',
        referer=None,
        origin=None,
        user_agent=None,
        headers={},
        capture_type=CaptureType.HLS,
        content_type='application/vnd.apple.mpegurl',
        content_length_bytes=None,
    )
    second = await service.capture(
        media_url='https://cdn.example/media/1a2b3c4d5e6f708192a3b4c5d6e7f809/master.m3u8',
        page_url=first.page_url,
        page_title='Example',
        referer=None,
        origin=None,
        user_agent=None,
        headers={},
        capture_type=CaptureType.HLS,
        content_type='application/vnd.apple.mpegurl',
        content_length_bytes=None,
    )
    assert first.id == second.id
    assert len(await repo.list()) == 1


@pytest.mark.asyncio
async def test_capture_does_not_report_manifest_size_as_media_size() -> None:
    """The browser's Content-Length for an hls/dash capture is the manifest
    text file's size, not the underlying media's -- storing it would show a
    tiny, wrong number (e.g. "500 B") for a real multi-hundred-MB stream."""
    repo = InMemoryCaptureRepository()
    service = CaptureService(repo, FakeMediaProbe())
    capture = await service.capture(
        media_url='https://cdn.example/video/master.m3u8',
        page_url='https://site.example/video',
        page_title='Example',
        referer=None,
        origin=None,
        user_agent=None,
        headers={},
        capture_type=CaptureType.HLS,
        content_type='application/vnd.apple.mpegurl',
        content_length_bytes=500,
    )
    assert capture.size_bytes is None

    updated = await service.capture(
        media_url='https://cdn.example/video/master.m3u8?token=2',
        page_url=capture.page_url,
        page_title='Example',
        referer=None,
        origin=None,
        user_agent=None,
        headers={},
        capture_type=CaptureType.HLS,
        content_type='application/vnd.apple.mpegurl',
        content_length_bytes=700,
    )
    assert updated.id == capture.id
    assert updated.size_bytes is None


@pytest.mark.asyncio
async def test_capture_reports_direct_media_content_length_as_size() -> None:
    """A direct media request's Content-Length is the file's real size, so it
    should still be recorded (unlike the hls/dash manifest case above)."""
    repo = InMemoryCaptureRepository()
    service = CaptureService(repo, FakeMediaProbe())
    capture = await service.capture(
        media_url='https://cdn.example/video.mp4',
        page_url='https://site.example/video',
        page_title='Example',
        referer=None,
        origin=None,
        user_agent=None,
        headers={},
        capture_type=CaptureType.MEDIA,
        content_type='video/mp4',
        content_length_bytes=123_456,
    )
    assert capture.size_bytes == 123_456


@pytest.mark.asyncio
async def test_capture_metadata_enrichment_updates_media_details() -> None:
    repo = InMemoryCaptureRepository()
    service = CaptureService(repo, FakeMediaProbe())
    capture = await service.capture(
        media_url='https://cdn.example/video.mp4',
        page_url='https://site.example/video',
        page_title='Example',
        referer='https://site.example/',
        origin='https://site.example',
        user_agent='Chrome',
        headers={},
        capture_type=CaptureType.MEDIA,
        content_type='video/mp4',
        content_length_bytes=500,
    )
    assert capture.metadata_status is MetadataStatus.PENDING
    await service.enrich_metadata(capture.id)
    updated = await repo.get(capture.id)
    assert updated is not None
    assert updated.metadata_status is MetadataStatus.READY
    assert updated.size_bytes == 12_345
    assert updated.duration_seconds == 12.5
    assert updated.width == 1280
    assert updated.height == 720
