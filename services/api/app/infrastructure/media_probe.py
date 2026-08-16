import asyncio
import json
import shutil
from dataclasses import dataclass

from ..domain.models import RequestContext


@dataclass(frozen=True, slots=True)
class MediaProbeResult:
    size_bytes: int | None
    duration_seconds: float | None
    width: int | None
    height: int | None


class MediaProbeService:
    def __init__(self, timeout_seconds: int = 45) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _headers_block(context: RequestContext) -> str:
        headers: dict[str, str] = {}
        for name, value in context.headers.items():
            if name.lower() in {'cookie', 'authorization', 'proxy-authorization', 'set-cookie', 'host'}:
                continue
            headers[name] = value
        if context.referer:
            headers['Referer'] = context.referer
        if context.origin:
            headers['Origin'] = context.origin
        return ''.join(f'{name}: {value}\r\n' for name, value in headers.items())

    async def probe(self, url: str, context: RequestContext) -> MediaProbeResult:
        ffprobe = shutil.which('ffprobe')
        if not ffprobe:
            raise RuntimeError('ffprobe was not found on PATH.')

        args = [
            ffprobe,
            '-v', 'error',
            '-print_format', 'json',
            '-show_entries', 'format=duration,size:stream=codec_type,width,height',
        ]
        headers = self._headers_block(context)
        if headers:
            args += ['-headers', headers]
        if context.user_agent:
            args += ['-user_agent', context.user_agent]
        args.append(url)

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError('Media metadata probe timed out.')

        if process.returncode != 0:
            detail = stderr.decode(errors='replace').strip()
            raise RuntimeError(detail or f'ffprobe exited with code {process.returncode}.')

        try:
            payload = json.loads(stdout.decode(errors='replace'))
        except json.JSONDecodeError as exc:
            raise RuntimeError('ffprobe returned invalid metadata JSON.') from exc

        format_info = payload.get('format') if isinstance(payload, dict) else {}
        if not isinstance(format_info, dict):
            format_info = {}
        streams = payload.get('streams') if isinstance(payload, dict) else []
        if not isinstance(streams, list):
            streams = []

        duration: float | None = None
        if format_info.get('duration') not in (None, ''):
            try:
                duration = max(0.0, float(format_info['duration']))
            except (TypeError, ValueError):
                duration = None

        size_bytes: int | None = None
        if format_info.get('size') not in (None, ''):
            try:
                size_bytes = max(0, int(format_info['size']))
            except (TypeError, ValueError):
                size_bytes = None

        width = None
        height = None
        for stream in streams:
            if not isinstance(stream, dict) or stream.get('codec_type') != 'video':
                continue
            width = stream.get('width') if isinstance(stream.get('width'), int) else None
            height = stream.get('height') if isinstance(stream.get('height'), int) else None
            break

        return MediaProbeResult(
            size_bytes=size_bytes,
            duration_seconds=duration,
            width=width,
            height=height,
        )
