"""Storage / disk-usage scan of the download directory (product-polish
Round 2). A per-folder breakdown so full-profile downloads that fill a phone
are visible."""

import pytest

from app.infrastructure.storage import scan_storage


def _write(path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)


def test_scan_sums_per_top_level_folder_sorted_desc(tmp_path) -> None:
    _write(tmp_path / 'big' / 'a.mp4', 300)
    _write(tmp_path / 'big' / 'nested' / 'b.mp4', 100)
    _write(tmp_path / 'small' / 'c.mp4', 50)

    usage = scan_storage(tmp_path)

    assert usage.total_bytes == 450
    assert [(f.name, f.bytes, f.file_count) for f in usage.folders] == [
        ('big', 400, 2),
        ('small', 50, 1),
    ]
    assert usage.disk_total_bytes > 0


def test_loose_files_are_bucketed(tmp_path) -> None:
    _write(tmp_path / 'loose.mp4', 25)
    _write(tmp_path / 'folder' / 'x.mp4', 10)

    usage = scan_storage(tmp_path)

    names = {f.name for f in usage.folders}
    assert '(loose files)' in names
    loose = next(f for f in usage.folders if f.name == '(loose files)')
    assert loose.bytes == 25
    assert loose.file_count == 1


def test_missing_directory_is_reported_empty_with_disk_figures(tmp_path) -> None:
    usage = scan_storage(tmp_path / 'does-not-exist-yet')

    assert usage.total_bytes == 0
    assert usage.folders == []
    # Free/total come from the nearest existing ancestor, so they're real.
    assert usage.disk_total_bytes > 0


@pytest.mark.asyncio
async def test_storage_endpoint(api_client) -> None:
    response = await api_client.get('/api/storage')
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['total_bytes'] == 0
    assert body['folders'] == []
    assert body['disk_total_bytes'] > 0
    assert body['directory']
