"""Shared in-memory doubles for capture tests."""

# The repository double defines a `list` method, which shadows the builtin
# for every annotation after it in the class body.
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.captures import CaptureVariant, CapturedSource
from app.infrastructure.media_probe import MediaProbeResult


class FakeMediaProbe:
    async def probe(self, url, context) -> MediaProbeResult:
        return MediaProbeResult(size_bytes=12_345, duration_seconds=12.5, width=1280, height=720)


class FakeManifestFetcher:
    """Serves canned playlist text, or raises, without any network access."""

    def __init__(self, playlists: dict[str, str] | None = None, error: Exception | None = None) -> None:
        self.playlists = playlists or {}
        self.error = error
        self.requested: list[str] = []

    async def fetch(self, url: str, context) -> str:
        self.requested.append(url)
        if self.error is not None:
            raise self.error
        return self.playlists[url]


class InMemoryCaptureRepository:
    def __init__(self) -> None:
        self.items: dict[str, CapturedSource] = {}
        self.variants: dict[str, list[CaptureVariant]] = {}

    async def add(self, capture: CapturedSource) -> CapturedSource:
        self.items[capture.id] = capture
        return capture

    async def get(self, capture_id: str) -> CapturedSource | None:
        return self.items.get(capture_id)

    async def list(self, limit: int = 50) -> list[CapturedSource]:
        return list(self.items.values())[:limit]

    async def find_by_source_key(self, source_key: str) -> CapturedSource | None:
        return next((item for item in self.items.values() if item.source_key == source_key), None)

    async def update(self, capture: CapturedSource) -> CapturedSource:
        self.items[capture.id] = capture
        return capture

    async def mark_downloaded(self, capture_id: str) -> CapturedSource | None:
        item = self.items.get(capture_id)
        if item:
            item.used_at = datetime.now(timezone.utc)
        return item

    async def delete(self, capture_id: str) -> None:
        self.items.pop(capture_id, None)
        self.variants.pop(capture_id, None)

    async def replace_variants(self, capture_id: str, variants: list[CaptureVariant]) -> None:
        self.variants[capture_id] = list(variants)
        # Mirrors the SQLite repository, which removes any capture card that
        # duplicates one of the master's variants.
        keys = {variant.variant_key for variant in variants}
        for item in list(self.items.values()):
            if item.id != capture_id and item.source_key in keys:
                self.items.pop(item.id, None)

    async def list_variants(self, capture_id: str) -> list[CaptureVariant]:
        return list(self.variants.get(capture_id, []))

    async def variants_for(self, capture_ids: list[str]) -> dict[str, list[CaptureVariant]]:
        return {capture_id: list(self.variants.get(capture_id, [])) for capture_id in capture_ids}

    async def find_by_variant_key(self, variant_key: str) -> CapturedSource | None:
        for capture_id, variants in self.variants.items():
            if any(variant.variant_key == variant_key for variant in variants):
                return self.items.get(capture_id)
        return None
