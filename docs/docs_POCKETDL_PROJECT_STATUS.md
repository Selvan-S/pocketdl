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
### Duplicate captures — master/variant grouping done
An HLS master playlist and its quality sub-playlists are now one card. The
master is fetched with the captured browser context and parsed
(`app/domain/manifests.py`); its variants are stored in a new
`capture_variants` table and keyed the way an incoming capture of that URL
would be, so capturing a variant returns the master's card rather than
creating a second one. A variant that already had a card is absorbed when
the master is parsed, and historical duplicates self-heal on startup.
Verified live against a local playlist server: master + two variant captures
produced one card with two selectable qualities.

HLS only, by design — a DASH `.mpd` carries every representation in the one
file the player fetches, so it never produced duplicate cards.

Still open: multi-CDN / hostname rotation for the same content.

### Duplicate captures — earlier increment (signed path tokens)
Signed tokens embedded in the media URL's path (not just the query string,
already handled) no longer create a new card per refresh; `normalize_media_url`
strips opaque token-like path segments conservatively before hashing.
Historical captures self-heal via the existing startup re-keying pass.

### Media size — improved
hls/dash captures no longer report the manifest text file's Content-Length as
the media's size (was showing e.g. "500 B" for a real multi-hundred-MB
stream); only a direct media capture's Content-Length is trusted. hls/dash
size is left unknown ("—") rather than wrong when nothing better is known.
A master playlist's variants now also carry a per-quality *estimate*
(bandwidth x duration), named as an estimate all the way to the UI and never
written into `size_bytes`. Still unimplemented: a segment-enumeration
estimate for playlists that declare no bandwidth.

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

## Capture quality selection — done (this increment)
Branch `feature/master-variant-grouping`, version 0.2.4. Closes the
repeatedly-deferred master/variant grouping item that Phase 2 and Phase 4
both depended on: duplicate quality cards are gone, and the variants became
the quality selector the extension popup was missing. Chips in both the PWA
and the popup; `POST /api/captures/{id}/download` takes a `variant_index`.

Design decisions worth keeping:
- The playlist is fetched with the standard library, not a new HTTP
  dependency — it is a small text file, and the backend's declared
  dependency set should keep working from the documented install commands.
- A chosen quality downloads that variant's own sub-playlist. When the
  master lists audio as a separate `#EXT-X-MEDIA` rendition, the variant
  carries video only, so the audio playlist is muxed in as a second ffmpeg
  input. This was preferred over `-map p:N` against the master because the
  argument construction is explicit and unit-testable rather than dependent
  on ffmpeg's internal program numbering.
- Variants are stored against the master, not as capture rows of their own,
  so they can never become cards.

Three unrelated defects surfaced and were fixed on the same branch:
- The captured-download `preset` field was accepted and then ignored (the
  ffmpeg path never read it), so the PWA showed a dead quality control.
- The extension popup closed every expanded card on its 5s poll.
- A downloader that raised instead of returning a failed job left the job at
  `running` forever. Found by running the new download path on a machine
  where ffmpeg is not on PATH.

Not verified: ffmpeg is not on PATH on the development machine, so the
two-input (video + separate audio) command has argument-level unit coverage
only and no captured download was executed end-to-end. Treat the first real
download of a separate-audio variant as the actual verification. Everything
else — grouping, absorption, the API shape, variant-index download routing,
the 422 on an unknown index, and the now-visible job failure — was verified
live against a local playlist server.

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

That work merged via PR #10 (`6388bb5`); `main` is synced and the merged
branch (plus the earlier `fix/capture-dedup-and-size`, PR #9) deleted
locally. Remote copies of both were left for the user to clean up via
GitHub at their convenience.

## Phase 4 extension popup polish — done (this increment)
Branch `feature/extension-ux-phase4`. Prompted by two user reports that
turned out to be two different things:
- The PWA's "Connecting…" pill never flipped to connected despite the API
  working — a real bug (`App.tsx`'s `Promise.all` over four endpoints let
  one failure block the pill forever), fixed with `Promise.allSettled`
  (commit `06c077b`). A missing `/manifest.webmanifest` route was fixed in
  the same commit.
- "No format selection in the extension" — not a regression. PR #10 only
  ever touched the PWA (`apps/web`); the extension popup has never had
  format selection, and the closest analog for captures (grouping a master
  manifest with its quality-variant sub-manifests) is real, unimplemented
  work that needs its own domain-model/API design, not a quick fix. The
  user chose to defer that and scope this branch to the smaller, genuinely
  missing Phase 4 popup items instead (commit `f4a492f`): remove/dismiss,
  an Open-in-PocketDL action with PWA-side scroll-to-highlight, relative
  capture age, and a dismissible offline banner (the popup's background
  capture-post fetch never checked `response.ok`, so a backend-rejected or
  offline capture vanished with zero signal — now recorded and surfaced).
  See `docs_POCKETDL_ROADMAP.md` Phase 4 for the itemized done/open split.

That merged as PR #11 (`780d863`). On-device testing on the user's Android
Termux setup then surfaced two further real bugs, fixed on
`fix/connection-staleness-and-versioning` (PR #12, `2f8126d`):
- The extension popup was silently running stale cached code after
  reinstalling from the packaged zip — root cause: `manifest.json`'s version
  had sat at `0.2.2` through several real feature merges, giving Quetta no
  signal that anything changed. Bumped to `0.2.3` everywhere it's tracked
  (extension manifest, both `package.json`s, backend `pyproject.toml`/
  `config.py`) and added a version label to the popup itself
  (`chrome.runtime.getManifest().version`) so this is visually checkable
  going forward, not just inferred.
- The PWA's connection pill, once connected, never reflected a *later* real
  outage — `status` was only ever set on success and nothing cleared it.
  Fixed with a separate `connected` flag driven by the current poll's
  success specifically.
- The actual root cause of the on-device "stuck connecting" symptom:
  `/api/system/status` re-ran three subprocess version checks (yt-dlp,
  ffmpeg, aria2c; 10s timeout each) on *every* 2s poll. Fine on desktop;
  on backgrounded Android/Termux, CPU throttling for new-process spawns
  made this take up to ~30s per request, and since polling never waits for
  the previous call to finish, overlapping slow requests piled up.
  Diagnosed via `time curl` direct from Termux (fast, foreground) vs. the
  same call through the browser (slow, Termux backgrounded) vs. Swagger
  (confirmed ~30s). Fixed by caching the version check after the first
  call — these never change mid-session except via the explicit "Update
  yt-dlp" action. Verified live: 2.38s cold, 0.08s cached after.

Then, on request, live download progress in the extension popup
(`feature/capture-download-progress`, PR #13, `9ef3db4`). Investigation
found `capture_id` was already threaded through the entire
download-creation call chain (`routes.py` → `QueueService.create` →
`YtDlpService.download`) but never persisted or used —
`CaptureRepository.mark_downloaded()` existed but nothing ever called it,
so there was no way to look up a capture's resulting download or its live
state at all. Fixed: `DownloadJob` now carries `capture_id` (idempotent
migration, same pattern as the download table's other added columns);
`QueueService` calls `mark_downloaded` when a captured download reaches
`COMPLETED` (not on failure/cancellation). Side effect: the PWA's
`status-badge.used` styling, present in the CSS but dead until now since
`status` never left `'captured'`, is correct for free. The popup now polls
`/api/downloads` alongside `/api/captures` and shows live progress →
"Downloaded ✓ + Open folder" (reuses the existing open-download-directory
endpoint) → or the error with a retry option on failure. A Copy-link
button was added alongside Open/Remove. 3 new backend unit tests cover the
completion/failure/no-capture-id orchestration paths (a real subprocess
download couldn't be exercised end-to-end in the sandboxed dev environment
used to build this — `asyncio.create_subprocess_exec` fails there for
reasons confirmed unrelated to and pre-existing this change; Termux uses
standard Linux subprocess spawning so this shouldn't apply there, but treat
first real on-device test as the actual verification, not this note).

All three branches (PR #11, #12, #13) are merged to `main` and confirmed
working on-device by the user ("the website is working"). Local and remote
tracking of the merged branches is cleaned up.

## Deferred / not yet done
- **Boot-service re-verification after this round's changes.** Running
  `termux-boot-install.sh` printed "Termux:Boot app: not detected" — this
  is a known best-effort-only check (Android package-visibility
  restrictions on newer versions), not a real failure signal, and M6 was
  already verified working via a real reboot before this round's changes.
  User deferred re-verifying with a fresh reboot or the no-reboot
  `bash ~/.termux/boot/pocketdl-start &` test; do that opportunistically,
  not urgently.
- **Capture quality ranking / master-variant manifest grouping** — done, see
  "Capture quality selection" above. What remains from that area is the
  first real on-device download of a variant whose audio is a separate
  `#EXT-X-MEDIA` rendition: the two-input ffmpeg command has argument-level
  unit coverage only, because ffmpeg is not on PATH on the development
  machine.
- Remaining Phase 2 breadth items (multi-CDN/hostname dedup, HLS
  segment-enumeration size estimates for playlists that declare no
  bandwidth, user-configurable suspicious-capture thresholds) — see
  `docs_POCKETDL_ROADMAP.md` Phase 2, still untouched.

Nothing is currently blocking. The next reasonable increment is whichever of
the above the user prioritizes, or Phase 5 download-manager breadth (SSE
progress instead of polling, retry policies, concurrency limits, history);
no standing reason to avoid feature breadth beyond normal judgment about
what is highest-value next.

## Download robustness fixes — done (this increment)
User hit two real-site failures while testing and asked, separately,
whether broader "HTTP/any other stream" support was even on the roadmap.
Answer: it already is — the standard path (yt-dlp) already covers direct
HTTP files via its generic extractor, and the captured path (ffmpeg)
already treats any captured URL generically regardless of container. Both
failures were robustness edge cases in that existing coverage, not missing
stream-type support; see `docs_POCKETDL_ROADMAP.md` Phase 2 for the fuller
writeup. Fixed, with regression tests (`test_ffmpeg_args.py`,
`test_yt_dlp_args.py`, additions to `test_download_errors.py`; suite now
62 tests, all passing):
- FFmpeg captured downloads failing with exit 183
  (`is not in allowed_segment_extensions`) on sites that disguise HLS
  playlists/segments as `.txt`/`.css`. Added `-allowed_extensions ALL` to
  the ffmpeg and ffprobe invocations in `CapturedMediaService`
  (`services/api/app/infrastructure/ffmpeg.py`).
- Standard yt-dlp downloads failing with
  `[SSL: CERTIFICATE_VERIFY_FAILED] ... unable to get local issuer
  certificate` on sites serving an incomplete cert chain that browsers
  silently repair via AIA chasing but Python's `ssl` module does not. Added
  a new `SSL_CERTIFICATE_ERROR` category and a one-shot
  `--no-check-certificate` retry, visible in the attempt label and
  `job.error_details` rather than a silent default
  (`services/api/app/application/downloads/strategy.py`,
  `services/api/app/infrastructure/yt_dlp.py`).

Not yet done: neither fix has been verified against the actual reported
URLs on the user's machine (both were fixed from the yt-dlp/ffmpeg error
text and known ffmpeg/OpenSSL behavior, not by re-running the failing
download) — treat as the real verification step, not this note.
