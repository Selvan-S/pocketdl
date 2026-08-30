import asyncio
import json
import re
import shutil
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from ..application.downloads.errors import classify_download_error
from ..application.downloads.strategy import (
    DownloadAttempt,
    ffmpeg_hls_attempt,
    format_args,
    impersonated_attempt,
    initial_attempt,
    should_retry_with_ffmpeg,
    should_retry_with_impersonation,
    should_retry_without_cert_verification,
    without_cert_verification,
)
from ..core.config import DEFAULT_FILENAME_TEMPLATE, FILENAME_TEMPLATES, Settings
from ..core.filenames import sanitize_filename, unique_stem
from ..domain.analyzer import MediaAnalysis, parse_media_analysis
from ..domain.models import ConflictStrategy, DownloadEngine, DownloadJob, DownloadStatus, DownloadSourceType, MediaOptions, RequestContext
from .ffmpeg import CapturedMediaService
from .gallery_dl import GalleryDlService
from .instaloader_service import InstaloaderService

ProgressCallback = Callable[[DownloadJob], Awaitable[None]]


class YtDlpService:
    def __init__(
        self,
        settings: Settings,
        captured_media: CapturedMediaService,
        gallery_dl: GalleryDlService,
        instaloader_service: InstaloaderService,
    ) -> None:
        self.settings = settings
        self.captured_media = captured_media
        self.gallery_dl = gallery_dl
        self.instaloader_service = instaloader_service
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        # yt-dlp/ffmpeg/aria2 versions only change on an explicit "Update
        # yt-dlp" action or a backend restart, never mid-session, so there is
        # no reason to re-spawn three subprocesses on every /system/status
        # poll (every 2s from the PWA). On Android/Termux specifically, a
        # backgrounded app gets its CPU throttled, so each of those three
        # sequential subprocess.run(..., timeout=10) calls can take the full
        # 10s instead of completing instantly — up to 30s per request,
        # compounding as new polls fire before the previous one resolves.
        self._cached_versions: dict[str, str | None] | None = None
        self._versions_lock = asyncio.Lock()

    @staticmethod
    def _tool_version(command: list[str]) -> str | None:
        try:
            import subprocess
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
            output = (result.stdout or result.stderr).splitlines()
            return output[0].strip() if output else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _versions_sync(self) -> dict[str, str | None]:
        return {
            'yt_dlp': self._tool_version([sys.executable, '-m', 'yt_dlp', '--version']),
            'ffmpeg': self._tool_version(['ffmpeg', '-version']),
            'aria2': self._tool_version(['aria2c', '--version']),
        }

    async def versions(self) -> dict[str, str | None]:
        if self._cached_versions is not None:
            return self._cached_versions
        # Lock so concurrent callers during the cold-start window (e.g.
        # several overlapping polls before the first call resolves) await the
        # same in-flight computation instead of each spawning their own three
        # subprocesses.
        async with self._versions_lock:
            if self._cached_versions is None:
                self._cached_versions = await asyncio.to_thread(self._versions_sync)
            return self._cached_versions

    async def refresh_versions(self) -> dict[str, str | None]:
        async with self._versions_lock:
            self._cached_versions = await asyncio.to_thread(self._versions_sync)
            return self._cached_versions

    async def update_yt_dlp(self) -> str | None:
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-m', 'pip', 'install', '-U', 'yt-dlp[default,curl-cffi]',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, = await asyncio.gather(process.communicate())
        if process.returncode != 0:
            details = (output or b'').decode(errors='replace').strip()
            raise RuntimeError(f'yt-dlp update failed.\n{details}')
        versions = await self.refresh_versions()
        return versions['yt_dlp']


    def _context_args(self, request_context: RequestContext, *, impersonate: str | None = None) -> list[str]:
        args: list[str] = []
        if request_context.user_agent:
            args += ['--user-agent', request_context.user_agent]
        if request_context.referer:
            args += ['--add-header', f'Referer:{request_context.referer}']
        if request_context.origin:
            args += ['--add-header', f'Origin:{request_context.origin}']
        for name, value in request_context.headers.items():
            if name.lower() in {'cookie', 'authorization', 'proxy-authorization'}:
                continue
            args += ['--add-header', f'{name}:{value}']
        if impersonate:
            args += ['--impersonate', impersonate]
        return args

    async def analyze(self, url: str, *, request_context: RequestContext) -> MediaAnalysis:
        attempts = ['chrome'] if request_context.impersonation.value == 'chrome' else [None]
        if request_context.impersonation.value == 'auto':
            attempts = [None, 'chrome']

        last_output = ''
        for index, impersonate in enumerate(attempts):
            args = [
                sys.executable, '-m', 'yt_dlp',
                '--no-warnings',
                '--no-playlist',
                '--skip-download',
                '--dump-single-json',
                *self._context_args(request_context, impersonate=impersonate),
                url,
            ]
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
            stdout_text = stdout.decode(errors='replace').strip()
            stderr_text = stderr.decode(errors='replace').strip()
            last_output = '\n'.join(part for part in (stderr_text, stdout_text) if part)
            if process.returncode == 0 and stdout_text:
                try:
                    payload = json.loads(stdout_text)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f'yt-dlp returned invalid analysis JSON: {exc}') from exc
                return parse_media_analysis(payload, url)
            if index == 0 and impersonate is None and 'HTTP Error 403' in last_output and request_context.impersonation.value == 'auto':
                continue
            break

        raise RuntimeError(last_output or 'yt-dlp analysis failed.')

    def _output_template(self, job: DownloadJob, conflict_strategy: ConflictStrategy = ConflictStrategy.SKIP) -> str:
        directory = self.settings.download_directory
        if job.filename:
            stem = sanitize_filename(job.filename)
            # RENAME needs the collision resolved up front, since we know the
            # stem here. A title-based download (no explicit filename) can't
            # be resolved in advance -- its final name isn't known until
            # yt-dlp extracts it -- so it relies on the --no-overwrites flag
            # from _conflict_args instead.
            if conflict_strategy is ConflictStrategy.RENAME:
                stem = unique_stem(directory, stem)
            return str(directory / f'{stem}.%(ext)s')
        # No explicit filename: use the configured naming pattern. The client
        # only ever chooses a key from a fixed map, never raw template syntax.
        pattern = FILENAME_TEMPLATES.get(self.settings.filename_template, FILENAME_TEMPLATES[DEFAULT_FILENAME_TEMPLATE])
        return str(directory / f'{pattern}.%(ext)s')

    # Bracketed marketing noise commonly stuck on titles. Removed from the
    # title metadata (so it's out of the filename) when clean_titles is on.
    # Conservative: only clearly-promotional tags, and only affects the
    # filename/embedded title, never the stored DB record.
    _TITLE_NOISE_PATTERN = (
        r'(?i)\s*[\(\[](?:official\s+)?(?:music\s+)?'
        r'(?:video|audio|lyrics?|lyric video|visualizer|mv|hd|4k|full album|official)[\)\]]'
    )

    def _title_cleanup_args(self) -> list[str]:
        if not self.settings.clean_titles:
            return []
        return [
            '--replace-in-metadata', 'title', self._TITLE_NOISE_PATTERN, '',
            # Collapse the double spaces a removal can leave behind.
            '--replace-in-metadata', 'title', r'\s{2,}', ' ',
        ]

    @staticmethod
    def _conflict_args(conflict_strategy: ConflictStrategy) -> list[str]:
        if conflict_strategy is ConflictStrategy.OVERWRITE:
            return ['--force-overwrites']
        # SKIP and RENAME both must never clobber an existing file. RENAME has
        # already picked a free name for an explicit filename; --no-overwrites
        # is the backstop (and, for a title-based download, the whole
        # behaviour: yt-dlp skips a file it has already downloaded).
        return ['--no-overwrites']

    @staticmethod
    def _error_summary(lines: list[str], return_code: int) -> str:
        errors = [line.strip() for line in lines if 'ERROR:' in line]
        if errors:
            return '\n'.join(dict.fromkeys(errors))
        return f'yt-dlp exited with code {return_code}.'

    @staticmethod
    def _subtitle_args(preset: str, media_options: MediaOptions) -> list[str]:
        # Subtitles are meaningless for an audio-only extraction, and can't be
        # embedded into an mp3 -- so skip them there entirely.
        if not media_options.subtitles or preset == 'audio':
            return []
        args = ['--write-subs', '--write-auto-subs', '--sub-langs', media_options.subtitle_langs]
        if media_options.embed_subtitles:
            # Embed into the container; still keep the sidecar so nothing is
            # lost if the muxer can't carry a given subtitle codec.
            args.append('--embed-subs')
        return args

    def _build_args(
        self,
        job: DownloadJob,
        *,
        preset: str,
        format_id: str | None,
        concurrent_fragments: int,
        retries: int,
        use_aria2: bool,
        request_context: RequestContext,
        attempt: DownloadAttempt,
        media_options: MediaOptions = MediaOptions(),
    ) -> list[str]:
        args = [
            sys.executable,
            '-m',
            'yt_dlp',
            '--newline',
            '--retries',
            str(max(1, retries)),
            '--fragment-retries',
            str(max(1, retries)),
            '--concurrent-fragments',
            str(max(1, min(concurrent_fragments, 32))),
            '--output',
            self._output_template(job, media_options.conflict_strategy),
            *format_args(preset, format_id),
        ]
        args += self._conflict_args(media_options.conflict_strategy)
        args += self._title_cleanup_args()
        args += self._subtitle_args(preset, media_options)
        # Prefer a particular audio-track language when the source has several.
        # -S sorting, not a filter: a single-track source is unaffected.
        if media_options.audio_language:
            args += ['-S', f'lang:{media_options.audio_language}']
        args += self._context_args(request_context, impersonate=attempt.impersonate)
        if attempt.use_ffmpeg_hls:
            args += ['--downloader', 'ffmpeg', '--hls-use-mpegts']
        elif use_aria2 and shutil.which('aria2c'):
            args += ['--downloader', 'aria2c']
        if attempt.no_check_certificate:
            args.append('--no-check-certificate')
        args.append(job.url)
        return args

    async def _run_process(self, job: DownloadJob, args: list[str], on_progress: ProgressCallback) -> tuple[int, list[str]]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._processes[job.id] = process
        output_lines: list[str] = []
        try:
            assert process.stdout is not None
            async for raw_line in process.stdout:
                line = raw_line.decode(errors='replace').rstrip()
                output_lines.append(line)
                self._parse_output(job, line)
                await on_progress(job)
            return await process.wait(), output_lines
        finally:
            self._processes.pop(job.id, None)

    async def download(
        self,
        job: DownloadJob,
        *,
        preset: str,
        format_id: str | None = None,
        concurrent_fragments: int,
        retries: int,
        use_aria2: bool,
        request_context: RequestContext,
        source_type: DownloadSourceType,
        capture_id: str | None,
        on_progress: ProgressCallback,
        audio_url: str | None = None,
        collection_item_id: str | None = None,
        media_options: MediaOptions = MediaOptions(),
    ) -> DownloadJob:
        if job.engine is DownloadEngine.GALLERY_DL:
            return await self.gallery_dl.download(
                job,
                context=request_context,
                retries=retries,
                on_progress=on_progress,
                collection_item_id=collection_item_id,
            )

        if job.engine is DownloadEngine.INSTALOADER:
            return await self.instaloader_service.download(
                job,
                context=request_context,
                retries=retries,
                on_progress=on_progress,
                collection_item_id=collection_item_id,
            )

        if source_type is DownloadSourceType.CAPTURED:
            return await self.captured_media.download(
                job,
                context=request_context,
                retries=retries,
                on_progress=on_progress,
                audio_url=audio_url,
            )

        job.status = DownloadStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.error = None
        job.error_details = None
        job.error_category = None
        job.exit_code = None
        await on_progress(job)

        outputs: list[str] = []
        attempts: list[DownloadAttempt] = []
        current = initial_attempt(request_context)

        async def run_attempt(attempt: DownloadAttempt) -> tuple[int, str]:
            job.impersonation = request_context.impersonation
            args = self._build_args(
                job,
                preset=preset,
                format_id=format_id,
                concurrent_fragments=concurrent_fragments,
                retries=retries,
                use_aria2=use_aria2,
                request_context=request_context,
                attempt=attempt,
                media_options=media_options,
            )
            return_code, lines = await self._run_process(job, args, on_progress)
            output = '\n'.join(lines)
            attempts.append(attempt)
            outputs.extend([f'[{attempt.label}]', *lines])
            return return_code, output

        try:
            return_code, output = await run_attempt(current)
            error_category = classify_download_error(output)

            if return_code != 0 and should_retry_with_impersonation(job, output, request_context, error_category):
                job.retry_count += 1
                await on_progress(job)
                return_code, output = await run_attempt(impersonated_attempt())
                error_category = classify_download_error(output)

            combined_output = '\n'.join(outputs)
            if return_code != 0 and should_retry_with_ffmpeg(combined_output):
                job.retry_count += 1
                await on_progress(job)
                used_chrome = any(item.impersonate == 'chrome' for item in attempts)
                return_code, output = await run_attempt(ffmpeg_hls_attempt(used_chrome))
                error_category = classify_download_error(output)

            if return_code != 0 and should_retry_without_cert_verification(error_category, attempts[-1]):
                job.retry_count += 1
                await on_progress(job)
                return_code, output = await run_attempt(without_cert_verification(attempts[-1]))
                error_category = classify_download_error(output)

            if job.status is DownloadStatus.CANCELLED:
                return job

            job.exit_code = return_code
            job.status = DownloadStatus.COMPLETED if return_code == 0 else DownloadStatus.FAILED
            job.progress = 100.0 if return_code == 0 else job.progress
            job.error = None if return_code == 0 else self._error_summary(outputs, return_code)
            job.error_details = None if return_code == 0 else '\n'.join(outputs).strip()
            job.error_category = None if return_code == 0 else error_category
            job.finished_at = datetime.now(timezone.utc)
            await on_progress(job)
            return job
        except asyncio.CancelledError:
            await self.cancel(job.id)
            raise
        except Exception as exc:
            job.status = DownloadStatus.FAILED
            job.exit_code = None
            job.error = f'Downloader error: {exc}'
            job.error_details = '\n'.join(outputs).strip() or repr(exc)
            job.error_category = classify_download_error(job.error_details)
            job.finished_at = datetime.now(timezone.utc)
            await on_progress(job)
            return job

    @staticmethod
    def _parse_output(job: DownloadJob, line: str) -> None:
        percent = re.search(r'(\d+(?:\.\d+)?)%', line)
        if percent:
            job.progress = float(percent.group(1))
        speed = re.search(r' at ([\d.]+)([KMG]?i?B)/s', line)
        if speed:
            multiplier = {
                'B': 1,
                'KB': 1000,
                'KiB': 1024,
                'MB': 1000**2,
                'MiB': 1024**2,
                'GB': 1000**3,
                'GiB': 1024**3,
            }.get(speed.group(2), 1)
            job.speed_bytes = float(speed.group(1)) * multiplier
        eta = re.search(r'\bETA ([0-9:]+)', line)
        if eta:
            parts = [int(x) for x in eta.group(1).split(':')]
            if len(parts) == 2:
                job.eta_seconds = parts[0] * 60 + parts[1]
            elif len(parts) == 3:
                job.eta_seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
        if line.startswith('[download] Destination:'):
            job.output_path = line.split(':', 1)[1].strip()
        if '[Merger] Merging formats into' in line:
            job.output_path = line.split('into', 1)[1].strip().strip('"')
        title_match = re.search(r'\[download\] (.+?): Downloading', line)
        if title_match:
            job.title = title_match.group(1)

    async def cancel(self, job_id: str) -> None:
        process = self._processes.get(job_id)
        if process is None:
            return
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
