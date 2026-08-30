import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnalyzedFormatResponse,
    BrowseDirectoryResponse,
    CaptureCreateRequest,
    CaptureDownloadRequest,
    CaptureResponse,
    CaptureVariantResponse,
    CollectionAddProfileItemsRequest,
    CollectionAddProfileItemsResponse,
    CollectionCreateRequest,
    CollectionDownloadRequest,
    CollectionItemAddRequest,
    CollectionItemResponse,
    CollectionRenameRequest,
    CollectionResponse,
    DownloadCreateRequest,
    DownloadHistoryResponse,
    DownloadPresetCreateRequest,
    DownloadPresetResponse,
    DownloadResponse,
    CollectionExport,
    CollectionItemExport,
    ExportBundle,
    FolderUsageResponse,
    ImportResultResponse,
    InstagramProfilePreviewRequest,
    PresetExport,
    SettingsExport,
    InstagramProfilePreviewResponse,
    InstagramSessionRequest,
    InstagramSessionStatusResponse,
    ProfileItemPreviewResponse,
    StorageUsageResponse,
    SystemStatusResponse,
    UpdateCheckResponse,
    SettingsResponse,
    SettingsUpdateRequest,
)
from ..application.captures.service import CaptureService
from ..application.collections.service import CollectionService
from ..core.path_settings import normalize_download_directory
from ..core.platform import DirectoryPickerUnavailable, browse_for_directory, open_directory
from ..core.session_store import clear_session_cookie, has_session_cookie, save_session_cookie
from ..infrastructure.storage import scan_storage
from ..infrastructure.updates import check_yt_dlp_update
from ..core.settings_store import clear_download_directory, save_download_directory, save_setting
from ..domain.captures import CaptureType, CaptureVariant, is_suspicious_capture
from ..domain.collections import Collection, CollectionItem, InstagramAuthRequiredError, InstagramContentType, Platform, ProfileItemPreview
from ..domain.manifests import VariantStream, estimated_size_bytes, quality_label
from ..domain.models import ConflictStrategy, DownloadSourceType, DownloadStatus, ImpersonationMode, MediaOptions, RequestContext
from ..domain.presets import DownloadPreset

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api')


def _context(payload) -> RequestContext:
    return RequestContext(
        page_url=str(payload.page_url) if payload.page_url else None,
        referer=str(payload.referer) if payload.referer else None,
        origin=str(payload.origin) if payload.origin else None,
        user_agent=payload.user_agent,
        headers=payload.headers,
        impersonation=ImpersonationMode(payload.impersonation) if hasattr(payload, 'impersonation') else ImpersonationMode.NONE,
    )


def to_response(job) -> DownloadResponse:
    return DownloadResponse(
        id=job.id,
        url=job.url,
        filename=job.filename,
        title=job.title,
        status=job.status.value,
        source_type=job.source_type,
        progress=job.progress,
        downloaded_bytes=job.downloaded_bytes,
        total_bytes=job.total_bytes,
        speed_bytes=job.speed_bytes,
        eta_seconds=job.eta_seconds,
        output_path=job.output_path,
        error=job.error,
        error_details=job.error_details,
        error_category=job.error_category,
        exit_code=job.exit_code,
        retry_count=job.retry_count,
        impersonation=job.impersonation,
        referer=job.referer,
        origin=job.origin,
        user_agent=job.user_agent,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        capture_id=job.capture_id,
    )


def variant_response(variant: CaptureVariant, duration_seconds: float | None) -> CaptureVariantResponse:
    stream = VariantStream(
        index=variant.position,
        url=variant.url,
        bandwidth_bps=variant.bandwidth_bps,
        width=variant.width,
        height=variant.height,
        codecs=variant.codecs,
        frame_rate=variant.frame_rate,
        name=variant.name,
        audio_url=variant.audio_url,
    )
    return CaptureVariantResponse(
        index=variant.position,
        url=variant.url,
        quality_label=quality_label(stream),
        bandwidth_bps=variant.bandwidth_bps,
        width=variant.width,
        height=variant.height,
        codecs=variant.codecs,
        frame_rate=variant.frame_rate,
        name=variant.name,
        has_separate_audio=variant.audio_url is not None,
        estimated_size_bytes=estimated_size_bytes(variant.bandwidth_bps, duration_seconds),
    )


def capture_response(capture, variants: list[CaptureVariant] | None = None) -> CaptureResponse:
    return CaptureResponse(
        id=capture.id,
        media_url=capture.media_url,
        page_url=capture.page_url,
        page_title=capture.page_title,
        referer=capture.referer,
        origin=capture.origin,
        user_agent=capture.user_agent,
        headers=capture.headers,
        capture_type=capture.capture_type,
        content_type=capture.content_type,
        size_bytes=capture.size_bytes,
        duration_seconds=capture.duration_seconds,
        width=capture.width,
        height=capture.height,
        metadata_status=capture.metadata_status.value,
        metadata_error=capture.metadata_error,
        looks_suspicious=is_suspicious_capture(capture),
        status=capture.status,
        created_at=capture.created_at,
        used_at=capture.used_at,
        variants_status=capture.variants_status,
        variants=[variant_response(variant, capture.duration_seconds) for variant in variants or []],
    )


def collection_response(collection: Collection, item_count: int, downloaded_count: int = 0) -> CollectionResponse:
    return CollectionResponse(
        id=collection.id,
        platform=collection.platform.value,
        name=collection.name,
        item_count=item_count,
        downloaded_count=downloaded_count,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


def collection_item_response(item: CollectionItem) -> CollectionItemResponse:
    return CollectionItemResponse(
        id=item.id,
        collection_id=item.collection_id,
        source_url=item.source_url,
        content_type=item.content_type,
        author_username=item.author_username,
        profile_username=item.profile_username,
        caption=item.caption,
        thumbnail_url=item.thumbnail_url,
        external_id=item.external_id,
        added_at=item.added_at,
        posted_at=item.posted_at,
        downloaded_job_id=item.downloaded_job_id,
    )


@router.post('/analyze', response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    context = _context(payload.request_context)
    try:
        result = await request.app.state.downloader.analyze(str(payload.url), request_context=context)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AnalyzeResponse(
        source_url=result.source_url,
        webpage_url=result.webpage_url,
        title=result.title,
        uploader=result.uploader,
        duration_seconds=result.duration_seconds,
        thumbnail=result.thumbnail,
        extractor=result.extractor,
        is_live=result.is_live,
        formats=[
            AnalyzedFormatResponse(
                format_id=item.format_id, ext=item.ext, width=item.width, height=item.height,
                fps=item.fps, vcodec=item.vcodec, acodec=item.acodec, filesize=item.filesize,
                tbr=item.tbr, protocol=item.protocol,
            ) for item in result.formats
        ],
    )


@router.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok'}


@router.get('/downloads', response_model=list[DownloadResponse])
async def list_downloads(request: Request) -> list[DownloadResponse]:
    jobs = await request.app.state.repository.list()
    return [to_response(job) for job in jobs]


# How many finished downloads the live snapshot carries alongside the active
# ones. Older history is paged in on demand via /downloads/history, so the SSE
# payload stays bounded no matter how long the queue's history grows.
_SNAPSHOT_TERMINAL_LIMIT = 40
# Page size cap for history requests.
_HISTORY_MAX_LIMIT = 100


@router.get('/downloads/history', response_model=DownloadHistoryResponse)
async def download_history(
    request: Request,
    limit: int = Query(default=40, ge=1, le=_HISTORY_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> DownloadHistoryResponse:
    """A page of finished downloads (history), newest-first. The live view
    already holds the active + most recent jobs from the SSE snapshot; this
    is how the UI reaches older ones without shipping them all on every
    snapshot."""
    # Fetch one extra to tell whether there's another page, without a count.
    jobs = await request.app.state.repository.list_terminal_page(limit + 1, offset)
    has_more = len(jobs) > limit
    return DownloadHistoryResponse(
        items=[to_response(job) for job in jobs[:limit]],
        has_more=has_more,
    )


@router.post('/downloads', response_model=DownloadResponse, status_code=status.HTTP_201_CREATED)
async def create_download(payload: DownloadCreateRequest, request: Request) -> DownloadResponse:
    queue = request.app.state.queue
    context = _context(payload.request_context)
    media_options = MediaOptions(
        subtitles=payload.subtitles,
        subtitle_langs=payload.subtitle_langs,
        embed_subtitles=payload.embed_subtitles,
        audio_language=payload.audio_language,
        conflict_strategy=ConflictStrategy(payload.conflict_strategy),
    )
    try:
        job = await queue.create(
            str(payload.url),
            payload.filename,
            payload.preset,
            payload.concurrent_fragments,
            payload.retries,
            payload.use_aria2,
            context,
            format_id=payload.format_id,
            media_options=media_options,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return to_response(job)


@router.post('/downloads/{job_id}/cancel', response_model=DownloadResponse)
async def cancel_download(job_id: str, request: Request) -> DownloadResponse:
    job = await request.app.state.queue.cancel(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Download not found')
    return to_response(job)


@router.post('/downloads/{job_id}/retry', response_model=DownloadResponse)
async def retry_download(job_id: str, request: Request) -> DownloadResponse:
    try:
        job = await request.app.state.queue.retry(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail='Download not found')
    return to_response(job)


@router.post('/downloads/{job_id}/pause', response_model=DownloadResponse)
async def pause_download(job_id: str, request: Request) -> DownloadResponse:
    job = await request.app.state.queue.pause(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Download not found')
    return to_response(job)


@router.post('/downloads/{job_id}/resume', response_model=DownloadResponse)
async def resume_download(job_id: str, request: Request) -> DownloadResponse:
    try:
        job = await request.app.state.queue.resume(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail='Download not found')
    return to_response(job)


@router.post('/downloads/clear-completed')
async def clear_completed_downloads(request: Request) -> dict[str, int]:
    """Remove every COMPLETED download at once. Deliberately leaves failed and
    cancelled ones -- those may still be retried."""
    repository = request.app.state.repository
    queue = request.app.state.queue
    removed = 0
    for job in await repository.list():
        if job.status is DownloadStatus.COMPLETED:
            await repository.delete(job.id)
            queue.forget(job.id)
            removed += 1
    return {'removed': removed}


@router.delete('/downloads/{job_id}')
async def delete_download(job_id: str, request: Request) -> dict[str, bool]:
    job = await request.app.state.repository.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Download not found')
    if job.status in {DownloadStatus.QUEUED, DownloadStatus.RUNNING}:
        raise HTTPException(status_code=409, detail='Cancel the download before removing it')
    await request.app.state.repository.delete(job_id)
    request.app.state.queue.forget(job_id)
    return {'ok': True}


def preset_response(preset: DownloadPreset) -> DownloadPresetResponse:
    return DownloadPresetResponse(
        id=preset.id,
        name=preset.name,
        preset=preset.preset,
        concurrent_fragments=preset.concurrent_fragments,
        retries=preset.retries,
        use_aria2=preset.use_aria2,
        created_at=preset.created_at,
    )


@router.get('/presets', response_model=list[DownloadPresetResponse])
async def list_presets(request: Request) -> list[DownloadPresetResponse]:
    presets = await request.app.state.preset_repository.list()
    return [preset_response(preset) for preset in presets]


@router.post('/presets', response_model=DownloadPresetResponse, status_code=status.HTTP_201_CREATED)
async def create_preset(payload: DownloadPresetCreateRequest, request: Request) -> DownloadPresetResponse:
    preset = DownloadPreset(
        id=uuid.uuid4().hex,
        name=payload.name.strip()[:100],
        preset=payload.preset,
        concurrent_fragments=payload.concurrent_fragments,
        retries=payload.retries,
        use_aria2=payload.use_aria2,
        created_at=datetime.now(timezone.utc),
    )
    await request.app.state.preset_repository.add(preset)
    return preset_response(preset)


@router.delete('/presets/{preset_id}')
async def delete_preset(preset_id: str, request: Request) -> dict[str, bool]:
    if await request.app.state.preset_repository.get(preset_id) is None:
        raise HTTPException(status_code=404, detail='Preset not found')
    await request.app.state.preset_repository.delete(preset_id)
    return {'ok': True}


@router.get('/captures', response_model=list[CaptureResponse])
async def list_captures(request: Request) -> list[CaptureResponse]:
    capture_repository = request.app.state.capture_repository
    captures = await capture_repository.list()
    variants = await capture_repository.variants_for([item.id for item in captures])
    return [capture_response(item, variants.get(item.id, [])) for item in captures]


@router.post('/captures', response_model=CaptureResponse, status_code=status.HTTP_201_CREATED)
async def create_capture(
    payload: CaptureCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    x_pocketdl_extension: str | None = Header(default=None),
) -> CaptureResponse:
    if x_pocketdl_extension != '0.2':
        raise HTTPException(status_code=403, detail='Capture requests must originate from the PocketDL extension.')
    service: CaptureService = request.app.state.capture_service
    try:
        capture = await service.capture(
            media_url=payload.media_url,
            page_url=payload.page_url,
            page_title=payload.page_title,
            referer=payload.referer,
            origin=payload.origin,
            user_agent=payload.user_agent,
            headers=payload.headers,
            capture_type=CaptureType(payload.capture_type),
            content_type=payload.content_type,
            content_length_bytes=payload.content_length_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Background tasks run in order, and reading the playlist is a single small
    # HTTP request where the ffprobe enrichment can take tens of seconds -- so
    # the quality list reaches the UI first rather than queueing behind it.
    background_tasks.add_task(service.resolve_variants, capture.id)
    background_tasks.add_task(service.enrich_metadata, capture.id)
    variants = await request.app.state.capture_repository.list_variants(capture.id)
    return capture_response(capture, variants)


@router.post('/captures/{capture_id}/download', response_model=DownloadResponse, status_code=status.HTTP_201_CREATED)
async def download_capture(capture_id: str, request: Request, payload: CaptureDownloadRequest | None = None) -> DownloadResponse:
    capture_repository = request.app.state.capture_repository
    capture = await capture_repository.get(capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail='Capture not found')

    options = payload or CaptureDownloadRequest()
    # A chosen quality downloads that variant's own sub-playlist. When the
    # master lists audio as a separate rendition the variant carries video
    # only, so its audio playlist is muxed in as a second ffmpeg input.
    media_url = capture.media_url
    audio_url: str | None = None
    if options.variant_index is not None:
        variants = await capture_repository.list_variants(capture_id)
        selected = next((variant for variant in variants if variant.position == options.variant_index), None)
        if selected is None:
            raise HTTPException(status_code=422, detail='Unknown quality for this capture.')
        media_url = selected.url
        audio_url = selected.audio_url

    # Subtitles (opt-in) come from a separate #EXT-X-MEDIA:TYPE=SUBTITLES
    # rendition on the HLS master; resolved on demand. A miss (no subtitles,
    # not HLS) simply leaves the download without them.
    subtitle_url: str | None = None
    if options.subtitles:
        subtitle_url = await request.app.state.capture_service.resolve_subtitle_url(capture, options.subtitle_language)

    context = RequestContext(
        page_url=capture.page_url,
        referer=capture.referer,
        origin=capture.origin,
        user_agent=capture.user_agent,
        headers=capture.headers,
        impersonation=ImpersonationMode.NONE,
    )
    job = await request.app.state.queue.create(
        media_url,
        options.filename,
        options.preset,
        options.concurrent_fragments,
        options.retries,
        False,
        context,
        source_type=DownloadSourceType.CAPTURED,
        capture_id=capture.id,
        title=capture.page_title,
        audio_url=audio_url,
        subtitle_url=subtitle_url,
        # Only embed vs sidecar matters to the ffmpeg path; the rest of
        # MediaOptions is for standard downloads.
        media_options=MediaOptions(embed_subtitles=options.embed_subtitles),
    )
    return to_response(job)


@router.delete('/captures/{capture_id}')
async def delete_capture(capture_id: str, request: Request) -> dict[str, bool]:
    capture = await request.app.state.capture_repository.get(capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail='Capture not found')
    await request.app.state.capture_repository.delete(capture_id)
    return {'ok': True}


# How long an idle stream waits before rebuilding its snapshot anyway. The
# notifier wakes it immediately on any real change, so this is purely a
# safety net for a mutation nobody instrumented -- and it doubles as the
# keepalive that stops an idle connection being dropped by a proxy.
_EVENT_HEARTBEAT_SECONDS = 15.0
# Floor between two pushes. A running download updates progress many times a
# second; without this the stream would be chattier than the 2s poll it
# replaced.
_EVENT_MIN_INTERVAL_SECONDS = 0.4


async def _snapshot_downloads(request: Request) -> list[DownloadResponse]:
    """The bounded download list for the SSE snapshot: all active jobs plus
    the most recent finished ones. Keeps the pushed payload from growing with
    history -- older jobs are reached via /downloads/history."""
    jobs = await request.app.state.repository.list_recent(_SNAPSHOT_TERMINAL_LIMIT)
    return [to_response(job) for job in jobs]


async def _event_snapshot(request: Request) -> dict:
    """Everything the PWA's old refresh loop fetched, in one payload.

    Deliberately calls the same handlers the individual endpoints do rather
    than re-querying, so the two can never disagree.
    """
    downloads, system, captures, settings_payload, collections = await asyncio.gather(
        _snapshot_downloads(request),
        system_status(request),
        list_captures(request),
        get_settings_route(request),
        list_collections(request),
        return_exceptions=True,
    )

    def ok(value):
        return None if isinstance(value, BaseException) else value

    # Collections carry *summaries only* (id, name, counts) -- never their
    # items. A 128-item playlist in every snapshot, rebuilt on each progress
    # tick, is exactly the cost this avoids; the counts are enough to drive a
    # live badge and let an open playlist decide when to re-fetch its page.
    return {
        'downloads': [item.model_dump(mode='json') for item in (ok(downloads) or [])],
        'status': (payload.model_dump(mode='json') if (payload := ok(system)) else None),
        'captures': [item.model_dump(mode='json') for item in (ok(captures) or [])],
        'settings': (payload.model_dump(mode='json') if (payload := ok(settings_payload)) else None),
        'collections': [item.model_dump(mode='json') for item in (ok(collections) or [])],
    }


@router.get('/events')
async def events(request: Request) -> StreamingResponse:
    """Server-sent stream replacing the PWA's 2s poll of four endpoints.

    SSE rather than a WebSocket: the traffic is entirely server-to-client,
    it is plain HTTP so it survives the Termux/reverse-proxy setup without
    an upgrade path, browsers reconnect on their own, and it needs no extra
    dependency.

    The stream only emits when the snapshot actually differs from the one
    already sent, so an idle app receives nothing but comment-only
    keepalives and never re-renders.
    """
    notifier = request.app.state.change_notifier

    async def stream():
        last_payload: str | None = None
        # Tell the browser how long to wait before reconnecting if the
        # connection drops (default is 3s, which is unnecessarily eager).
        yield 'retry: 5000\n\n'
        while True:
            # Read the version *before* building, so a change landing while
            # this snapshot is being built or throttled is still waiting for
            # us at the bottom of the loop rather than lost.
            seen = notifier.version
            payload = json.dumps(await _event_snapshot(request), default=str)
            if payload != last_payload:
                last_payload = payload
                yield f'event: state\ndata: {payload}\n\n'
            else:
                # A comment line: keeps the connection (and any proxy in
                # front of it) alive without waking the client's handler.
                yield ': keepalive\n\n'
            await asyncio.sleep(_EVENT_MIN_INTERVAL_SECONDS)
            await notifier.wait(since=seen, timeout=_EVENT_HEARTBEAT_SECONDS)

    return StreamingResponse(
        stream(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache, no-transform',
            # nginx and friends buffer streamed responses by default, which
            # would hold every event until the buffer filled.
            'X-Accel-Buffering': 'no',
        },
    )


def _settings_response(request: Request) -> SettingsResponse:
    settings = request.app.state.settings
    return SettingsResponse(
        download_directory=str(settings.download_directory),
        default_download_directory=str(request.app.state.default_download_directory),
        filename_template=settings.filename_template,
        clean_titles=settings.clean_titles,
    )


@router.get('/settings', response_model=SettingsResponse)
async def get_settings_route(request: Request) -> SettingsResponse:
    return _settings_response(request)


@router.put('/settings', response_model=SettingsResponse)
async def update_settings(payload: SettingsUpdateRequest, request: Request) -> SettingsResponse:
    try:
        directory = normalize_download_directory(payload.download_directory)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    settings = request.app.state.settings
    settings.download_directory = directory
    request.app.state.captured_media.download_directory = directory
    save_download_directory(settings.database_path, directory)

    # Output-naming preferences are optional in the same request; apply and
    # persist only what was provided.
    if payload.filename_template is not None:
        settings.filename_template = payload.filename_template
        save_setting(settings.database_path, 'filename_template', payload.filename_template)
    if payload.clean_titles is not None:
        settings.clean_titles = payload.clean_titles
        save_setting(settings.database_path, 'clean_titles', payload.clean_titles)

    return _settings_response(request)


@router.post('/settings/reset-download-directory', response_model=SettingsResponse)
async def reset_download_directory(request: Request) -> SettingsResponse:
    settings = request.app.state.settings
    directory = request.app.state.default_download_directory
    directory.mkdir(parents=True, exist_ok=True)
    request.app.state.settings.download_directory = directory
    request.app.state.captured_media.download_directory = directory
    clear_download_directory(settings.database_path)
    return _settings_response(request)


@router.post('/settings/open-download-directory')
async def open_download_directory(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    try:
        open_directory(settings.download_directory)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f'Unable to open download directory: {exc}') from exc
    return {'ok': True, 'download_directory': str(settings.download_directory)}


@router.post('/settings/browse-download-directory', response_model=BrowseDirectoryResponse)
async def browse_download_directory(request: Request) -> BrowseDirectoryResponse:
    """Desktop-only: opens a native OS folder picker on the machine running
    the backend and returns the chosen path without saving it -- the caller
    still confirms via the existing PUT /settings, same as if they had
    typed the path themselves."""
    settings = request.app.state.settings
    try:
        chosen = await asyncio.to_thread(browse_for_directory, settings.download_directory)
    except DirectoryPickerUnavailable as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return BrowseDirectoryResponse(path=chosen)


@router.get('/storage', response_model=StorageUsageResponse)
async def storage_usage(request: Request) -> StorageUsageResponse:
    """Disk usage of the download directory, broken down by top-level folder.

    Scanning a large tree is slow, so it runs in a worker thread and is not
    part of the SSE snapshot or any polled path -- the UI fetches it on
    demand.
    """
    directory = request.app.state.settings.download_directory
    usage = await asyncio.to_thread(scan_storage, directory)
    return StorageUsageResponse(
        directory=usage.directory,
        total_bytes=usage.total_bytes,
        free_bytes=usage.free_bytes,
        disk_total_bytes=usage.disk_total_bytes,
        folders=[FolderUsageResponse(name=f.name, bytes=f.bytes, file_count=f.file_count) for f in usage.folders],
    )


# The bundle format version. Bump only on a breaking shape change; import
# tolerates unknown fields, so additive changes don't need it.
_EXPORT_VERSION = 1


@router.get('/export', response_model=ExportBundle)
async def export_data(request: Request) -> ExportBundle:
    """A single JSON backup of settings, saved presets, and playlists (with
    their items) -- cheap insurance before a phone reset or reinstall."""
    settings = request.app.state.settings
    presets = await request.app.state.preset_repository.list()
    service: CollectionService = request.app.state.collection_service
    collections = await service.list_collections()

    collection_exports: list[CollectionExport] = []
    for collection in collections:
        items = await service.list_items(collection.id)
        collection_exports.append(CollectionExport(
            platform=collection.platform.value,
            name=collection.name,
            items=[
                CollectionItemExport(
                    source_url=item.source_url, content_type=item.content_type,
                    author_username=item.author_username, profile_username=item.profile_username,
                    caption=item.caption, thumbnail_url=item.thumbnail_url,
                    external_id=item.external_id, posted_at=item.posted_at,
                )
                for item in items
            ],
        ))

    return ExportBundle(
        pocketdl_export_version=_EXPORT_VERSION,
        exported_at=datetime.now(timezone.utc),
        settings=SettingsExport(download_directory=str(settings.download_directory)),
        presets=[
            PresetExport(
                name=preset.name, preset=preset.preset, concurrent_fragments=preset.concurrent_fragments,
                retries=preset.retries, use_aria2=preset.use_aria2,
            )
            for preset in presets
        ],
        collections=collection_exports,
    )


@router.post('/import', response_model=ImportResultResponse)
async def import_data(bundle: ExportBundle, request: Request) -> ImportResultResponse:
    """Restore a bundle produced by /export. Additive and idempotent: a
    preset whose name already exists is skipped, a playlist is matched by
    (platform, name) and its items de-duplicated by content, so re-importing
    the same file changes nothing. The download directory is applied only if
    it's valid on this machine (paths differ across devices)."""
    notes: list[str] = []
    if bundle.pocketdl_export_version != _EXPORT_VERSION:
        notes.append(
            f'Bundle version {bundle.pocketdl_export_version} differs from this build ({_EXPORT_VERSION}); '
            'imported on a best-effort basis.'
        )

    preset_repository = request.app.state.preset_repository
    existing_preset_names = {preset.name for preset in await preset_repository.list()}
    imported_presets = 0
    for preset in bundle.presets:
        if preset.name in existing_preset_names:
            continue
        await preset_repository.add(DownloadPreset(
            id=uuid.uuid4().hex, name=preset.name[:100], preset=preset.preset,
            concurrent_fragments=preset.concurrent_fragments, retries=preset.retries,
            use_aria2=preset.use_aria2, created_at=datetime.now(timezone.utc),
        ))
        existing_preset_names.add(preset.name)
        imported_presets += 1

    service: CollectionService = request.app.state.collection_service
    by_key = {(c.platform.value, c.name): c for c in await service.list_collections()}
    imported_collections = 0
    imported_items = 0
    for collection_export in bundle.collections:
        key = (collection_export.platform, collection_export.name)
        target = by_key.get(key)
        if target is None:
            target = await service.create_collection(Platform(collection_export.platform), collection_export.name)
            by_key[key] = target
            imported_collections += 1
        previews = [
            ProfileItemPreview(
                source_url=item.source_url, content_type=item.content_type,
                author_username=item.author_username, profile_username=item.profile_username,
                caption=item.caption, thumbnail_url=item.thumbnail_url,
                external_id=item.external_id, posted_at=item.posted_at,
            )
            for item in collection_export.items
        ]
        added, _already = await service.add_items(target.id, previews)
        imported_items += added

    settings_applied = False
    if bundle.settings and bundle.settings.download_directory:
        try:
            directory = normalize_download_directory(bundle.settings.download_directory)
        except ValueError:
            notes.append('The download directory in the bundle is not valid on this machine and was left unchanged.')
        else:
            settings = request.app.state.settings
            settings.download_directory = directory
            request.app.state.captured_media.download_directory = directory
            save_download_directory(settings.database_path, directory)
            settings_applied = True

    return ImportResultResponse(
        imported_presets=imported_presets,
        imported_collections=imported_collections,
        imported_items=imported_items,
        settings_applied=settings_applied,
        notes=notes,
    )


@router.get('/system/status', response_model=SystemStatusResponse)
async def system_status(request: Request) -> SystemStatusResponse:
    versions = await request.app.state.downloader.versions()
    jobs = await request.app.state.repository.list()
    return SystemStatusResponse(
        app_version=request.app.state.settings.app_version,
        yt_dlp_version=versions['yt_dlp'],
        ffmpeg_version=versions['ffmpeg'],
        aria2_version=versions['aria2'],
        download_directory=str(request.app.state.settings.download_directory),
        active_downloads=sum(1 for x in jobs if x.status is DownloadStatus.RUNNING),
        queued_downloads=sum(1 for x in jobs if x.status is DownloadStatus.QUEUED),
    )


@router.get('/system/update-check', response_model=UpdateCheckResponse)
async def check_update(request: Request) -> UpdateCheckResponse:
    """Whether a newer yt-dlp is on PyPI. Makes an external request, so it is
    fetched on demand by the UI (never polled) and degrades to
    update_available=False on any network error rather than failing."""
    versions = await request.app.state.downloader.versions()
    status = await asyncio.to_thread(check_yt_dlp_update, versions.get('yt_dlp'))
    return UpdateCheckResponse(
        current=status.current, latest=status.latest,
        update_available=status.update_available, error=status.error,
    )


@router.post('/system/update/yt-dlp')
async def update_yt_dlp(request: Request) -> dict[str, object]:
    version = await request.app.state.downloader.update_yt_dlp()
    return {'ok': True, 'version': version}


@router.post('/instagram/profile/preview', response_model=InstagramProfilePreviewResponse)
async def preview_instagram_profile(payload: InstagramProfilePreviewRequest, request: Request) -> InstagramProfilePreviewResponse:
    service = request.app.state.profile_discovery_service
    try:
        page = await service.preview(
            payload.profile_url,
            [InstagramContentType(value) for value in payload.content_types],
            payload.posted_after,
            payload.posted_before,
            payload.limit,
        )
    except InstagramAuthRequiredError as exc:
        logger.info('Instagram profile preview requires a session: %s (%s)', payload.profile_url, exc)
        raise HTTPException(status_code=401, detail=f'Instagram session required: {exc}') from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Not a client mistake (bad URL/input already 422'd above) -- an
        # actual instaloader failure the response body alone won't leave a
        # durable trace of, so it's worth a real server-side log line.
        logger.warning('Instagram profile preview failed: %s (%s)', payload.profile_url, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return InstagramProfilePreviewResponse(
        items=[_preview_response(item) for item in page.items],
        has_more=page.has_more,
        next_posted_before=page.next_posted_before,
    )


def _preview_response(item: ProfileItemPreview) -> ProfileItemPreviewResponse:
    return ProfileItemPreviewResponse(
        source_url=item.source_url, content_type=item.content_type, author_username=item.author_username,
        profile_username=item.profile_username, caption=item.caption, thumbnail_url=item.thumbnail_url,
        external_id=item.external_id, posted_at=item.posted_at,
    )


@router.post('/collections/{collection_id}/profile-items', response_model=CollectionAddProfileItemsResponse)
async def add_profile_items_to_collection(
    collection_id: str, payload: CollectionAddProfileItemsRequest, request: Request,
) -> CollectionAddProfileItemsResponse:
    """Add every item matching a profile query, without previewing it first.

    Selecting a whole profile otherwise meant paging through it by hand and
    holding every card on screen just to tick them.
    """
    discovery = request.app.state.profile_discovery_service
    collections: CollectionService = request.app.state.collection_service
    if await collections.get_collection(collection_id) is None:
        raise HTTPException(status_code=404, detail='Collection not found.')

    try:
        page = await discovery.preview(
            payload.profile_url,
            [InstagramContentType(value) for value in payload.content_types],
            payload.posted_after,
            payload.posted_before,
            payload.limit,
        )
    except InstagramAuthRequiredError as exc:
        raise HTTPException(status_code=401, detail=f'Instagram session required: {exc}') from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.warning('Instagram bulk add failed: %s (%s)', payload.profile_url, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    added, already_present = await collections.add_items(collection_id, page.items)
    return CollectionAddProfileItemsResponse(
        added=added,
        already_present=already_present,
        has_more=page.has_more,
        next_posted_before=page.next_posted_before,
    )


@router.get('/instagram/session', response_model=InstagramSessionStatusResponse)
async def get_instagram_session_status(request: Request) -> InstagramSessionStatusResponse:
    settings = request.app.state.settings
    # Deliberately does not call verify_session() here -- this is polled by
    # the UI like any other settings fetch, and verification is a real
    # network call to Instagram; see POST .../session and .../verify below.
    return InstagramSessionStatusResponse(configured=has_session_cookie(settings.database_path, 'instagram'))


@router.post('/instagram/session', response_model=InstagramSessionStatusResponse)
async def set_instagram_session(payload: InstagramSessionRequest, request: Request) -> InstagramSessionStatusResponse:
    settings = request.app.state.settings
    try:
        save_session_cookie(settings.database_path, 'instagram', '.instagram.com', payload.cookie_header)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    verified_username = await _verify_instagram_session(request)
    return InstagramSessionStatusResponse(configured=True, verified_username=verified_username)


@router.post('/instagram/session/verify', response_model=InstagramSessionStatusResponse)
async def verify_instagram_session(request: Request) -> InstagramSessionStatusResponse:
    settings = request.app.state.settings
    configured = has_session_cookie(settings.database_path, 'instagram')
    verified_username = await _verify_instagram_session(request) if configured else None
    return InstagramSessionStatusResponse(configured=configured, verified_username=verified_username)


async def _verify_instagram_session(request: Request) -> str | None:
    """Best-effort: a real call to Instagram, so a network hiccup here
    should not fail the surrounding save/status request -- it just means
    the caller doesn't get a verified username this time."""
    service = request.app.state.profile_discovery_service
    try:
        return await service.verify_session()
    except Exception as exc:
        logger.info('Instagram session verification failed: %s', exc)
        return None


@router.delete('/instagram/session')
async def clear_instagram_session(request: Request) -> dict[str, bool]:
    settings = request.app.state.settings
    clear_session_cookie(settings.database_path, 'instagram')
    return {'ok': True}


@router.get('/collections', response_model=list[CollectionResponse])
async def list_collections(request: Request) -> list[CollectionResponse]:
    service: CollectionService = request.app.state.collection_service
    collections = await service.list_collections()
    # One GROUP BY for every collection's (total, downloaded) counts, rather
    # than a list_items query per collection -- this route is also built into
    # every SSE snapshot, which rebuilds on each download progress tick.
    counts = await service.collection_counts()
    responses = []
    for collection in collections:
        total, downloaded = counts.get(collection.id, (0, 0))
        responses.append(collection_response(collection, total, downloaded))
    return responses


@router.post('/collections', response_model=CollectionResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(payload: CollectionCreateRequest, request: Request) -> CollectionResponse:
    service: CollectionService = request.app.state.collection_service
    try:
        collection = await service.create_collection(Platform(payload.platform), payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return collection_response(collection, 0)


@router.get('/collections/{collection_id}', response_model=CollectionResponse)
async def get_collection(collection_id: str, request: Request) -> CollectionResponse:
    service: CollectionService = request.app.state.collection_service
    collection = await service.get_collection(collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail='Collection not found')
    items = await service.list_items(collection_id)
    downloaded = sum(1 for item in items if item.downloaded_job_id is not None)
    return collection_response(collection, len(items), downloaded)


@router.put('/collections/{collection_id}', response_model=CollectionResponse)
async def rename_collection(collection_id: str, payload: CollectionRenameRequest, request: Request) -> CollectionResponse:
    service: CollectionService = request.app.state.collection_service
    try:
        collection = await service.rename_collection(collection_id, payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    items = await service.list_items(collection_id)
    downloaded = sum(1 for item in items if item.downloaded_job_id is not None)
    return collection_response(collection, len(items), downloaded)


@router.delete('/collections/{collection_id}')
async def delete_collection(collection_id: str, request: Request) -> dict[str, bool]:
    service: CollectionService = request.app.state.collection_service
    await service.delete_collection(collection_id)
    return {'ok': True}


@router.get('/collections/{collection_id}/items', response_model=list[CollectionItemResponse])
async def list_collection_items(
    collection_id: str,
    request: Request,
    state: Literal['all', 'pending', 'downloaded'] = 'all',
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[CollectionItemResponse]:
    """One page of a playlist, filtered by download state.

    A long playlist is split into pending / downloaded / all tabs, each
    paged, so it is no longer one unbounded scroll. The by-state totals a
    client needs to render those tabs live come from the collection summary
    (item_count / downloaded_count), so this returns just the rows.
    """
    service: CollectionService = request.app.state.collection_service
    collection = await service.get_collection(collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail='Collection not found')
    items = await service.list_items_page(collection_id, state=state, limit=limit, offset=offset)
    return [collection_item_response(item) for item in items]


@router.post('/collections/{collection_id}/items', response_model=CollectionItemResponse, status_code=status.HTTP_201_CREATED)
async def add_collection_item(collection_id: str, payload: CollectionItemAddRequest, request: Request) -> CollectionItemResponse:
    service: CollectionService = request.app.state.collection_service
    preview = ProfileItemPreview(
        source_url=payload.source_url,
        content_type=payload.content_type,
        author_username=payload.author_username,
        profile_username=payload.profile_username,
        caption=payload.caption,
        thumbnail_url=payload.thumbnail_url,
        external_id=payload.external_id,
        posted_at=payload.posted_at,
    )
    try:
        item = await service.add_item(collection_id, preview)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return collection_item_response(item)


@router.delete('/collections/{collection_id}/items/{item_id}')
async def remove_collection_item(collection_id: str, item_id: str, request: Request) -> dict[str, bool]:
    service: CollectionService = request.app.state.collection_service
    await service.remove_item(collection_id, item_id)
    return {'ok': True}


@router.post('/collections/{collection_id}/download', response_model=list[DownloadResponse], status_code=status.HTTP_201_CREATED)
async def download_collection(collection_id: str, payload: CollectionDownloadRequest, request: Request) -> list[DownloadResponse]:
    service: CollectionService = request.app.state.collection_service
    try:
        jobs = await service.download_collection(
            collection_id,
            payload.item_ids,
            request_context=RequestContext(impersonation=ImpersonationMode.NONE),
            preset=payload.preset,
            concurrent_fragments=payload.concurrent_fragments,
            retries=payload.retries,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [to_response(job) for job in jobs]
