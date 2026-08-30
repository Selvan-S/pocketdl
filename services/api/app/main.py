from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .api.routes import router
from .core.config import get_settings
from .core.logging import configure_logging
from .application.downloads.service import QueueService
from .application.events import ChangeNotifier
from .application.captures.service import CaptureService
from .application.collections.service import CollectionService
from .application.instagram.discovery import ProfileDiscoveryService
from .infrastructure.captures import SqliteCaptureRepository
from .infrastructure.collections import SqliteCollectionRepository
from .infrastructure.ffmpeg import CapturedMediaService
from .infrastructure.gallery_dl import GalleryDlService
from .infrastructure.instaloader_service import InstaloaderService
from .infrastructure.manifest_fetch import ManifestFetcher
from .infrastructure.media_probe import MediaProbeService
from .infrastructure.presets import SqliteDownloadPresetRepository
from .infrastructure.sqlite import SqliteDownloadRepository
from .infrastructure.yt_dlp import YtDlpService

configure_logging()
settings = get_settings()
default_download_directory = settings.default_download_directory


@asynccontextmanager
async def lifespan(app: FastAPI):
    repository = SqliteDownloadRepository(settings.database_path)
    await repository.initialize()
    capture_repository = SqliteCaptureRepository(settings.database_path)
    await capture_repository.initialize()
    collection_repository = SqliteCollectionRepository(settings.database_path)
    await collection_repository.initialize()
    preset_repository = SqliteDownloadPresetRepository(settings.database_path)
    await preset_repository.initialize()
    media_probe = MediaProbeService()
    manifest_fetcher = ManifestFetcher()
    capture_service = CaptureService(capture_repository, media_probe, manifest_fetcher)
    captured_media = CapturedMediaService(settings.download_directory)
    # gallery-dl remains available as infrastructure (constructed, tested)
    # but is not wired into any live route -- Phase 5's design reserves it
    # as the generic engine for the next non-Instagram platform. Instagram
    # itself routes through instaloader_service instead, after two live
    # findings (see CLAUDE.md's "Important proven behavior") showed
    # gallery-dl's Instagram errors are ambiguous free text with no date
    # filtering, where instaloader gives typed exceptions and real dates.
    gallery_dl = GalleryDlService(settings, collection_repository)
    instaloader_service = InstaloaderService(settings, collection_repository)
    downloader = YtDlpService(settings, captured_media, gallery_dl, instaloader_service)
    change_notifier = ChangeNotifier()
    queue = QueueService(
        repository, downloader, settings.max_concurrent_downloads, capture_repository, collection_repository,
        on_change=change_notifier.notify,
    )
    profile_discovery_service = ProfileDiscoveryService(instaloader_service)
    collection_service = CollectionService(collection_repository, queue)
    app.state.change_notifier = change_notifier
    app.state.settings = settings
    app.state.default_download_directory = default_download_directory
    app.state.repository = repository
    app.state.capture_repository = capture_repository
    app.state.capture_service = capture_service
    app.state.captured_media = captured_media
    app.state.collection_repository = collection_repository
    app.state.preset_repository = preset_repository
    app.state.gallery_dl = gallery_dl
    app.state.instaloader_service = instaloader_service
    app.state.profile_discovery_service = profile_discovery_service
    app.state.collection_service = collection_service
    app.state.downloader = downloader
    app.state.queue = queue
    yield
    await queue.shutdown()


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://127.0.0.1:5173', 'http://localhost:5173'],
    allow_origin_regex=r'^chrome-extension://[a-p]{32}$',
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)
@app.middleware('http')
async def notify_on_mutation(request, call_next):
    """Wake the SSE stream after any request that could have changed state.

    Catching it here rather than at each mutating route means a new endpoint
    cannot forget to do it. Download *progress* is pushed separately by
    QueueService, since that changes state without any request at all.
    """
    response = await call_next(request)
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and response.status_code < 400:
        app.state.change_notifier.notify()
    return response


app.include_router(router)

WEB_DIST = Path(__file__).resolve().parents[3] / 'apps' / 'web' / 'dist'
if WEB_DIST.exists():
    app.mount('/assets', StaticFiles(directory=WEB_DIST / 'assets'), name='assets')

    @app.get('/', include_in_schema=False)
    async def web_root() -> FileResponse:
        return FileResponse(WEB_DIST / 'index.html')

    @app.get('/manifest.webmanifest', include_in_schema=False)
    async def web_manifest() -> FileResponse:
        return FileResponse(WEB_DIST / 'manifest.webmanifest')


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app.main:app', host=settings.host, port=settings.port, reload=False)
