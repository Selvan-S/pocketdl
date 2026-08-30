from pathlib import Path

from app.infrastructure.ffmpeg import CapturedMediaService


def test_captured_ffmpeg_args_allow_nonstandard_segment_extensions() -> None:
    """Some sites disguise HLS playlists/segments as .txt/.css to dodge naive
    ad-blockers. ffmpeg's hls demuxer rejects those extensions by default
    (exit 183, "not in allowed_segment_extensions") unless told otherwise."""
    args = CapturedMediaService._build_ffmpeg_args(
        'https://cdn.example/hls/index_avc_640p.txt',
        Path('/downloads/video.mp4'),
        '',
        None,
    )
    assert '-allowed_extensions' in args
    assert args[args.index('-allowed_extensions') + 1] == 'ALL'
    # must appear before -i (an ffmpeg input/demuxer option, not output)
    assert args.index('-allowed_extensions') < args.index('-i')


def test_captured_ffmpeg_args_include_headers_and_user_agent() -> None:
    args = CapturedMediaService._build_ffmpeg_args(
        'https://cdn.example/video.mp4',
        Path('/downloads/video.mp4'),
        'Referer: https://site.example/\r\n',
        'Mozilla/5.0',
    )
    assert '-headers' in args
    assert '-user_agent' in args
    assert args[args.index('-user_agent') + 1] == 'Mozilla/5.0'


def test_captured_ffmpeg_args_mux_a_separate_audio_rendition() -> None:
    """When the master lists audio as its own #EXT-X-MEDIA rendition, the
    chosen quality's playlist carries video only -- downloading it alone would
    produce a silent file."""
    args = CapturedMediaService._build_ffmpeg_args(
        'https://cdn.example/hls/1080p/index.m3u8',
        Path('/downloads/video.mp4'),
        'Referer: https://site.example/\r\n',
        'Mozilla/5.0',
        'https://cdn.example/hls/audio/en.m3u8',
    )

    inputs = [args[index + 1] for index, value in enumerate(args) if value == '-i']
    assert inputs == ['https://cdn.example/hls/1080p/index.m3u8', 'https://cdn.example/hls/audio/en.m3u8']
    assert args[args.index('-map') + 1] == '0:v:0?'
    assert '1:a:0?' in args
    # ffmpeg applies input options to the -i that follows, so the second input
    # needs its own copy rather than inheriting the first one's.
    assert args.count('-headers') == 2
    assert args.count('-user_agent') == 2
    assert args.count('-allowed_extensions') == 2


def test_captured_ffmpeg_args_take_audio_from_the_single_input_when_muxed() -> None:
    args = CapturedMediaService._build_ffmpeg_args(
        'https://cdn.example/hls/1080p/index.m3u8',
        Path('/downloads/video.mp4'),
        '',
        None,
    )

    assert args.count('-i') == 1
    assert '0:a:0?' in args
    assert '1:a:0?' not in args


# --- Brotli fix: force identity, drop the browser's accept-encoding ---

def test_headers_block_forces_identity_encoding() -> None:
    """The captured browser Accept-Encoding (gzip, deflate, br) makes servers
    return brotli, which ffmpeg's HTTP client can't decode ("Unknown content
    coding: br"). We drop it and ask for identity instead."""
    from app.domain.models import RequestContext

    block = CapturedMediaService._headers_block(
        RequestContext(headers={'Accept-Encoding': 'gzip, deflate, br, zstd', 'X-Keep': 'yes'})
    )

    assert 'Accept-Encoding: identity\r\n' in block
    assert 'br' not in block
    assert 'zstd' not in block
    # Non-encoding headers are still forwarded.
    assert 'X-Keep: yes\r\n' in block


def test_headers_block_adds_identity_even_without_a_captured_one() -> None:
    from app.domain.models import RequestContext

    block = CapturedMediaService._headers_block(RequestContext(referer='https://site.example/'))

    assert 'Accept-Encoding: identity\r\n' in block
    assert 'Referer: https://site.example/\r\n' in block
