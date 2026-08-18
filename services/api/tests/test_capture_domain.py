from app.domain.captures import CaptureType, make_source_key, normalize_media_url


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
