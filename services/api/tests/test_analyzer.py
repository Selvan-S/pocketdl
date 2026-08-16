from app.domain.analyzer import parse_media_analysis


def test_parse_media_analysis_sorts_formats_and_extracts_metadata() -> None:
    payload = {
        'title': 'Example video',
        'uploader': 'Example uploader',
        'duration': 125,
        'extractor_key': 'Generic',
        'is_live': False,
        'formats': [
            {'format_id': 'low', 'height': 360, 'ext': 'mp4', 'vcodec': 'avc1', 'acodec': 'none', 'protocol': 'https'},
            {'format_id': 'high', 'height': 1080, 'ext': 'mp4', 'vcodec': 'avc1', 'acodec': 'mp4a', 'filesize': 123456},
        ],
    }

    result = parse_media_analysis(payload, 'https://example.com/video')

    assert result.title == 'Example video'
    assert result.uploader == 'Example uploader'
    assert result.duration_seconds == 125
    assert result.formats[0].format_id == 'high'
    assert result.formats[1].format_id == 'low'
