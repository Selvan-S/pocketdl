from pathlib import Path

from app.core.settings_store import clear_download_directory, load_download_directory, save_download_directory

def test_settings_store_round_trip(tmp_path: Path) -> None:
    database = tmp_path / 'pocketdl.db'
    target = tmp_path / 'downloads'
    save_download_directory(database, target)
    assert load_download_directory(database) == target
    clear_download_directory(database)
    assert load_download_directory(database) is None
