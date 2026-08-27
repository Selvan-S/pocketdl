from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Platform(StrEnum):
    """Site a collection's items were discovered from.

    A single member today (Instagram is the Phase 5 pilot), but the field
    exists on Collection/CollectionItem from the start so the same
    save-a-selection-then-download-it flow generalizes to the next platform
    without a schema change -- see docs/docs_POCKETDL_ROADMAP.md Phase 5.
    """

    INSTAGRAM = 'instagram'


class InstagramContentType(StrEnum):
    POST = 'post'
    CAROUSEL = 'carousel'
    REEL = 'reel'
    STORY = 'story'
    HIGHLIGHT = 'highlight'


@dataclass(slots=True)
class Collection:
    """A named, user-curated set of items to download together (a
    "playlist"), e.g. a subset of one Instagram profile's posts/reels."""

    id: str
    platform: Platform
    name: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class CollectionItem:
    """One discoverable piece of content added to a Collection.

    content_type is stored as the plain string value of a platform-specific
    enum (InstagramContentType today) rather than typed to that enum here,
    so this dataclass stays platform-agnostic; the owning application
    service is responsible for producing/validating a value that is
    meaningful for the item's platform.
    """

    id: str
    collection_id: str
    source_url: str
    content_type: str
    author_username: str | None
    caption: str | None
    thumbnail_url: str | None
    external_id: str | None
    added_at: datetime
    downloaded_job_id: str | None = None
