from pathlib import Path


def platform_media_path(download_root: Path, platform: str, *subfolders: str, filename: str) -> Path:
    """Build a target file path under
    ``<download_root>/<platform>/<subfolders...>/<filename>``, creating the
    directory tree if it does not exist yet.

    One function so folder organization for a non-yt-dlp download engine
    stays centralized here instead of being rebuilt ad hoc per service, kept
    generic (platform and subfolders are plain strings, not tied to
    Instagram) so a future Phase 5 platform reuses it as-is.
    """
    directory = download_root.joinpath(platform, *subfolders)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / filename
