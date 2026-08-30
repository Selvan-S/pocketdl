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


def unique_stem(directory: Path, stem: str) -> str:
    """A filename stem that doesn't collide with an existing file of any
    extension in `directory`. Returns `stem` unchanged if nothing matches,
    else appends " (1)", " (2)", ... -- the "rename" conflict strategy.

    Matches on the stem across extensions (``stem.*``) because the real
    output extension isn't known until the download resolves it.
    """
    if not any(directory.glob(f'{glob_escape(stem)}.*')):
        return stem
    index = 1
    while any(directory.glob(f'{glob_escape(f"{stem} ({index})")}.*')):
        index += 1
    return f'{stem} ({index})'


def glob_escape(value: str) -> str:
    """Escape glob metacharacters so a stem containing [, ], *, or ? is
    matched literally by Path.glob."""
    return re.sub(r'([\[\]*?])', r'[\1]', value)
