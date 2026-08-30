import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class FolderUsage:
    name: str
    bytes: int
    file_count: int


@dataclass(slots=True)
class StorageUsage:
    """Disk usage of the download directory: how much its contents occupy,
    broken down by top-level folder (one per platform/profile in practice),
    plus the filesystem's free/total so the UI can show headroom."""

    directory: str
    total_bytes: int
    free_bytes: int
    disk_total_bytes: int
    folders: list[FolderUsage] = field(default_factory=list)


# Files sitting directly in the download directory (not under any subfolder)
# are grouped under this synthetic bucket so they still count and show up.
_LOOSE_FILES_LABEL = '(loose files)'


def _tree_size(path: Path) -> tuple[int, int]:
    """(bytes, file_count) under `path`, skipping anything unreadable rather
    than failing the whole scan on one permission error or broken symlink."""
    total = 0
    count = 0
    for child in path.rglob('*'):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
                count += 1
        except OSError:
            continue
    return total, count


def scan_storage(directory: Path) -> StorageUsage:
    """Synchronous; call via asyncio.to_thread — a large tree can take a while.

    A missing directory is reported as empty (0 bytes) rather than an error:
    a fresh install simply hasn't downloaded anything yet. Disk free/total is
    read from the nearest existing ancestor so the figure is still meaningful.
    """
    disk_anchor = directory
    while not disk_anchor.exists() and disk_anchor != disk_anchor.parent:
        disk_anchor = disk_anchor.parent
    try:
        usage = shutil.disk_usage(disk_anchor)
        free_bytes, disk_total_bytes = usage.free, usage.total
    except OSError:
        free_bytes, disk_total_bytes = 0, 0

    folders: list[FolderUsage] = []
    total_bytes = 0
    loose_bytes = 0
    loose_count = 0

    if directory.exists():
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            entries = []
        for entry in entries:
            try:
                if entry.is_dir() and not entry.is_symlink():
                    size, count = _tree_size(entry)
                    folders.append(FolderUsage(name=entry.name, bytes=size, file_count=count))
                    total_bytes += size
                elif entry.is_file() and not entry.is_symlink():
                    loose_bytes += entry.stat().st_size
                    loose_count += 1
            except OSError:
                continue

    if loose_count:
        folders.append(FolderUsage(name=_LOOSE_FILES_LABEL, bytes=loose_bytes, file_count=loose_count))
        total_bytes += loose_bytes

    folders.sort(key=lambda folder: folder.bytes, reverse=True)
    return StorageUsage(
        directory=str(directory),
        total_bytes=total_bytes,
        free_bytes=free_bytes,
        disk_total_bytes=disk_total_bytes,
        folders=folders,
    )
