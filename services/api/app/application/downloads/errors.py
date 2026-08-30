from ...domain.errors import DownloadErrorCategory


def classify_download_error(output: str) -> DownloadErrorCategory:
    text = output.lower()

    if 'geo restriction' in text or 'not available in your country' in text or 'not available in your region' in text:
        return DownloadErrorCategory.GEO_RESTRICTION
    if 'drm' in text or 'digital rights management' in text or 'encrypted media' in text:
        return DownloadErrorCategory.DRM
    if 'unsupported url' in text or 'no suitable extractor' in text:
        return DownloadErrorCategory.UNSUPPORTED_URL
    if 'requested format is not available' in text or 'requested format not available' in text or 'format is not available' in text:
        return DownloadErrorCategory.FORMAT_ERROR
    if 'certificate verify failed' in text or 'certificate_verify_failed' in text or 'ssl: cert' in text:
        return DownloadErrorCategory.SSL_CERTIFICATE_ERROR
    if 'ffmpeg' in text and ('error' in text or 'failed' in text):
        return DownloadErrorCategory.FFMPEG_ERROR
    if 'rate limit' in text or 'too many requests' in text or 'http error 429' in text:
        return DownloadErrorCategory.RATE_LIMITED
    if 'authentication required' in text or 'login required' in text or 'sign in to confirm' in text or 'redirect to login' in text:
        return DownloadErrorCategory.AUTHENTICATION_REQUIRED
    if 'http error 401' in text or 'status code: 401' in text:
        return DownloadErrorCategory.HTTP_401
    if 'http error 403' in text or 'status code: 403' in text:
        return DownloadErrorCategory.HTTP_403
    if 'http error 404' in text or 'status code: 404' in text:
        return DownloadErrorCategory.HTTP_404
    if 'timed out' in text or 'timeout' in text or 'connection reset' in text or 'network is unreachable' in text:
        return DownloadErrorCategory.NETWORK_ERROR
    return DownloadErrorCategory.UNKNOWN
