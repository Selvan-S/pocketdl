import json
from pathlib import Path

SETTINGS_FILENAME = 'settings.json'


def settings_file(database_path: Path) -> Path:
    return database_path.parent / SETTINGS_FILENAME


def load_download_directory(database_path: Path) -> Path | None:
    path = settings_file(database_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    raw = payload.get('download_directory') if isinstance(payload, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser()


def save_download_directory(database_path: Path, directory: Path) -> None:
    path = settings_file(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'download_directory': str(directory)}, indent=2), encoding='utf-8')


def clear_download_directory(database_path: Path) -> None:
    path = settings_file(database_path)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
