from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .settings_store import load_download_directory


def _default_download_directory() -> Path:
    return Path('/sdcard/Download/PocketDL') if os.environ.get('PREFIX', '').startswith('/data/data/com.termux') else Path.home() / 'Downloads' / 'PocketDL'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'PocketDL'
    app_version: str = '0.2.4'
    host: str = '127.0.0.1'
    port: int = 8787
    database_path: Path = Field(default=Path.home() / '.pocketdl' / 'pocketdl.db')
    download_directory: Path = Field(default_factory=_default_download_directory)
    max_concurrent_downloads: int = 2
    default_concurrent_fragments: int = 8
    default_retries: int = 10
    yt_dlp_update_timeout_seconds: int = 300

    @property
    def database_parent(self) -> Path:
        return self.database_path.parent

    @property
    def default_download_directory(self) -> Path:
        return _default_download_directory()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.database_parent.mkdir(parents=True, exist_ok=True)
    persisted = load_download_directory(settings.database_path)
    if persisted is not None:
        try:
            persisted.mkdir(parents=True, exist_ok=True)
            if persisted.is_dir():
                settings.download_directory = persisted
        except OSError:
            pass
    settings.download_directory.mkdir(parents=True, exist_ok=True)
    return settings
