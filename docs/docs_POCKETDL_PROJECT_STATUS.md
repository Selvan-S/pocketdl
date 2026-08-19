# PocketDL — Project Status and Historical Context

## Product goal
PocketDL is a free, local/self-hosted downloader intended to provide the strongest practical download workflow available on Android without relying on paid download quotas. The design combines:

- yt-dlp for broad extractor support.
- FFmpeg for media processing and captured HLS/DASH downloads.
- A local FastAPI backend.
- A React/PWA UI.
- A browser extension for capturing media requests that generic extraction cannot reproduce.
- Termux as the Android runtime.

The product should feel closer to a combination of Video DownloadHelper + JDownloader, while remaining free and locally controlled.

## Why browser capture exists
A real-world HLS site was used as a diagnostic case. The browser successfully requested a signed HLS manifest with browser context (Origin, Referer, User-Agent and other browser-generated headers). PowerShell replay and Chrome Copy-as-cURL replay returned HTTP 200. yt-dlp, even with curl_cffi and impersonation, returned HTTP 403 for the same class of raw m3u8 request.

The conclusion was not to continue adding arbitrary yt-dlp flags. Instead, PocketDL captures the browser's successful media request context and downloads the captured media directly with the appropriate local media engine.

## Milestones completed

### v0.1.x — Local downloader foundation
- FastAPI backend.
- React/Vite frontend.
- SQLite queue/persistence.
- yt-dlp integration.
- FFmpeg integration.
- Custom filename support.
- Full yt-dlp error output and exit code.
- Basic download queue and status UI.
- Automatic runtime detection.

### v0.1.2 — Downloader engine foundation
- Request context model.
- Standard vs browser-aware download strategies.
- Error categorization.
- 403/HLS retry strategy experimentation.
- curl_cffi dependency.
- Database migrations.

### v0.2.0 — Browser capture
- Chrome/Chromium Manifest V3 extension.
- Observes HLS/DASH/direct media requests.
- Sends capture records to localhost FastAPI.
- Stores capture history in SQLite.
- Captured HLS/DASH download path via FFmpeg.
- React browser-captures view.

### v0.2.1 — Capture UX
- UI-configurable download directory.
- Direct download action from browser-capture workflow.
- Initial deduplication improvements.
- Capture source display improvements.

### v0.2.2 — Capture hardening
- Capture metadata enrichment.
- Duration and dimensions via ffprobe where possible.
- Best-effort media size.
- Collapsible capture cards/sections.
- Additional duplicate filtering and normalization.
- Short-media warning logic.
- Cleaner capture list UX.

## Current verified desktop workflow

```text
Chrome/Chromium
   ↓
PocketDL Capture extension
   ↓
FastAPI localhost
   ↓
SQLite capture record
   ↓
React UI
   ↓
Download captured source
   ↓
FFmpeg
   ↓
Configured download directory
```

Normal URL workflow remains:

```text
URL → FastAPI → Queue → yt-dlp → FFmpeg → Download
```

## Current tested desktop environment
- Python 3.13.14
- Node.js/npm installed
- FFmpeg 9.0
- yt-dlp 2026.07.04
- curl_cffi 0.15.0
- Windows development machine

## Current endpoint/runtime assumptions
- Backend: `http://127.0.0.1:8787`
- Swagger: `http://127.0.0.1:8787/docs`
- Web development server: `http://localhost:5173`
- Default Windows downloads path has been `C:\Users\ADMIN\Downloads\PocketDL` in testing.
- Android target path should be `/storage/emulated/0/Download/PocketDL` or a UI-configured equivalent.

## Current known issues
### Duplicate captures — improved
Signed tokens embedded in the media URL's path (not just the query string,
already handled) no longer create a new card per refresh; `normalize_media_url`
strips opaque token-like path segments conservatively before hashing.
Historical captures self-heal via the existing startup re-keying pass.

Still open: grouping a master manifest with its own quality-variant
sub-manifests into one card is a different problem (genuinely different
paths) and remains unaddressed, as does multi-CDN/hostname rotation for the
same content.

### Media size — improved
hls/dash captures no longer report the manifest text file's Content-Length as
the media's size (was showing e.g. "500 B" for a real multi-hundred-MB
stream); only a direct media capture's Content-Length is trusted. hls/dash
size is now left unknown ("—") rather than wrong, pending either ffprobe
enrichment succeeding or a future HLS segment-enumeration estimate — the
latter is unimplemented; exact size before download may be impossible for
some HLS/DASH sources without it.

### Short/wrong captures — improved
Suspicious captures are now marked, never deleted. `is_suspicious_capture` in
the domain layer flags short duration (any capture type), tiny direct-media
size, and segment/chunk-shaped URLs; the result is exposed as
`looks_suspicious` on the capture API and shown in both the PWA and the
extension popup.

The previous check was a hardcoded 10s threshold living in React that only
applied to `capture_type=media`, so an hls/dash capture that probed out to a
couple of seconds could never be flagged. Thresholds are module-level
constants (`SHORT_DURATION_SECONDS`, `TINY_MEDIA_SIZE_BYTES`) — tunable in one
place, but not yet user-configurable at runtime.

### Mobile browser capture
Verified working on-device using the Quetta browser (Chromium-based, supports
loading the extension). M5 complete.

### Background service — done
Implemented: `scripts/pocketdl-service.sh` (wake-lock, crash restart with
backoff), `scripts/pocketdl-stop.sh`, `scripts/pocketdl-status.sh`, and
`scripts/termux-boot-install.sh` to wire up the Termux:Boot hook. Verified
on-device with a real reboot — `pocketdl-status.sh` showed the service,
backend, and reachable API all up post-boot. One bug was found and fixed
along the way: the boot hook invokes `pocketdl-service.sh` through a symlink,
and `dirname "${BASH_SOURCE[0]}"` resolved against the symlink's own location
rather than its target, crash-looping the backend forever after every
reboot. Fixed with `readlink -f` (same pattern as the `pocketdl` launcher).

## Important repository incident
A previous broad `.gitignore` pattern (`*`) caused a source file to be absent from the Android checkout:

`services/api/app/application/downloads/service.py`

This produced:

`ModuleNotFoundError: No module named 'app.application.downloads.service'`

Before continuing Android development, audit Git tracking and ensure all `.py`, `.ts`, `.tsx`, config, test, and documentation files are tracked.

## Immediate next action
The Android baseline is complete: M1–M6 are all verified on-device, including
a real reboot triggering the Termux:Boot autostart hook, extension sideloading
on the Quetta browser, and a normal mobile download. Phase 2 (post-mobile
stabilization) is done to the point CLAUDE.md required before moving on:
path-embedded signed-token dedup, hls/dash size misattribution, and
suspicious/short-capture flagging (across all capture types, not just
`media`) are all fixed and merged (PR #9, `db92af2`). What's left in Phase 2
is explicitly lower-priority, not-yet-attempted breadth (master/variant
manifest grouping, multi-CDN dedup, HLS segment-enumeration size estimates,
user-configurable thresholds) — see `docs_POCKETDL_ROADMAP.md` Phase 2 for
the itemized list.

Phase 3 format/quality selection is also done: `/api/analyze`'s per-format
list (resolution, codec, fps, bitrate) is now wired into the UI — clicking a
format chip downloads that exact `format_id` instead of only a coarse
preset — and a 480p preset was added. This was a real gap: the component
built for it (`AnalyzeResult.tsx`) existed but was never imported anywhere,
and its own code comment still said "Format selection will be added in a
later release."

A from-scratch mobile setup guide (`docs/MOBILE_SETUP_GUIDE.md`) has also
been written and linked from README.md and `docs/termux.md`.

This work is on branch `feature/format-quality-analysis` (commits `47b470a`,
`a82912a`), pushed to origin, not yet merged — per the established workflow
the user opens the PR and merges via GitHub themselves, then this branch
should be deleted locally and remotely and `main` re-synced.

Nothing is currently blocking. The next reasonable increment is either: pick
up one of the remaining Phase 2 items above, or move into Phase 4 (extension
UX: capture quality ranking, popup download action, freshness/age) — CLAUDE.md's
"do not start v0.3 [format] work until mobile baseline is working" gate has
been satisfied, so there is no standing reason to avoid feature breadth
beyond normal judgment about what's highest-value next.
