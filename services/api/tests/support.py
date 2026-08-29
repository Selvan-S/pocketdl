"""Shared in-memory doubles for capture tests."""

# The repository double defines a `list` method, which shadows the builtin
# for every annotation after it in the class body.
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.captures import CaptureVariant, CapturedSource
from app.domain.collections import Collection, CollectionItem
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


class InMemoryCollectionRepository:
    def __init__(self) -> None:
        self.collections: dict[str, Collection] = {}
        self.items: dict[str, CollectionItem] = {}

    async def add_collection(self, collection: Collection) -> Collection:
        self.collections[collection.id] = collection
        return collection

    async def get_collection(self, collection_id: str) -> Collection | None:
        return self.collections.get(collection_id)

    async def list_collections(self) -> list[Collection]:
        return list(self.collections.values())

    async def rename_collection(self, collection_id: str, name: str) -> Collection | None:
        collection = self.collections.get(collection_id)
        if collection is None:
            return None
        collection.name = name
        collection.updated_at = datetime.now(timezone.utc)
        return collection

    async def delete_collection(self, collection_id: str) -> None:
        self.collections.pop(collection_id, None)
        for item_id in [item_id for item_id, item in self.items.items() if item.collection_id == collection_id]:
            self.items.pop(item_id, None)

    async def add_item(self, item: CollectionItem) -> CollectionItem:
        self.items[item.id] = item
        return item

    async def get_item(self, item_id: str) -> CollectionItem | None:
        return self.items.get(item_id)

    async def list_items(self, collection_id: str) -> list[CollectionItem]:
        return [item for item in self.items.values() if item.collection_id == collection_id]

    async def list_items_page(
        self, collection_id: str, *, state: str = 'all', limit: int = 50, offset: int = 0,
    ) -> list[CollectionItem]:
        items = sorted(
            (item for item in self.items.values() if item.collection_id == collection_id),
            key=lambda item: item.added_at,
        )
        if state == 'pending':
            items = [item for item in items if item.downloaded_job_id is None]
        elif state == 'downloaded':
            items = [item for item in items if item.downloaded_job_id is not None]
        return items[offset:offset + limit]

    async def collection_counts(self) -> dict[str, tuple[int, int]]:
        counts: dict[str, tuple[int, int]] = {}
        for item in self.items.values():
            total, downloaded = counts.get(item.collection_id, (0, 0))
            counts[item.collection_id] = (total + 1, downloaded + (item.downloaded_job_id is not None))
        return counts

    async def remove_item(self, collection_id: str, item_id: str) -> None:
        item = self.items.get(item_id)
        if item and item.collection_id == collection_id:
            self.items.pop(item_id, None)

    async def mark_item_downloaded(self, item_id: str, job_id: str) -> None:
        item = self.items.get(item_id)
        if item:
            item.downloaded_job_id = job_id
