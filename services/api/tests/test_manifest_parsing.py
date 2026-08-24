from app.domain.manifests import (
    estimated_size_bytes,
    is_master_playlist,
    parse_attributes,
    parse_master_playlist,
    quality_label,
)

MASTER = """#EXTM3U
#EXT-X-VERSION:4
#EXT-X-STREAM-INF:BANDWIDTH=1280000,RESOLUTION=1280x720,FRAME-RATE=29.970,CODECS="avc1.4d401f,mp4a.40.2"
720p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2560000,AVERAGE-BANDWIDTH=2100000,RESOLUTION=1920x1080,NAME="Full HD"
https://other-cdn.example/1080p/index.m3u8
"""

MEDIA_PLAYLIST = """#EXTM3U
#EXT-X-TARGETDURATION:6
#EXTINF:6.000,
segment-0.ts
#EXTINF:6.000,
segment-1.ts
#EXT-X-ENDLIST
"""

MASTER_WITH_AUDIO_GROUP = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aac",NAME="English",DEFAULT=YES,URI="audio/en.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",URI="subs/en.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,AUDIO="aac"
360p/video.m3u8
"""


def test_master_playlist_is_recognised_and_media_playlist_is_not() -> None:
    assert is_master_playlist(MASTER)
    assert not is_master_playlist(MEDIA_PLAYLIST)


def test_media_playlist_yields_no_variants() -> None:
    """A capture of one specific quality has nothing to choose between, and
    must not be mistaken for a master."""
    assert parse_master_playlist(MEDIA_PLAYLIST, 'https://cdn.example/720p/index.m3u8') == []


def test_variants_resolve_relative_and_absolute_uris_against_the_master() -> None:
    variants = parse_master_playlist(MASTER, 'https://cdn.example/hls/master.m3u8')

    assert [variant.url for variant in variants] == [
        'https://cdn.example/hls/720p/index.m3u8',
        'https://other-cdn.example/1080p/index.m3u8',
    ]
    assert [variant.index for variant in variants] == [0, 1]


def test_variant_attributes_are_parsed() -> None:
    first, second = parse_master_playlist(MASTER, 'https://cdn.example/hls/master.m3u8')

    assert (first.width, first.height) == (1280, 720)
    assert first.bandwidth_bps == 1_280_000
    assert first.frame_rate == 29.970
    # A quoted CODECS value contains a comma, which a naive split(',') on the
    # attribute list would treat as an attribute separator.
    assert first.codecs == 'avc1.4d401f,mp4a.40.2'
    # AVERAGE-BANDWIDTH is the better size predictor when a stream declares both.
    assert second.bandwidth_bps == 2_100_000
    assert second.name == 'Full HD'


def test_attribute_parsing_keeps_quoted_commas_together() -> None:
    attributes = parse_attributes('BANDWIDTH=100,CODECS="a.1,b.2",RESOLUTION=4x2')

    assert attributes == {'BANDWIDTH': '100', 'CODECS': 'a.1,b.2', 'RESOLUTION': '4x2'}


def test_separate_audio_rendition_is_attached_to_the_variant_that_uses_it() -> None:
    """Downloading such a variant's URL alone yields a silent file, so the
    rendition playlist has to travel with it."""
    (variant,) = parse_master_playlist(MASTER_WITH_AUDIO_GROUP, 'https://cdn.example/hls/master.m3u8')

    assert variant.audio_url == 'https://cdn.example/hls/audio/en.m3u8'


def test_variants_without_an_audio_group_have_no_separate_audio() -> None:
    for variant in parse_master_playlist(MASTER, 'https://cdn.example/hls/master.m3u8'):
        assert variant.audio_url is None


def test_subtitle_renditions_are_not_treated_as_audio() -> None:
    playlist = MASTER_WITH_AUDIO_GROUP.replace('TYPE=AUDIO', 'TYPE=SUBTITLES', 1)
    (variant,) = parse_master_playlist(playlist, 'https://cdn.example/hls/master.m3u8')

    assert variant.audio_url is None


def test_quality_label_prefers_height_then_name_then_bitrate() -> None:
    variants = parse_master_playlist(MASTER, 'https://cdn.example/hls/master.m3u8')
    assert quality_label(variants[0]) == '720p'

    unnamed = parse_master_playlist(
        '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=3200000\nonly.m3u8\n',
        'https://cdn.example/hls/master.m3u8',
    )
    assert quality_label(unnamed[0]) == '3.2 Mbps'

    anonymous = parse_master_playlist(
        '#EXTM3U\n#EXT-X-STREAM-INF:PROGRAM-ID=1\nonly.m3u8\n',
        'https://cdn.example/hls/master.m3u8',
    )
    assert quality_label(anonymous[0]) == 'Variant 1'


def test_malformed_attributes_do_not_raise() -> None:
    playlist = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=abc,RESOLUTION=wide,FRAME-RATE=\nonly.m3u8\n'
    (variant,) = parse_master_playlist(playlist, 'https://cdn.example/hls/master.m3u8')

    assert variant.bandwidth_bps is None
    assert (variant.width, variant.height) == (None, None)
    assert variant.frame_rate is None
    assert variant.url == 'https://cdn.example/hls/only.m3u8'


def test_stream_inf_without_a_following_uri_is_skipped() -> None:
    playlist = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n#EXT-X-ENDLIST\n'

    assert parse_master_playlist(playlist, 'https://cdn.example/hls/master.m3u8') == []


def test_estimated_size_needs_both_bitrate_and_duration() -> None:
    assert estimated_size_bytes(8_000_000, 10.0) == 10_000_000
    assert estimated_size_bytes(None, 10.0) is None
    assert estimated_size_bytes(8_000_000, None) is None
    assert estimated_size_bytes(8_000_000, 0) is None
