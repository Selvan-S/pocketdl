from datetime import datetime, timezone

from app.domain.captures import (
    CaptureStatus,
    CaptureType,
    CapturedSource,
    MetadataStatus,
    is_suspicious_capture,
    looks_like_media_segment,
    make_source_key,
    normalize_media_url,
)


def _make_capture(**overrides) -> CapturedSource:
    defaults = dict(
        id='test',
        source_key='key',
        media_url='https://cdn.example/video/master.m3u8',
        page_url='https://site.example/watch',
        page_title='Example',
        referer=None,
        origin=None,
        user_agent=None,
        headers={},
        capture_type=CaptureType.HLS,
        content_type='application/vnd.apple.mpegurl',
        size_bytes=None,
        duration_seconds=None,
        width=None,
        height=None,
        metadata_status=MetadataStatus.READY,
        metadata_error=None,
        status=CaptureStatus.CAPTURED,
        created_at=datetime.now(timezone.utc),
        used_at=None,
    )
    defaults.update(overrides)
    return CapturedSource(**defaults)


def test_normalize_media_url_ignores_query_string_signed_tokens() -> None:
    first = normalize_media_url('https://cdn.example/video/master.m3u8?token=abc123&expires=1')
    second = normalize_media_url('https://cdn.example/video/master.m3u8?token=xyz789&expires=2')
    assert first == second


def test_normalize_media_url_ignores_signed_tokens_embedded_in_the_path() -> None:
    first = normalize_media_url('https://cdn.example/media/8f7a2b91c3d445fabb0e7a1c9d4e6f21/master.m3u8')
    second = normalize_media_url('https://cdn.example/media/1a2b3c4d5e6f708192a3b4c5d6e7f809/master.m3u8')
    assert first == second


def test_normalize_media_url_ignores_uuid_signed_tokens_in_the_path() -> None:
    first = normalize_media_url('https://cdn.example/hls/550e8400-e29b-41d4-a716-446655440000/index.m3u8')
    second = normalize_media_url('https://cdn.example/hls/6ba7b810-9dad-11d1-80b4-00c04fd430c8/index.m3u8')
    assert first == second


def test_normalize_media_url_preserves_distinct_manifest_filenames() -> None:
    """Different quality-variant filenames must stay distinct: grouping master
    and variant manifests together is a separate, unsolved problem, not
    something this normalization should silently paper over."""
    master = normalize_media_url('https://cdn.example/video/master.m3u8')
    variant = normalize_media_url('https://cdn.example/video/720p.m3u8')
    assert master != variant


def test_normalize_media_url_preserves_short_meaningful_segments() -> None:
    """Ordinary path segments (slugs, quality labels) must not be mistaken
    for opaque tokens."""
    a = normalize_media_url('https://cdn.example/videos/my-cool-video/master.m3u8')
    b = normalize_media_url('https://cdn.example/videos/another-video/master.m3u8')
    assert a != b


def test_normalize_media_url_preserves_numeric_content_ids() -> None:
    """Pure-digit path segments are treated as stable content IDs, not
    rotating tokens, so different videos stay distinguishable."""
    a = normalize_media_url('https://cdn.example/videos/1029384756/master.m3u8')
    b = normalize_media_url('https://cdn.example/videos/1029384757/master.m3u8')
    assert a != b


def test_make_source_key_stable_across_path_token_refresh() -> None:
    first = make_source_key(
        'https://cdn.example/media/8f7a2b91c3d445fabb0e7a1c9d4e6f21/master.m3u8',
        'https://site.example/watch',
        CaptureType.HLS,
    )
    second = make_source_key(
        'https://cdn.example/media/1a2b3c4d5e6f708192a3b4c5d6e7f809/master.m3u8',
        'https://site.example/watch',
        CaptureType.HLS,
    )
    assert first == second


def test_looks_like_media_segment_matches_common_fragment_patterns() -> None:
    assert looks_like_media_segment('https://cdn.example/hls/segment-0042.ts')
    assert looks_like_media_segment('https://cdn.example/hls/init-segment.mp4')
    assert looks_like_media_segment('https://cdn.example/dash/chunk_1_00001.m4s')
    assert looks_like_media_segment('https://cdn.example/video.mp4?range=0-1023')


def test_looks_like_media_segment_ignores_ordinary_media_urls() -> None:
    assert not looks_like_media_segment('https://cdn.example/videos/my-cool-video.mp4')
    assert not looks_like_media_segment('https://cdn.example/hls/master.m3u8')


def test_is_suspicious_capture_flags_short_duration_regardless_of_type() -> None:
    """An hls/dash capture that probes out to a couple of seconds must be
    flagged too -- the previous duration-only check applied to
    capture_type=media exclusively, so this exact scenario (cited in
    CLAUDE.md's backlog) could never be caught."""
    capture = _make_capture(capture_type=CaptureType.HLS, duration_seconds=2.0)
    assert is_suspicious_capture(capture)


def test_is_suspicious_capture_allows_normal_duration() -> None:
    capture = _make_capture(capture_type=CaptureType.HLS, duration_seconds=1800.0)
    assert not is_suspicious_capture(capture)


def test_is_suspicious_capture_flags_tiny_direct_media_size() -> None:
    capture = _make_capture(capture_type=CaptureType.MEDIA, media_url='https://cdn.example/video.mp4', size_bytes=2_048)
    assert is_suspicious_capture(capture)


def test_is_suspicious_capture_ignores_size_for_hls_dash() -> None:
    """size_bytes is intentionally unset for hls/dash (it would be the
    manifest's size, not the media's) -- it must never factor into this
    check for those types."""
    capture = _make_capture(capture_type=CaptureType.HLS, size_bytes=100)
    assert not is_suspicious_capture(capture)


def test_is_suspicious_capture_flags_segment_like_url() -> None:
    capture = _make_capture(
        capture_type=CaptureType.MEDIA,
        media_url='https://cdn.example/dash/chunk_1_00001.m4s',
        size_bytes=5_000_000,
    )
    assert is_suspicious_capture(capture)


def test_is_suspicious_capture_allows_plausible_capture() -> None:
    capture = _make_capture(
        capture_type=CaptureType.MEDIA,
        media_url='https://cdn.example/videos/my-cool-video.mp4',
        size_bytes=250_000_000,
        duration_seconds=1800.0,
    )
    assert not is_suspicious_capture(capture)
