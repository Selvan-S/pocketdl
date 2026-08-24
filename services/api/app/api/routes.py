from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status

from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnalyzedFormatResponse,
    CaptureCreateRequest,
    CaptureDownloadRequest,
    CaptureResponse,
    CaptureVariantResponse,
    DownloadCreateRequest,
    DownloadResponse,
    SystemStatusResponse,
    SettingsResponse,
    SettingsUpdateRequest,
)
from ..application.captures.service import CaptureService
from ..core.path_settings import normalize_download_directory
from ..core.platform import open_directory
from ..core.settings_store import clear_download_directory, save_download_directory
from ..domain.captures import CaptureType, CaptureVariant, is_suspicious_capture
from ..domain.manifests import VariantStream, estimated_size_bytes, quality_label
from ..domain.models import DownloadSourceType, DownloadStatus, ImpersonationMode, RequestContext

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


@router.post('/downloads', response_model=DownloadResponse, status_code=status.HTTP_201_CREATED)
async def create_download(payload: DownloadCreateRequest, request: Request) -> DownloadResponse:
    queue = request.app.state.queue
    context = _context(payload.request_context)
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


@router.delete('/downloads/{job_id}')
async def delete_download(job_id: str, request: Request) -> dict[str, bool]:
    job = await request.app.state.repository.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Download not found')
    if job.status in {DownloadStatus.QUEUED, DownloadStatus.RUNNING}:
        raise HTTPException(status_code=409, detail='Cancel the download before removing it')
    await request.app.state.repository.delete(job_id)
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
    )
    return to_response(job)


@router.delete('/captures/{capture_id}')
async def delete_capture(capture_id: str, request: Request) -> dict[str, bool]:
    capture = await request.app.state.capture_repository.get(capture_id)
    if capture is None:
        raise HTTPException(status_code=404, detail='Capture not found')
    await request.app.state.capture_repository.delete(capture_id)
    return {'ok': True}


@router.get('/settings', response_model=SettingsResponse)
async def get_settings_route(request: Request) -> SettingsResponse:
    settings = request.app.state.settings
    default_directory = request.app.state.default_download_directory
    return SettingsResponse(
        download_directory=str(settings.download_directory),
        default_download_directory=str(default_directory),
    )


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
    return SettingsResponse(
        download_directory=str(directory),
        default_download_directory=str(request.app.state.default_download_directory),
    )


@router.post('/settings/reset-download-directory', response_model=SettingsResponse)
async def reset_download_directory(request: Request) -> SettingsResponse:
    settings = request.app.state.settings
    directory = request.app.state.default_download_directory
    directory.mkdir(parents=True, exist_ok=True)
    request.app.state.settings.download_directory = directory
    request.app.state.captured_media.download_directory = directory
    clear_download_directory(settings.database_path)
    return SettingsResponse(
        download_directory=str(directory),
        default_download_directory=str(request.app.state.default_download_directory),
    )


@router.post('/settings/open-download-directory')
async def open_download_directory(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    try:
        open_directory(settings.download_directory)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f'Unable to open download directory: {exc}') from exc
    return {'ok': True, 'download_directory': str(settings.download_directory)}


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


@router.post('/system/update/yt-dlp')
async def update_yt_dlp(request: Request) -> dict[str, object]:
    version = await request.app.state.downloader.update_yt_dlp()
    return {'ok': True, 'version': version}
