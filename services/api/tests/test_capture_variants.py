import pytest

from app.application.captures.service import CaptureService
from app.domain.captures import CaptureType, VariantStatus
from support import FakeManifestFetcher, FakeMediaProbe, InMemoryCaptureRepository

MASTER_URL = 'https://cdn.example/hls/master.m3u8'
PAGE_URL = 'https://site.example/watch/1'

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=1280x720
720p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2560000,RESOLUTION=1920x1080
1080p/index.m3u8
"""

MEDIA_PLAYLIST = '#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6.000,\nseg-0.ts\n#EXT-X-ENDLIST\n'


def build_service(playlists: dict[str, str] | None = None, error: Exception | None = None):
    repository = InMemoryCaptureRepository()
    fetcher = FakeManifestFetcher(playlists, error)
    return CaptureService(repository, FakeMediaProbe(), fetcher), repository, fetcher


async def capture_url(service: CaptureService, media_url: str, capture_type: CaptureType = CaptureType.HLS):
    return await service.capture(
        media_url=media_url,
        page_url=PAGE_URL,
        page_title='Example',
        referer='https://site.example/',
        origin='https://site.example',
        user_agent='Chrome',
        headers={},
        capture_type=capture_type,
        content_type='application/vnd.apple.mpegurl',
        content_length_bytes=500,
    )


@pytest.mark.asyncio
async def test_master_playlist_variants_are_recorded_against_the_capture() -> None:
    service, repository, _ = build_service({MASTER_URL: MASTER})

    capture = await capture_url(service, MASTER_URL)
    await service.resolve_variants(capture.id)

    variants = await repository.list_variants(capture.id)
    assert [variant.height for variant in variants] == [720, 1080]
    assert [variant.position for variant in variants] == [0, 1]
    assert (await repository.get(capture.id)).variants_status is VariantStatus.READY


@pytest.mark.asyncio
async def test_capturing_a_variant_after_the_master_does_not_create_a_second_card() -> None:
    """The player fetches the master and then a quality sub-playlist. Both are
    the same video and must share one card."""
    service, repository, _ = build_service({MASTER_URL: MASTER})

    master = await capture_url(service, MASTER_URL)
    await service.resolve_variants(master.id)

    returned = await capture_url(service, 'https://cdn.example/hls/720p/index.m3u8')

    assert returned.id == master.id
    assert len(await repository.list()) == 1


@pytest.mark.asyncio
async def test_a_variant_captured_before_the_master_is_absorbed_into_it() -> None:
    """Capture order is not guaranteed, so a variant that already has its own
    card is removed once the master reveals it as one of its qualities."""
    service, repository, _ = build_service({MASTER_URL: MASTER})

    variant_capture = await capture_url(service, 'https://cdn.example/hls/1080p/index.m3u8')
    master = await capture_url(service, MASTER_URL)
    assert len(await repository.list()) == 2

    await service.resolve_variants(master.id)

    remaining = await repository.list()
    assert [item.id for item in remaining] == [master.id]
    assert await repository.get(variant_capture.id) is None


@pytest.mark.asyncio
async def test_a_variant_capture_refreshes_the_master_request_context() -> None:
    """The variant request is the more recent proof of what the site accepts,
    so its context is worth keeping even though its card is not."""
    service, repository, _ = build_service({MASTER_URL: MASTER})
    master = await capture_url(service, MASTER_URL)
    await service.resolve_variants(master.id)

    await service.capture(
        media_url='https://cdn.example/hls/720p/index.m3u8',
        page_url=PAGE_URL,
        page_title='Example',
        referer='https://site.example/watch/1',
        origin='https://site.example',
        user_agent='Chrome/Newer',
        headers={'X-Test': 'ok'},
        capture_type=CaptureType.HLS,
        content_type='application/vnd.apple.mpegurl',
        content_length_bytes=400,
    )

    stored = await repository.get(master.id)
    assert stored.user_agent == 'Chrome/Newer'
    assert stored.referer == 'https://site.example/watch/1'
    assert stored.headers == {'X-Test': 'ok'}


@pytest.mark.asyncio
async def test_media_playlist_capture_reports_no_variants() -> None:
    """"No qualities to choose from" is a normal outcome, not a failure."""
    service, repository, _ = build_service({MASTER_URL: MEDIA_PLAYLIST})

    capture = await capture_url(service, MASTER_URL)
    await service.resolve_variants(capture.id)

    assert (await repository.get(capture.id)).variants_status is VariantStatus.NONE
    assert await repository.list_variants(capture.id) == []


@pytest.mark.asyncio
async def test_unreachable_playlist_leaves_the_capture_downloadable() -> None:
    service, repository, _ = build_service(error=RuntimeError('403'))

    capture = await capture_url(service, MASTER_URL)
    await service.resolve_variants(capture.id)

    stored = await repository.get(capture.id)
    assert stored.variants_status is VariantStatus.FAILED
    assert stored.media_url == MASTER_URL


@pytest.mark.asyncio
async def test_non_hls_captures_are_never_fetched() -> None:
    """A DASH .mpd already carries every representation, and a direct media
    URL has none -- neither is worth a network round trip."""
    service, repository, fetcher = build_service({MASTER_URL: MASTER})

    dash = await capture_url(service, 'https://cdn.example/dash/manifest.mpd', CaptureType.DASH)
    await service.resolve_variants(dash.id)

    assert fetcher.requested == []
    assert (await repository.get(dash.id)).variants_status is VariantStatus.NONE


@pytest.mark.asyncio
async def test_re_resolving_replaces_a_stale_variant_list() -> None:
    service, repository, fetcher = build_service({MASTER_URL: MASTER})
    capture = await capture_url(service, MASTER_URL)
    await service.resolve_variants(capture.id)

    fetcher.playlists[MASTER_URL] = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=640x360\n360p/index.m3u8\n'
    await service.resolve_variants(capture.id)

    variants = await repository.list_variants(capture.id)
    assert [variant.height for variant in variants] == [360]
