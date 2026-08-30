"""Cancel/pause must stop a captured download's ffmpeg process, which lives
in CapturedMediaService, not YtDlpService._processes. Without delegation a
paused capture kept running and its progress rewrote the status to RUNNING
(looked like it auto-resumed)."""

import pytest

from app.core.config import get_settings
from app.infrastructure.ffmpeg import CapturedMediaService
from app.infrastructure.gallery_dl import GalleryDlService
from app.infrastructure.instaloader_service import InstaloaderService
from app.infrastructure.yt_dlp import YtDlpService


@pytest.mark.asyncio
async def test_cancel_delegates_to_captured_media() -> None:
    settings = get_settings()
    captured = CapturedMediaService(settings.download_directory)
    service = YtDlpService(settings, captured, GalleryDlService(settings, None), InstaloaderService(settings, None))

    called: list[str] = []

    async def fake_cancel(job_id: str) -> None:
        called.append(job_id)

    captured.cancel = fake_cancel  # type: ignore[assignment]

    await service.cancel('job-1')

    assert called == ['job-1']
