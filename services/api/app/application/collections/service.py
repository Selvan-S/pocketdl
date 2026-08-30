import uuid
from datetime import datetime, timezone

from ...domain.collections import Collection, CollectionItem, Platform, ProfileItemPreview
from ...domain.models import DownloadEngine, DownloadJob, RequestContext
from ...domain.ports import CollectionRepository
from ..downloads.service import QueueService


class CollectionService:
    """Create/manage named collections ("playlists") of discovered items and
    fan a download out into the existing download-creation use case -- one
    QueueService.create() call per item, engine=INSTALOADER -- rather than
    building a parallel download path."""

    def __init__(self, repository: CollectionRepository, queue: QueueService) -> None:
        self.repository = repository
        self.queue = queue

    async def create_collection(self, platform: Platform, name: str) -> Collection:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError('Collection name cannot be empty.')
        now = datetime.now(timezone.utc)
        collection = Collection(id=uuid.uuid4().hex, platform=platform, name=cleaned[:200], created_at=now, updated_at=now)
        return await self.repository.add_collection(collection)

    async def list_collections(self) -> list[Collection]:
        return await self.repository.list_collections()

    async def get_collection(self, collection_id: str) -> Collection | None:
        return await self.repository.get_collection(collection_id)

    async def rename_collection(self, collection_id: str, name: str) -> Collection:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError('Collection name cannot be empty.')
        renamed = await self.repository.rename_collection(collection_id, cleaned[:200])
        if renamed is None:
            raise ValueError('Collection not found.')
        return renamed

    async def delete_collection(self, collection_id: str) -> None:
        await self.repository.delete_collection(collection_id)

    async def list_items(self, collection_id: str) -> list[CollectionItem]:
        return await self.repository.list_items(collection_id)

    async def list_items_page(
        self, collection_id: str, *, state: str = 'all', limit: int = 50, offset: int = 0,
    ) -> list[CollectionItem]:
        return await self.repository.list_items_page(collection_id, state=state, limit=limit, offset=offset)

    async def collection_counts(self) -> dict[str, tuple[int, int]]:
        return await self.repository.collection_counts()

    async def add_item(self, collection_id: str, preview: ProfileItemPreview) -> CollectionItem:
        collection = await self.repository.get_collection(collection_id)
        if collection is None:
            raise ValueError('Collection not found.')
        item = CollectionItem(
            id=uuid.uuid4().hex,
            collection_id=collection_id,
            source_url=preview.source_url,
            content_type=preview.content_type,
            author_username=preview.author_username,
            profile_username=preview.profile_username,
            caption=preview.caption,
            thumbnail_url=preview.thumbnail_url,
            external_id=preview.external_id,
            added_at=datetime.now(timezone.utc),
            posted_at=preview.posted_at,
        )
        return await self.repository.add_item(item)

    async def add_items(self, collection_id: str, previews: list[ProfileItemPreview]) -> tuple[int, int]:
        """Add many previews at once, returning (added, already_present).

        Adding is idempotent at the repository level (one row per piece of
        content per collection), so this reports how many were genuinely new
        rather than silently claiming to have added items the playlist
        already held -- which is what "Added 50" followed by an unchanged
        list looked like before.
        """
        existing = {
            item.external_id or item.source_url
            for item in await self.repository.list_items(collection_id)
        }
        added = 0
        already_present = 0
        for preview in previews:
            if (preview.external_id or preview.source_url) in existing:
                already_present += 1
                continue
            await self.add_item(collection_id, preview)
            existing.add(preview.external_id or preview.source_url)
            added += 1
        return added, already_present

    async def remove_item(self, collection_id: str, item_id: str) -> None:
        await self.repository.remove_item(collection_id, item_id)

    @staticmethod
    def _default_title(item: CollectionItem) -> str:
        parts = [item.author_username, item.content_type, item.external_id]
        return '_'.join(part for part in parts if part) or f'instagram-{item.id[:8]}'

    async def download_collection(
        self,
        collection_id: str,
        item_ids: list[str] | None,
        *,
        request_context: RequestContext,
        preset: str = 'best',
        concurrent_fragments: int = 8,
        retries: int = 10,
    ) -> list[DownloadJob]:
        collection = await self.repository.get_collection(collection_id)
        if collection is None:
            raise ValueError('Collection not found.')

        items = await self.repository.list_items(collection_id)
        if item_ids is not None:
            wanted = set(item_ids)
            items = [item for item in items if item.id in wanted]
        # Skip items that already completed a download rather than silently
        # re-queueing them every time "Download all" is pressed again.
        items = [item for item in items if item.downloaded_job_id is None]

        jobs: list[DownloadJob] = []
        for item in items:
            job = await self.queue.create(
                url=item.source_url,
                filename=None,
                preset=preset,
                concurrent_fragments=concurrent_fragments,
                retries=retries,
                use_aria2=False,
                request_context=request_context,
                title=self._default_title(item),
                engine=DownloadEngine.INSTALOADER,
                collection_item_id=item.id,
            )
            jobs.append(job)
        return jobs
