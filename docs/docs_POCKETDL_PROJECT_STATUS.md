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

### Short/wrong captures
Players can issue tiny media requests that are not the actual video. These should be filtered or clearly marked, without deleting all short legitimate media.

### Mobile browser capture
Verified working on-device using the Quetta browser (Chromium-based, supports
loading the extension). M5 complete.

### Background service
Implemented: `scripts/pocketdl-service.sh` (wake-lock, crash restart with
backoff), `scripts/pocketdl-stop.sh`, `scripts/pocketdl-status.sh`, and
`scripts/termux-boot-install.sh` to wire up the Termux:Boot hook. The
supervisor's restart/backoff/signal-handling logic is verified functionally.
Termux:Boot itself is a separate app (F-Droid) the user installs manually;
the actual reboot-triggers-autostart path has not yet been verified on-device.

## Important repository incident
A previous broad `.gitignore` pattern (`*`) caused a source file to be absent from the Android checkout:

`services/api/app/application/downloads/service.py`

This produced:

`ModuleNotFoundError: No module named 'app.application.downloads.service'`

Before continuing Android development, audit Git tracking and ensure all `.py`, `.ts`, `.tsx`, config, test, and documentation files are tracked.

## Immediate next action
The Android baseline is complete: M1–M6 are all verified on-device, including
a real reboot triggering the Termux:Boot autostart hook. Now in Phase 2
(stabilization after mobile): duplicate-capture and media-size fixes are
underway (path-embedded signed tokens, hls/dash size misattribution — both
fixed; master/variant grouping, multi-CDN dedup, and HLS segment-enumeration
size estimates remain open). Short-media filtering is untouched. Do not
proceed into v0.3 richer format/quality analysis until Phase 2 is stable.
