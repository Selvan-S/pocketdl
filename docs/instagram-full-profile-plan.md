# Instagram Full-Profile Download — Implementation Plan (deferred)

Status: **design only, not started**.

Correction: this was originally sequenced behind Android mobile M1–M6.
docs/docs_POCKETDL_ROADMAP.md shows those milestones (and Phase 2/3
stabilization) are already done and verified on-device, so that gate no
longer applies. This plan is now the pilot implementation for
[Phase 5 — Multi-platform extraction](docs_POCKETDL_ROADMAP.md) in the main
roadmap; see that section for how it generalizes to other platforms.

## Goal

From one Instagram profile URL, let the user browse Posts / Reels / Stories /
Highlights, select individual items, save selections into a named
**playlist** (collection), and download a playlist on demand into an
organized folder tree.

## Why this needs new architecture, not a tweak

Today `DownloadJob` is 1 URL → 1 file, written flat into a single configured
download directory ([models.py](../services/api/app/domain/models.py),
[path_settings.py](../services/api/app/core/path_settings.py)). A profile
download is 1 URL → N discoverable items, browsed and selected before any
download happens. That's two new domain concepts (`CollectionItem`,
`Collection`), not a parameter on the existing job.

## Engine choice: add gallery-dl, don't force yt-dlp

yt-dlp's Instagram extractor is unreliable for Stories/Highlights; gallery-dl
has dedicated, better-maintained support for them via session cookies. This
mirrors the HLS lesson already in CLAUDE.md — use the tool built for the job
instead of fighting yt-dlp headers/impersonation. Add gallery-dl as a second
engine behind the same seam `YtDlpService` already occupies, not as a
special-cased branch inside it.

**Pre-req spike (do first, before writing any of the layers below):** verify
`gallery-dl` installs and runs under Termux/Android (pure-Python, but confirm
no native wheel surprises) — analogous to an M1-style runtime check.

## Layers

### Domain (`domain/`)
- `InstagramContentType` enum: `POST`, `CAROUSEL`, `REEL`, `STORY`, `HIGHLIGHT`.
- `DownloadEngine` enum on `DownloadJob`: `YT_DLP` | `GALLERY_DL` — orthogonal
  to `DownloadSourceType` (source_type is about *how the URL was obtained*;
  engine is about *which subprocess runs it*).
- `Collection` (id, name, created_at, updated_at).
- `CollectionItem` (id, collection_id, source_url, content_type,
  author_username, caption, thumbnail_url, external_id, added_at,
  downloaded_job_id: str | None).

### Application (`application/instagram/`, `application/collections/`)
- `ProfileDiscoveryService.list_items(profile_url, content_types, session)` —
  runs gallery-dl in metadata-only mode (`--simulate -j`), returns
  `CollectionItem`-shaped previews. Nothing persisted yet.
- `CollectionService` — create/rename/delete collection; add/remove items;
  `download_collection(collection_id, item_ids | None)` fans out into the
  *existing* download-creation use case (one call per item, engine=GALLERY_DL),
  reusing current queueing/concurrency rather than building a parallel path.

### Infrastructure (`infrastructure/gallery_dl.py`)
- Mirrors `YtDlpService`'s shape: `list_profile_items()`, `download()`,
  `_build_args()`, output-line parsing for progress, `version()` for
  `/system/status`. gallery-dl's progress output is coarser than yt-dlp's
  (mostly per-file completion, not byte-level percent) — note this as a known
  UX gap up front rather than discovering it late.
- Output path builder (new `core/media_paths.py`): given
  `(download_root, "instagram", username, content_type, filename)` returns
  the target path. One function, not per-site string-building scattered
  across services.

### Database (`infrastructure/sqlite.py`)
- New tables `collections`, `collection_items`, added with the same
  idempotent `CREATE TABLE IF NOT EXISTS` + `PRAGMA table_info` column-check
  pattern already used for `downloads`. No change to the `downloads` table
  except the new `engine` column (same migration pattern).

### API (`api/`)
- `POST /api/instagram/profile/preview` — profile URL + content-type filter
  → list of discoverable items (no download).
- `POST /api/collections`, `GET /api/collections`, `GET /api/collections/{id}`
- `POST /api/collections/{id}/items`, `DELETE /api/collections/{id}/items/{item_id}`
- `POST /api/collections/{id}/download` — download all or selected items.
- Session cookie: write-only endpoint, never echoed back by any GET, only a
  `configured: bool` flag.

### UI (`apps/web`)
- "Profile" view: URL input + content-type checkboxes → Preview → grid of
  selectable item cards, reusing the selectable-card pattern already shipped
  for HLS variant grouping → "Add selected to playlist" (existing or new).
- "Playlists" view: list collections with thumbnail/count, per-playlist
  "Download all" / "Download selected" / remove item / delete playlist.

## Folder organization

```
<download_root>/
├── Instagram/
│   └── <username>/
│       ├── Posts/
│       ├── Reels/
│       ├── Stories/
│       └── Highlights/<highlight_name>/
├── Standard/     ← existing yt-dlp/direct downloads, unchanged
└── Captured/     ← existing captured-source downloads, unchanged
```

Filename: `<username>_<yyyy-mm-dd>_<content-type>_<shortcode>.<ext>`, built
with the existing `sanitize_filename`.

## Security design for the session cookie (required before this ships)

Stories/Highlights need an authenticated session even for content the user
already has access to. Per CLAUDE.md's rule that credential-like data needs
an explicit design, not silent handling:

- User supplies their own exported cookie (paste or future extension
  helper). PocketDL never asks for or stores an Instagram password.
- Stored in a dedicated file separate from the main SQLite DB, restrictive
  file permissions, excluded from any backup/export tooling.
- Never included in API responses, logs, or `DownloadJob.error_details`.
  gallery-dl error output must be scrubbed for the cookie value before
  persisting, the same way `YtDlpService._context_args` already strips
  `Cookie`/`Authorization` from generic forwarded headers.

## Tests

- Domain: `Collection`/`CollectionItem` construction and invariants.
- Application: `CollectionService` add/remove/fan-out-download, mocking the
  download-creation use case.
- Infrastructure: `GalleryDlService` arg-building; regression test asserting
  cookie values never appear in captured error output.
- Migration idempotency: `initialize()` called twice against the same DB
  file must not error, matching the existing `downloads` table pattern.

## Explicit non-goals for this pass

- No clipboard monitoring, share-target, LAN access, storage dashboard, or
  download presets from the original brainstorm — those are unrelated
  scope and not sequenced here.
- No change to the `captured`/HLS path, duplicate-capture handling, or
  captured-size accuracy — orthogonal to this feature, tracked separately
  in the existing backlog.

## Sequencing

No longer blocked on mobile (M1–M6 done). Still design-only pending explicit
go-ahead to implement. When started: run the gallery-dl Termux spike first,
then build bottom-up (domain → application → infrastructure → API → UI),
each with its own tests, per the standard workflow.
