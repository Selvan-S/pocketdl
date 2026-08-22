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
