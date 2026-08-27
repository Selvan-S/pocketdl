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


class InstagramAuthRequiredError(RuntimeError):
    """Raised when a profile fetch could not complete in a way that, in
    current practice, means the profile needs an authenticated session
    cookie -- see GalleryDlService.list_profile_items and CLAUDE.md's
    "Important proven behavior" entry for how this was verified."""


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


@dataclass(frozen=True, slots=True)
class ProfileItemPreview:
    """One discoverable item as returned by profile discovery, before the
    user has chosen to add it to a Collection -- same shape as
    CollectionItem minus the fields that only exist once persisted
    (id, collection_id, added_at, downloaded_job_id)."""

    source_url: str
    content_type: str
    author_username: str | None
    caption: str | None
    thumbnail_url: str | None
    external_id: str | None
