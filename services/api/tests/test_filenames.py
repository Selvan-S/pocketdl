import pytest

from app.core.filenames import sanitize_filename


def test_sanitize_filename_removes_invalid_characters() -> None:
    assert sanitize_filename('my/video:01?.mp4') == 'my_video_01_'


def test_sanitize_filename_rejects_empty_result() -> None:
    with pytest.raises(ValueError):
        sanitize_filename('   ')


def test_sanitize_filename_avoids_windows_reserved_names() -> None:
    assert sanitize_filename('CON') == '_CON'
