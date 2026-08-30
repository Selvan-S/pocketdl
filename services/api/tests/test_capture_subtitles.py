"""Subtitle support for captured HLS downloads (captures round)."""

from pathlib import Path

from app.domain.manifests import parse_subtitle_renditions, pick_subtitle_rendition
from app.infrastructure.ffmpeg import CapturedMediaService

MASTER = """#EXTM3U
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="en",DEFAULT=YES,URI="subs/en.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Spanish",LANGUAGE="es",DEFAULT=NO,URI="subs/es.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="A",DEFAULT=YES,URI="audio/a.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360,SUBTITLES="subs"
v0/index.m3u8
"""


def test_parse_subtitle_renditions_extracts_tracks() -> None:
    subs = parse_subtitle_renditions(MASTER, 'https://cdn.example/hls/master.m3u8')
    assert [(s.language, s.is_default) for s in subs] == [('en', True), ('es', False)]
    assert subs[0].url == 'https://cdn.example/hls/subs/en.m3u8'


def test_pick_prefers_requested_language_then_default() -> None:
    subs = parse_subtitle_renditions(MASTER, 'https://cdn.example/hls/master.m3u8')
    assert pick_subtitle_rendition(subs, 'es').language == 'es'
    assert pick_subtitle_rendition(subs, None).language == 'en'  # default
    assert pick_subtitle_rendition(subs, 'fr').language == 'en'  # falls back to default
    assert pick_subtitle_rendition([], 'en') is None


def test_ffmpeg_args_mux_subtitles_as_mov_text() -> None:
    args = CapturedMediaService._build_ffmpeg_args(
        'https://cdn.example/v0/index.m3u8', Path('/downloads/out.mp4'), '', None,
        subtitle_url='https://cdn.example/subs/en.m3u8',
    )
    # Subtitle is input 1 (no separate audio here).
    assert '-c:s' in args and args[args.index('-c:s') + 1] == 'mov_text'
    assert '-map' in args
    assert '1:s:0?' in args


def test_ffmpeg_args_subtitle_index_after_separate_audio() -> None:
    args = CapturedMediaService._build_ffmpeg_args(
        'https://cdn.example/v.m3u8', Path('/downloads/out.mp4'), '', None,
        audio_url='https://cdn.example/a.m3u8', subtitle_url='https://cdn.example/s.m3u8',
    )
    # video=0, audio=1, subtitle=2
    assert '1:a:0?' in args
    assert '2:s:0?' in args
