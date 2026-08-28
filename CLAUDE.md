# PocketDL — Claude Development Instructions

## Role
You are continuing development of PocketDL, a local/self-hosted downloader built for desktop development first and Android/Termux deployment later.

Treat this as a real software project. Maintainable architecture, tests, migrations, type safety, observability, and backwards compatibility matter more than quickly adding features.

## Current state
See docs/docs_POCKETDL_ROADMAP.md for the authoritative, actively-maintained
phase-by-phase status — the summary below is kept short and can lag it.
- Current desktop milestone: v0.2.2 core workflow is working.
- Browser capture works for HLS/direct-media sources.
- Captured downloads work.
- Normal yt-dlp downloads work.
- UI-configurable download location works.
- Collapsible capture sections/cards work.
- Duration metadata is generally accurate.
- Mobile/Termux deployment is done — M1-M6 all verified on-device (Termux
  runtime, backend, PWA, standard download, browser capture, Termux:Boot
  background service).
- Capture duplicates mostly fixed (signed-token normalization + HLS
  master/variant grouping); multi-CDN/hostname-rotation duplicates still
  open.
- Captured media size is partially reliable: direct-media Content-Length is
  trusted, and HLS/DASH variants get a labeled bandwidth x duration
  estimate; exact size for HLS with no declared bandwidth is still open.
- Format/quality selection (Phase 3) is done.
- Multi-platform extraction (beyond Instagram/yt-dlp) and broader product
  enhancements are active work per explicit request — see
  docs/instagram-full-profile-plan.md and the roadmap's Phase 5 and
  "Product-polish priority plan" sections. Sequence this behind the two
  narrow Phase 2 remnants above, not behind mobile (already done).
- Instagram pilot (Phase 5) is feature-complete on branch
  `feature/phase5-instagram-collections`, backend and UI both, now on
  instaloader as the live Instagram engine (swapped from gallery-dl
  mid-build for typed errors and real date-range filtering; gallery-dl
  kept, unremoved, reserved for the next Phase 5 platform). As of
  2026-08-28 it is also live-verified end to end against a real session
  cookie: authenticated profile preview returns real, correctly-mapped
  posts/carousels/reels, session verify works, and downloads write real
  files to the right per-profile folders with date-stamped names and
  caption sidecars. Stories and Highlights are the part still never
  exercised live — see the roadmap's Phase 5 "Round 7" and "What's left",
  where the open items are pagination (results truncate silently at 50)
  and UI responsiveness (replace the 2s poll with SSE).

## Live updates
The PWA does not poll. `GET /api/events` is a server-sent event stream
carrying one snapshot of downloads/status/captures/settings, and it only
emits when that snapshot actually changes. Waking is via
`ChangeNotifier` (`app/application/events.py`), fired by an HTTP middleware
after any successful non-GET request and by `QueueService` on download
progress, with a 15s heartbeat as backstop.

The notifier is deliberately **level-triggered** (a version counter, not a
bare broadcast): a subscriber spends most of its cycle building and writing
its snapshot rather than waiting, and an edge-triggered signal fired in that
window is lost. Read `notifier.version` *before* building a snapshot and
pass it to `wait(since=...)`.

Two constraints on anything added here. Nothing reachable by the stream, or
by a route the client polls as a fallback, may call out to a platform API --
see `tests/test_polling_does_not_hit_instagram.py`. And httpx's
`ASGITransport` buffers responses to completion, so SSE cannot be tested
through the `api_client` fixture; drive the route's `body_iterator` directly
as `tests/test_events_stream.py` does.

## Current architecture
```text
apps/
├── web/                    # React + TypeScript + Vite PWA
└── browser-extension/     # Chrome/Chromium Manifest V3 capture extension

services/
└── api/                   # FastAPI backend
    └── app/
        ├── api/           # HTTP routes/schemas
        ├── application/   # use cases/orchestration
        ├── domain/        # models, ports, enums, business rules
        ├── infrastructure/# SQLite, yt-dlp, FFmpeg, media probing
        └── core/          # config, logging, paths, platform helpers
```

Preferred dependency direction:

```text
API → Application → Domain
             ↑
       Infrastructure
```

Do not put business logic in API routes. Do not create giant utility/service files.

## Download architecture
There are two source types:

1. `standard`
   - Normal page/direct URL.
   - Uses yt-dlp for extraction and download.

2. `captured`
   - Browser-observed media URL + request context.
   - Used especially for HLS/DASH sites where browser requests work but yt-dlp cannot reproduce them.
   - Current captured-media path uses FFmpeg rather than forcing yt-dlp to reproduce browser networking.

Request context can include page URL, Referer, Origin, User-Agent, and approved non-sensitive headers.

Do not silently capture/store Cookie, Authorization, Proxy-Authorization, Set-Cookie, or equivalent credentials. A future browser-session feature must have an explicit security design.

## Important proven behavior
A difficult HLS site was experimentally verified as follows:
- Browser request: HTTP 200.
- Browser request replayed via PowerShell with browser-like context: HTTP 200.
- Chrome "Copy as cURL" replay: HTTP 200.
- yt-dlp normal request: HTTP 403.
- yt-dlp + curl_cffi/impersonation: still HTTP 403 in that case.

Therefore, do NOT waste time endlessly adding random yt-dlp headers or impersonation targets. Browser capture is the intended solution for this class of source.

Instagram profile discovery (gallery-dl engine, added for Phase 5) was experimentally verified as follows (2026-08-27, gallery-dl 1.32.9):
- `gallery-dl --resolve-json` against a real public Instagram profile URL, with no session cookie configured: returns `{"error": "NotFoundError", "message": "Requested user could not be found"}` — indistinguishable at a glance from a genuinely wrong username, not a normal HTTP 403/404.

Therefore every Instagram profile fetch needs an authenticated session cookie today, not just Stories/Highlights as originally assumed when instagram-full-profile-plan.md was written. `GalleryDlService.list_profile_items` classifies this specific error shape into `InstagramAuthRequiredError` so the API/UI can say "sign in required" instead of a confusing empty result. Full JSON field-mapping (username/caption/thumbnail extraction) is implemented from gallery-dl's source but not yet live-verified against real authenticated data — do this before trusting it in production, same "stop and diagnose" discipline as the mobile M-milestones.

Second live finding (2026-08-27, real pasted session cookie, real profile): gallery-dl returned `AbortExtraction: HTTP redirect to home page (https://www.instagram.com/)` even with a session cookie configured. Traced to `extractor/instagram.py`'s `request()` wrapper: any Instagram response whose final URL (after following redirects) is the bare homepage (a URL 24-28 chars long ending in `/`) raises this, distinct from its explicit "login"/"challenge" page detection. A valid-looking cookie does not guarantee gallery-dl's request succeeds -- a private profile the session's account doesn't follow, or Instagram fingerprinting gallery-dl's request as non-browser traffic, both produce this same bounce. Not yet root-caused to one specific cause. This result plus the original NotFoundError finding motivated evaluating instaloader as a purpose-built alternative for Instagram specifically -- see docs/docs_POCKETDL_ROADMAP.md Phase 5.

Third live finding (2026-08-28, first attempt with a real session cookie on the instaloader engine): a real profile preview (Reels selected, no date range) hung for 5+ minutes with the request "Stalled" in Chrome DevTools, and the 2s polling requests piling up behind it made the tab sluggish to scroll. Two compounding gaps, both since fixed in `InstaloaderService`: (1) instaloader's own defaults are `request_timeout=300s` per HTTP call with `max_connection_attempts=3` retries, and nothing wrapped the `asyncio.to_thread` calls in an outer timeout -- fixed with `request_timeout=20s`/`max_connection_attempts=2` plus `asyncio.wait_for` around every public method. (2) With no `since` date bound, pagination had nothing to stop it early, so an active profile's *entire* history got paged through, one request per page plus instaloader's own rate-limit courtesy delay between them -- fixed with a 50-item cap when no date range is given. Re-verified live afterward (fake cookie): same call now fails cleanly in 7s. See docs/docs_POCKETDL_ROADMAP.md Phase 5 "Round 4" for the full writeup.

Fourth live finding (2026-08-28, real session cookie, real public profile, instaloader 4.15.3) — this is the one that made an authenticated Instagram preview work for the first time, and it supersedes several earlier guesses above. Four bugs, all fixed in `InstaloaderService`:

1. **`context.update_cookies()` does not log instaloader in.** It only pushes cookies into the requests session: it leaves `context.username` unset — which is exactly what `context.is_logged_in` tests — and never sets the `X-CSRFToken` header. Every request therefore ran as an anonymous scraper that happened to carry a valid cookie. `Profile.get_posts()` branches on `is_logged_in`, and its anonymous branch got a **302 to the Instagram homepage**, surfaced as the misleading `ConnectionException: JSON Query to graphql/query: Expecting value: line 1 column 1 (char 0)`. Use `context.load_session(username, pairs)` instead, which sets both. Note this very likely also explains gallery-dl's "AbortExtraction: HTTP redirect to home page" in the second finding above — that was probably never about a bad cookie or a private profile.
2. **`Profile.get_reels()` costs one extra HTTP request per reel by design.** Its connection returns a media struct with no `taken_at`/`caption`/`user.username` (logged in or not), so instaloader's own `node_wrapper` does a `Post.from_shortcode()` refetch per reel — measured at 5 reels in 70s across 17 requests. Read reels as the `product_type == 'clips'` entries of the ordinary timeline instead: same posts, same order, complete metadata, 12 per request.
3. **The Instagram timeline is not strictly reverse-chronological.** Pinned posts are served at the head regardless of age (verified: three entries dated Aug 19/18/12 ahead of one dated Aug 27). Any "stop once older than `since`" early-exit must skip entries with a non-empty `timeline_pinned_user_ids` rather than treat them as the start of the older tail.
4. **Never pass an absolute path as instaloader's `download_post(target=...)`.** Substituted pattern values go through `_PostPathFormatter.sanitize_path()`, which on Windows rewrites `:` and `\` to lookalike characters *unconditionally* (the `sanitize_paths` constructor flag only forces that behaviour on non-Windows; it does not disable it). The absolute path became one literal mojibake directory under the working directory, `download_post()` still returned `True`, and the job was marked COMPLETED with no file — so Instagram downloads had never worked and said they had. Put the directory in `dirname_pattern` as a literal (patterns are not sanitized, only substituted values), and never report a download complete without confirming the file exists.

Preview, session verification and download are now all live-verified end to end against a real signed-in session; Stories and Highlights are not, and may carry a per-item cost like (2). See docs/docs_POCKETDL_ROADMAP.md Phase 5 "Round 6".

Fifth live finding (2026-08-28, user testing on a second real profile) — Round 6's reels change was verified only against one profile and generalized badly:

1. **The Instagram Reels tab is NOT a subset of the profile grid.** A reel can be published without showing on the grid. Measured on a real profile: 25 grid posts with **zero** `product_type == 'clips'` entries, alongside 15+ reels in the Reels tab, entirely disjoint. So "read reels by filtering the timeline" returns nothing at all for such an account. But `Profile.get_reels()` is still ~12s/reel (re-measured: 15 reels in 179s). The way out is neither: drive the reels connection through `instaloader.NodeIterator` with a `node_wrapper` that returns the raw media struct instead of refetching — one request per 12 reels.
2. **Instagram media pks encode a timestamp**: `(pk >> 23) + 1314220021721` ms. This is how a reel preview gets a date, since the reels connection omits `taken_at` and `caption` entirely. It is the upload-start time, so it runs early by 47s to ~31min — treat it as an approximation, and correct it at download time where `Post.from_shortcode` runs anyway.
3. **`post.owner_username` is not the profile you browsed.** Instagram credits a co-authored post to the collaborator, so keying a download folder on it scatters one profile's files across other users' folders. `CollectionItem.profile_username` records the profile the item was discovered under; `author_username` stays the true credit.
4. **instaloader's defaults were right and Round 6 overrode them.** `filename_pattern` defaults to `'{date_utc}_UTC'` and `post_metadata_txt_pattern` to `'{caption}'` (a `<basename>.txt` sidecar); `download_pic` already skips a file that exists. Round 6 removed the date and disabled the sidecar on the reasoning that captions live in the DB — wrong for an archive meant to be readable without PocketDL. Now `{date_utc:%Y-%m-%d_%H-%M-%S}_{shortcode}` (explicit spec because the literal default renders with colons, which the Windows sanitizer mangles) with the sidecar re-enabled and the JSON still off.

Rate-limit boundary: the PWA's 2s poll must never reach Instagram. It doesn't — the polled routes are local-only and `GET /api/instagram/session` deliberately skips verification — and `tests/test_polling_does_not_hit_instagram.py` now enforces that both ways. See docs/docs_POCKETDL_ROADMAP.md Phase 5 "Round 7".

## Current known bugs / backlog
1. Duplicate captured cards — mostly fixed (signed-token normalization,
   HLS master/variant grouping). Still open: multi-CDN/hostname-rotation
   duplicates for the same content.
2. Captured media size — partially fixed. Direct-media Content-Length is
   trusted; HLS/DASH variants get a labeled bandwidth x duration estimate.
   Still open: exact size when a playlist declares no bandwidth and ffprobe
   can't determine one; codecs/bitrate for non-master-playlist captures.
3. Very short/wrong captures — mostly done. `is_suspicious_capture` flags
   (not deletes) captures below a duration/size threshold, surfaced in both
   the PWA and extension. Still open: MIME/content-type signal, configurable
   thresholds.
4. Browser/mobile extension compatibility on Android — verified (M5, real
   device, Quetta browser).
5. Background service / Termux:Boot — implemented and verified (M6, real
   reboot).

## Mobile objective
Android runtime:

```text
Android
├── Termux
│   ├── Python
│   ├── Node.js/npm
│   ├── FFmpeg
│   ├── yt-dlp + curl_cffi
│   └── PocketDL backend
├── Android browser
│   └── PocketDL PWA
└── Chromium browser with extension support (for capture testing)
```

Mobile milestones:

- M1: Termux runtime installed and verified.
- M2: FastAPI backend runs on Android and Swagger works.
- M3: React PWA runs on Android and reaches backend.
- M4: Standard download works and writes to Android Downloads/PocketDL.
- M5: Browser capture works on a supported Android Chromium browser.
- M6: Termux:Boot/background startup.

Do these in order. Stop and diagnose at the first failed milestone.

## Git/repository rules
GitHub is becoming the canonical source of truth.

Before first push:
- Audit `.gitignore`.
- Ensure source files are tracked.
- Ensure `.venv`, `node_modules`, `dist`, `__pycache__`, `.pytest_cache`, databases, logs, and secrets are ignored.
- Run `git status`, `git diff --cached --name-only`, and `git ls-files` checks.

Do not replace the `.git` directory when updating the project.
Do not rely on ZIP replacement as the long-term workflow.

A previously bad `.gitignore` used a broad `*` pattern. This caused a real incident where `services/api/app/application/downloads/service.py` was missing from the Android checkout and caused:

`ModuleNotFoundError: No module named 'app.application.downloads.service'`

Therefore, whenever a source file is missing on another machine, inspect Git tracking first instead of manually patching the machine.

## Test credentials
`.secrets/` is gitignored as a whole directory. `.secrets/instagram_session.json`
holds a real browser session cookie export used to exercise the Instagram path
against live data. A session cookie is a full account credential, not a scoped
token: never commit it, never log it, never echo it into a response, a test
fixture, or a commit message. Drop a new platform's test session into the same
directory rather than adding another `.gitignore` rule.

## Dependency management
The backend declares:

```text
yt-dlp[default,curl-cffi]
```

in project dependency files. Do not add hidden manual dependency steps.

A fresh environment should work from the documented dependency installation commands.

## Coding standards
- Python: type hints, small functions, clear exceptions, pathlib, no hidden global state.
- TypeScript: strict typing, explicit interfaces/types, no `any` unless justified.
- React: feature-oriented components as the project grows; keep API calls outside presentational components.
- API: validate all input, return predictable error schemas.
- DB: all schema changes must have idempotent/automatic migration logic.
- Tests: add regression tests for every bug found.
- Never claim a build/test passed unless it actually ran.
- Do not silently change public API contracts.
- Do not hardcode hostnames, paths, user-agent strings, or site-specific rules unless the feature explicitly requires them.

## Security / legal boundary
PocketDL should handle media that the user is authorized to download. Do not implement DRM circumvention or bypass protected encrypted media. Do not collect browser credentials silently.

## Development workflow
For a major feature:
1. Inspect the current repository before proposing changes.
2. Write a short implementation plan.
3. Implement domain/application/infrastructure/API/UI layers separately.
4. Add regression tests.
5. Run backend tests and type checks.
6. Run frontend/extension builds when dependencies are available.
7. Update documentation/changelog.
8. Provide exact migration/run instructions.

For small bugs, prefer a minimal patch with a regression test.

## Immediate priority
Android/Termux deployment (M1-M6) and format/quality analysis (Phase 3) are
both done. Immediate priority is now, per explicit request:
1. Multi-platform extraction beyond Instagram (docs/docs_POCKETDL_ROADMAP.md
   Phase 5) and the product-polish enhancement plan in the same doc.
2. Keep that sequenced behind the two narrow Phase 2 remnants above
   (multi-CDN capture dedup, HLS size-estimate edge case) if they resurface
   as real user-reported bugs — they are not blocking, just unfinished.
Do not treat this section as license to restart the original v0.3
"format/quality analysis" scope — that specific phase is done; new feature
work should map to a phase in docs/docs_POCKETDL_ROADMAP.md.
