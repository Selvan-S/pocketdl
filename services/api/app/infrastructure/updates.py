import json
import urllib.request
from dataclasses import dataclass

# yt-dlp publishes to PyPI with date-based versions (YYYY.MM.DD[.N]), which
# sort correctly as plain strings -- so no version-parsing dependency needed.
_PYPI_URL = 'https://pypi.org/pypi/yt-dlp/json'
_TIMEOUT_SECONDS = 8.0


@dataclass(slots=True)
class UpdateStatus:
    current: str | None
    latest: str | None
    update_available: bool
    error: str | None = None


def _normalize(version: str | None) -> str | None:
    """yt-dlp --version prints just the version, but be defensive and take the
    first whitespace-separated token."""
    if not version:
        return None
    token = version.strip().split()
    return token[0] if token else None


def _fetch_latest_yt_dlp() -> str:
    request = urllib.request.Request(_PYPI_URL, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310 (fixed trusted URL)
        payload = json.loads(response.read().decode('utf-8'))
    return str(payload['info']['version'])


def check_yt_dlp_update(current: str | None) -> UpdateStatus:
    """Compare the installed yt-dlp against the latest on PyPI. Synchronous;
    call via asyncio.to_thread. Best-effort: any network/parse failure reports
    update_available=False with the error, never raises -- a version check
    must not break the page."""
    normalized_current = _normalize(current)
    try:
        latest = _normalize(_fetch_latest_yt_dlp())
    except Exception as exc:  # noqa: BLE001 (best-effort: report, don't raise)
        return UpdateStatus(current=normalized_current, latest=None, update_available=False, error=str(exc))
    available = bool(latest and normalized_current and latest > normalized_current)
    return UpdateStatus(current=normalized_current, latest=latest, update_available=available)
