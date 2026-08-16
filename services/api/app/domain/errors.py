from enum import StrEnum


class DownloadErrorCategory(StrEnum):
    HTTP_401 = 'http_401'
    HTTP_403 = 'http_403'
    HTTP_404 = 'http_404'
    GEO_RESTRICTION = 'geo_restriction'
    DRM = 'drm'
    UNSUPPORTED_URL = 'unsupported_url'
    FORMAT_ERROR = 'format_error'
    FFMPEG_ERROR = 'ffmpeg_error'
    NETWORK_ERROR = 'network_error'
    AUTHENTICATION_REQUIRED = 'authentication_required'
    RATE_LIMITED = 'rate_limited'
    CANCELLED = 'cancelled'
    UNKNOWN = 'unknown'
