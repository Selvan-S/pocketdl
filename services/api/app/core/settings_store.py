import json
from pathlib import Path
from typing import Any

SETTINGS_FILENAME = 'settings.json'


def settings_file(database_path: Path) -> Path:
    return database_path.parent / SETTINGS_FILENAME


def _read(database_path: Path) -> dict[str, Any]:
    path = settings_file(database_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(database_path: Path, data: dict[str, Any]) -> None:
    path = settings_file(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def save_setting(database_path: Path, key: str, value: Any) -> None:
    """Merge one key into the persisted settings, leaving the others intact."""
    data = _read(database_path)
    data[key] = value
    _write(database_path, data)


def load_setting(database_path: Path, key: str, default: Any = None) -> Any:
    return _read(database_path).get(key, default)


def clear_setting(database_path: Path, key: str) -> None:
    data = _read(database_path)
    if key in data:
        del data[key]
        _write(database_path, data)


# --- download_directory (kept as named helpers for existing callers) ---------

def load_download_directory(database_path: Path) -> Path | None:
    raw = load_setting(database_path, 'download_directory')
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser()


def save_download_directory(database_path: Path, directory: Path) -> None:
    save_setting(database_path, 'download_directory', str(directory))


def clear_download_directory(database_path: Path) -> None:
    clear_setting(database_path, 'download_directory')
