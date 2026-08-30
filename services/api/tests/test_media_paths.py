from pathlib import Path

from app.core.media_paths import platform_media_path


def test_platform_media_path_builds_nested_directory_and_creates_it(tmp_path: Path) -> None:
    result = platform_media_path(tmp_path, 'Instagram', 'someuser', 'Reels', filename='clip.mp4')

    assert result == tmp_path / 'Instagram' / 'someuser' / 'Reels' / 'clip.mp4'
    assert result.parent.is_dir()


def test_platform_media_path_with_no_subfolders(tmp_path: Path) -> None:
    result = platform_media_path(tmp_path, 'Standard', filename='video.mp4')

    assert result == tmp_path / 'Standard' / 'video.mp4'
    assert result.parent.is_dir()
