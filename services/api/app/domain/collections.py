from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Platform(StrEnum):
    """Where a collection's items come from.

    INSTAGRAM: items discovered from a profile (downloaded via instaloader).
    GENERIC: a user-curated list of plain URLs downloaded via yt-dlp, the
    same as a paste-a-URL download -- the "playlist for normal downloads".
    """

    INSTAGRAM = 'instagram'
    GENERIC = 'generic'


# Top-level folder each platform's downloads are organised under, inside the
# download directory: <download dir>/<platform folder>/<...>. Generic playlists
# then nest a per-playlist folder beneath this (see CollectionService); the
# Instagram path nests per-profile.
PLATFORM_FOLDERS: dict[Platform, str] = {
    Platform.INSTAGRAM: 'Instagram',
    Platform.GENERIC: 'Web',
}


class InstagramContentType(StrEnum):
    POST = 'post'
    CAROUSEL = 'carousel'
    REEL = 'reel'
    STORY = 'story'
    HIGHLIGHT = 'highlight'


class InstagramAuthRequiredError(RuntimeError):
    """Raised when a profile fetch could not complete in a way that, in
    current practice, means the profile needs an authenticated session
    cookie -- see InstaloaderService.list_profile_items and CLAUDE.md's
    "Important proven behavior" entries for how this was verified."""


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
    posted_at: datetime | None = None
    downloaded_job_id: str | None = None
    # The profile this item was discovered under, which is not always the
    # post's own owner: Instagram attributes a co-authored post to the
    # collaborator, so author_username alone scattered one profile's
    # download across other people's folders. Downloads and per-profile
    # grouping key on this; author_username stays the true credit.
    profile_username: str | None = None


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
    posted_at: datetime | None = None
    # The profile this item was discovered under, which is not always the
    # post's own owner: Instagram attributes a co-authored post to the
    # collaborator, so author_username alone scattered one profile's
    # download across other people's folders. Downloads and per-profile
    # grouping key on this; author_username stays the true credit.
    profile_username: str | None = None
