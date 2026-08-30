import asyncio
import re
import shutil
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from ..core.filenames import sanitize_filename
from ..domain.errors import DownloadErrorCategory
from ..domain.models import DownloadJob, DownloadStatus, RequestContext

ProgressCallback = Callable[[DownloadJob], Awaitable[None]]


class CapturedMediaService:
    """Download browser-captured HLS/DASH manifests directly with FFmpeg."""

    def __init__(self, download_directory: Path) -> None:
        self.download_directory = download_directory
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    # Headers we never forward to ffmpeg. Credentials are dropped for the
    # usual reasons; accept-encoding is dropped because the captured value is
    # the *browser's* (e.g. "gzip, deflate, br, zstd") and ffmpeg's HTTP
    # client cannot decode brotli/zstd -- it then receives a compressed body,
    # fails to recognise the playlist, and dies with "Unknown content coding:
    # br" / "Invalid data found". We force identity below instead.
    _SKIP_HEADERS = {'cookie', 'authorization', 'proxy-authorization', 'set-cookie', 'host', 'accept-encoding'}

    @staticmethod
    def _headers_block(context: RequestContext) -> str:
        headers: dict[str, str] = {}
        for name, value in context.headers.items():
            if name.lower() in CapturedMediaService._SKIP_HEADERS:
                continue
            headers[name] = value
        if context.referer:
            headers['Referer'] = context.referer
        if context.origin:
            headers['Origin'] = context.origin
        # Ask for an uncompressed response: the one encoding ffmpeg reliably
        # handles here is identity. Set last so it wins over anything above.
        headers['Accept-Encoding'] = 'identity'
        return ''.join(f'{name}: {value}\r\n' for name, value in headers.items())

    @staticmethod
    def _parse_progress(job: DownloadJob, line: str, duration_us: int | None) -> None:
        line = line.strip()
        match = re.search(r'^out_time_us=(\d+)$', line)
        if match and duration_us and duration_us > 0:
            elapsed_us = int(match.group(1))
            job.progress = min(100.0, max(0.0, elapsed_us / duration_us * 100.0))
        if line == 'progress=end':
            job.progress = 100.0

    @staticmethod
    def _input_args(url: str, headers: str, user_agent: str | None) -> list[str]:
        """Options for one input. ffmpeg applies these to the ``-i`` that
        follows, so a second input needs its own copy rather than inheriting
        the first one's."""
        args: list[str] = []
        if headers:
            args += ['-headers', headers]
        if user_agent:
            args += ['-user_agent', user_agent]
        return args + [
            # Some sites disguise HLS playlists/segments with non-media
            # extensions (.txt, .css) to dodge naive ad-blockers/bandwidth
            # savers. ffmpeg's hls demuxer rejects segment URLs whose
            # extension isn't on a small built-in allowlist unless told
            # otherwise (exit 183, "not in allowed_segment_extensions").
            '-allowed_extensions', 'ALL',
            '-i', url,
        ]

    @staticmethod
    def _build_ffmpeg_args(
        url: str,
        output_path: Path,
        headers: str,
        user_agent: str | None,
        audio_url: str | None = None,
        subtitle_url: str | None = None,
    ) -> list[str]:
        args = ['ffmpeg', '-hide_banner', '-nostdin', '-y', '-loglevel', 'warning']
        args += CapturedMediaService._input_args(url, headers, user_agent)
        # Input indices: video is 0. A separate audio rendition (if any) is
        # next, then a subtitle rendition (if any). Track them so the -map
        # arguments reference the right inputs.
        next_input = 1
        maps = ['-map', '0:v:0?']
        if audio_url:
            # A specific HLS quality whose master lists audio as a separate
            # #EXT-X-MEDIA rendition: the variant playlist carries video only,
            # so downloading it alone would produce a silent file. Mux the
            # rendition in as a second input.
            args += CapturedMediaService._input_args(audio_url, headers, user_agent)
            maps += ['-map', f'{next_input}:a:0?']
            next_input += 1
        else:
            maps += ['-map', '0:a:0?']
        codec_args = ['-c', 'copy', '-movflags', '+faststart']
        if subtitle_url:
            # HLS subtitles are a separate #EXT-X-MEDIA:TYPE=SUBTITLES playlist
            # (usually WebVTT). Add it as its own input and convert to mov_text
            # so it embeds in the mp4 container.
            args += CapturedMediaService._input_args(subtitle_url, headers, user_agent)
            maps += ['-map', f'{next_input}:s:0?']
            codec_args += ['-c:s', 'mov_text']
            next_input += 1
        args += maps
        args += codec_args
        args += ['-progress', 'pipe:1', str(output_path)]
        return args

    async def _probe_duration(self, url: str, context: RequestContext) -> int | None:
        ffprobe = shutil.which('ffprobe')
        if not ffprobe:
            return None
        args = [ffprobe, '-v', 'error', '-allowed_extensions', 'ALL']
        headers = self._headers_block(context)
        if headers:
            args += ['-headers', headers]
        if context.user_agent:
            args += ['-user_agent', context.user_agent]
        args += ['-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', url]
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=60)
        if process.returncode != 0:
            return None
        try:
            seconds = float(stdout.decode(errors='replace').strip())
        except ValueError:
            return None
        return max(1, int(seconds * 1_000_000))

    async def download(
        self,
        job: DownloadJob,
        *,
        context: RequestContext,
        retries: int,
        on_progress: ProgressCallback,
        audio_url: str | None = None,
        subtitle_url: str | None = None,
    ) -> DownloadJob:
        job.status = DownloadStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.error = None
        job.error_details = None
        job.error_category = None
        job.exit_code = None
        await on_progress(job)

        stem = sanitize_filename(job.filename) if job.filename else sanitize_filename(job.title or f'capture-{job.id[:8]}')
        output_path = self.download_directory / f'{stem}.mp4'
        if output_path.exists():
            output_path = self.download_directory / f'{stem}-{job.id[:8]}.mp4'

        headers = self._headers_block(context)
        duration_us = await self._probe_duration(job.url, context)
        max_attempts = max(1, min(retries, 5))
        attempt_outputs: list[str] = []
        return_code = 1

        for attempt_number in range(1, max_attempts + 1):
            args = self._build_ffmpeg_args(job.url, output_path, headers, context.user_agent, audio_url, subtitle_url)

            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            self._processes[job.id] = process
            try:
                assert process.stdout is not None
                async for raw in process.stdout:
                    line = raw.decode(errors='replace').rstrip()
                    attempt_outputs.append(f'[ffmpeg attempt {attempt_number}] {line}')
                    self._parse_progress(job, line, duration_us)
                    if output_path.exists():
                        try:
                            job.downloaded_bytes = output_path.stat().st_size
                        except OSError:
                            pass
                    await on_progress(job)
                return_code = await process.wait()
            finally:
                self._processes.pop(job.id, None)

            if job.status is DownloadStatus.CANCELLED:
                return job
            if return_code == 0 and output_path.exists():
                break
            if attempt_number < max_attempts:
                await asyncio.sleep(min(2 * attempt_number, 5))

        job.exit_code = return_code
        if return_code == 0 and output_path.exists():
            job.output_path = str(output_path)
            job.progress = 100.0
            job.status = DownloadStatus.COMPLETED
            job.error = None
            job.error_details = None
            job.error_category = None
        else:
            job.status = DownloadStatus.FAILED
            job.error = f'FFmpeg exited with code {return_code}.'
            job.error_details = '\n'.join(attempt_outputs).strip()
            job.error_category = DownloadErrorCategory.FFMPEG_ERROR
        job.finished_at = datetime.now(timezone.utc)
        await on_progress(job)
        return job

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
