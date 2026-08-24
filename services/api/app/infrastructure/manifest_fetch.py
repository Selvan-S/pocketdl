"""Fetch a captured playlist's text using the browser's own request context.

Uses the standard library rather than adding an HTTP client dependency: a
manifest is a small text file, and the backend already declares only the
dependencies documented in ``requirements.txt``. The blocking call runs in a
worker thread so it never stalls the event loop.
"""

import asyncio
import ssl
import urllib.error
import urllib.request

from ..domain.models import RequestContext

# Manifests are text. A master playlist is measured in kilobytes; anything
# past this is not a playlist we should be parsing, and reading it unbounded
# would let a hostile or misidentified URL exhaust memory.
MAX_MANIFEST_BYTES = 4 * 1024 * 1024

_BLOCKED_HEADERS = {'cookie', 'authorization', 'proxy-authorization', 'set-cookie', 'host', 'content-length'}


class ManifestFetcher:
    def __init__(self, timeout_seconds: int = 20) -> None:
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _headers(context: RequestContext) -> dict[str, str]:
        headers = {name: value for name, value in context.headers.items() if name.lower() not in _BLOCKED_HEADERS}
        if context.referer:
            headers['Referer'] = context.referer
        if context.origin:
            headers['Origin'] = context.origin
        if context.user_agent:
            headers['User-Agent'] = context.user_agent
        return headers

    def _read(self, request: urllib.request.Request, *, ssl_context: ssl.SSLContext | None) -> str:
        with urllib.request.urlopen(request, timeout=self.timeout_seconds, context=ssl_context) as response:
            payload = response.read(MAX_MANIFEST_BYTES + 1)
        if len(payload) > MAX_MANIFEST_BYTES:
            raise RuntimeError('Playlist is larger than the supported manifest size.')
        return payload.decode('utf-8', errors='replace')

    def _fetch_sync(self, url: str, context: RequestContext) -> str:
        request = urllib.request.Request(url, headers=self._headers(context), method='GET')
        try:
            return self._read(request, ssl_context=None)
        except urllib.error.URLError as exc:
            # Same incomplete-certificate-chain case the standard download
            # path already retries: browsers repair it via AIA chasing,
            # Python's ssl module does not. One retry, never a blanket
            # default.
            if not isinstance(exc.reason, ssl.SSLCertVerificationError):
                raise
            return self._read(request, ssl_context=ssl._create_unverified_context())

    async def fetch(self, url: str, context: RequestContext) -> str:
        return await asyncio.wait_for(
            asyncio.to_thread(self._fetch_sync, url, context),
            timeout=self.timeout_seconds + 5,
        )
