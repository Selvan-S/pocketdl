import pytest
from datetime import datetime

from app.application.captures.service import CaptureService
from app.domain.captures import CaptureType


class InMemoryCaptureRepository:
    def __init__(self):
        self.items = {}

    async def add(self, capture):
        self.items[capture.id] = capture
        return capture

    async def get(self, capture_id):
        return self.items.get(capture_id)

    async def list(self, limit=50):
        return list(self.items.values())[:limit]

    async def find_by_source_key(self, source_key):
        return next((item for item in self.items.values() if item.source_key == source_key), None)

    async def update(self, capture):
        self.items[capture.id] = capture
        return capture

    async def mark_downloaded(self, capture_id):
        item = self.items.get(capture_id)
        if item:
            item.used_at = datetime.now()
        return item

    async def delete(self, capture_id):
        self.items.pop(capture_id, None)


@pytest.mark.asyncio
async def test_capture_filters_sensitive_headers_and_deduplicates() -> None:
    repo = InMemoryCaptureRepository()
    service = CaptureService(repo)
    first = await service.capture(
        media_url='https://cdn.example/video/master.m3u8?x=1',
        page_url='https://site.example/video',
        page_title='Example',
        referer='https://site.example/',
        origin='https://site.example',
        user_agent='Chrome',
        headers={'Origin': 'https://site.example', 'Cookie': 'secret', 'X-Test': 'ok'},
        capture_type=CaptureType.HLS,
        content_type='application/vnd.apple.mpegurl',
    )
    second = await service.capture(
        media_url='https://cdn.example/video/master.m3u8?token=2',
        page_url=first.page_url,
        page_title='Example',
        referer=first.referer,
        origin=first.origin,
        user_agent=first.user_agent,
        headers={'X-Test': 'ok'},
        capture_type=CaptureType.HLS,
        content_type=first.content_type,
    )
    assert first.id == second.id
    assert second.media_url.endswith('token=2')
    assert 'Cookie' not in first.headers
    assert first.headers['X-Test'] == 'ok'
