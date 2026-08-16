import re
from pathlib import Path

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


def sanitize_filename(value: str) -> str:
    """Return a safe filename stem for local filesystem output."""
    cleaned = _INVALID_FILENAME_CHARS.sub('_', value).strip().rstrip('.')
    if not cleaned:
        raise ValueError('Filename cannot be empty.')

    stem = Path(cleaned).stem.strip().rstrip('.')
    if not stem:
        raise ValueError('Filename cannot be empty.')

    if stem.upper() in _RESERVED_NAMES:
        stem = f'_{stem}'

    return stem[:200]
