from pathlib import Path


def normalize_download_directory(raw_path: str) -> Path:
    value = raw_path.strip()
    if not value:
        raise ValueError('Download directory cannot be empty.')

    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('Download directory must be an absolute path.')

    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError('Download directory is not a directory.')
    return path
