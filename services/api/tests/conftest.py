"""Shared fixtures.

`api_client` is the project's first HTTP-level harness: it builds the real
FastAPI app against a throwaway database and download directory, so a test
can assert on what a route actually does rather than on the use case behind
it. Kept here rather than in support.py because it needs pytest fixtures
(tmp_path/monkeypatch), which support.py's plain doubles do not.
"""

import importlib

import httpx2
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def api_client(tmp_path, monkeypatch):
    database_path = tmp_path / 'state' / 'pocketdl.db'
    database_path.parent.mkdir(parents=True, exist_ok=True)
    # Settings has no env_prefix, so these are the bare field names.
    monkeypatch.setenv('DATABASE_PATH', str(database_path))
    monkeypatch.setenv('DOWNLOAD_DIRECTORY', str(tmp_path / 'downloads'))

    import app.core.config as config

    # get_settings is lru_cached and app.main reads it at import time, so both
    # the cache and the module have to be rebuilt for the env above to apply.
    config.get_settings.cache_clear()
    import app.main

    main = importlib.reload(app.main)

    try:
        async with main.app.router.lifespan_context(main.app):
            transport = httpx2.ASGITransport(app=main.app)
            async with httpx2.AsyncClient(transport=transport, base_url='http://testserver') as client:
                # Handy for tests that need to seed state the app will read
                # (e.g. writing a session cookie to the throwaway database).
                client.app_settings = main.app.state.settings
                yield client
    finally:
        config.get_settings.cache_clear()


@pytest.fixture
def anyio_backend():
    return 'asyncio'
