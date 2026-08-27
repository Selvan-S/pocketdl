# PocketDL — Product Roadmap

## Roadmap philosophy
Build in vertical, testable milestones. Stabilize the current workflow before adding breadth. Prefer generic infrastructure over site-specific hacks.

---

# Phase 0 — Desktop foundation ✅

Completed:
- React/Vite PWA.
- FastAPI backend.
- SQLite persistence.
- yt-dlp integration.
- FFmpeg integration.
- Custom filenames.
- Queue.
- Detailed errors.
- Download directory settings.
- Browser capture extension.
- Captured HLS/DASH download path.

---

# Phase 1 — Android/Termux deployment — done (M1–M6 all verified on-device)

## M1 — Termux runtime — done
Verified via `scripts/termux-doctor.sh` on-device: Termux, git, Python,
Node.js/npm, FFmpeg/ffprobe, and Android storage access all passed.

## M2 — Backend on Android — done
`termux-doctor.sh --all` verified the venv, yt-dlp, curl_cffi and the rest of
the dependency set; `/api/health` and `/api/system/status` confirmed live.

## M3 — PWA on Android — done
The backend serves the built PWA directly at `/` (no separate Vite dev
server needed); frontend → backend communication verified.

## M4 — Normal mobile download — done
Verified on-device: a standard download completed successfully.

## M5 — Browser capture on Android — done
Verified on-device with the Quetta browser: extension loads, captures
HLS/DASH, and the captured download completes.

## M6 — Background service — done
Verified on-device with a real reboot: `pocketdl-status.sh` showed the
service, backend, and reachable API all up post-boot via the Termux:Boot
hook. One bug surfaced and fixed along the way: the hook invokes
`pocketdl-service.sh` through a symlink
(`~/.termux/boot/pocketdl-start -> pocketdl-service.sh`), and the script's
`dirname "${BASH_SOURCE[0]}"` resolved against the symlink's own location
rather than its target, landing outside the repository and crash-looping the
backend forever after every reboot. Fixed with `readlink -f`, the same
pattern already used by the `pocketdl` launcher symlink. `pocketdl-service.sh`
holds `termux-wake-lock` and restarts the backend with backoff on crash or
exit; `pocketdl-status.sh` is the health/startup indicator;
`pocketdl-stop.sh` stops it cleanly.

---

# Phase 2 — Stabilization after mobile ← CURRENT

## Download robustness — done (this increment)
Two user-reported real-site failures, both fixed with regression tests:
- Captured HLS download failing with `FFmpeg exited with code 183` /
  `is not in allowed_segment_extensions`. The site serves its `.m3u8`
  playlist and segments with `.txt`/`.css` extensions (an
  ad-blocker/bandwidth-saver evasion trick common on some streaming sites);
  ffmpeg's hls demuxer rejects segment URLs whose extension isn't on its
  small built-in allowlist unless told otherwise. Fixed by adding
  `-allowed_extensions ALL` to both the ffmpeg download command and the
  ffprobe duration-probe call in `CapturedMediaService`.
- Standard (yt-dlp) download of a direct `.mp4` URL failing with
  `[SSL: CERTIFICATE_VERIFY_FAILED] ... unable to get local issuer
  certificate`. The site sends an incomplete certificate chain (missing
  intermediate) that browsers silently repair via AIA chasing but Python's
  `ssl` module does not attempt. Fixed with a narrow, visible one-shot
  retry: a new `SSL_CERTIFICATE_ERROR` category triggers a single retry of
  the same attempt with `--no-check-certificate` (recorded in the attempt
  label and `job.error_details`, not a silent blanket setting).

This also answered a standing open question: whether "support for HTTP or
other streams beyond HLS" was a missing roadmap item. It isn't — the
standard path (yt-dlp's generic extractor) already handles direct HTTP
files and hundreds of other site extractors, and the captured path
(ffmpeg) already treats any captured URL generically regardless of
container/protocol (HLS, DASH, or a direct file). The two failures above
were robustness edge cases in that existing coverage, not gaps in
stream-type support — there is no separate "add HTTP support" work item.

## Capture deduplication — master/variant grouping done
The last structural duplicate source is fixed. An HLS master playlist
advertises the same video at several qualities, each as its own sub-playlist
URL; a player fetches the master and then one or more variants, so browser
capture saw each as a separate media request and made a card per quality.
URL normalization could never fix this — the variants' paths differ
genuinely, not by a rotating token — so the master playlist is now parsed
(`app/domain/manifests.py`) and its variants recorded against the capture in
a new `capture_variants` table. Capturing a variant returns the master's
card; a variant that already had a card is absorbed when the master is
parsed; historical duplicates self-heal on startup. The variants also became
the quality selector this item and Phase 4's "capture quality ranking" both
needed — see Phase 4.

Scope note: HLS only. A DASH `.mpd` already carries every representation in
the single file the player fetches, so it never produced duplicate cards.

Still open, not attempted:
- Multi-CDN / hostname rotation for the same content.
- host/path normalization beyond token stripping, codec information, a
  broader stable-identity hash.

## Capture deduplication — earlier increment (signed path tokens)
Fixed: signed tokens embedded in the media URL's *path* (not just the query
string, which was already handled) no longer create a new card on every
refresh. `normalize_media_url` replaces path segments that look like opaque,
request-scoped tokens (UUIDs, long hex, long mixed alphanumeric) with a
placeholder before hashing, conservatively — numeric IDs and short/word-like
segments are left alone so distinct videos and quality variants stay
distinguishable. "When a signed URL changes: update existing capture with
newest URL/context, do not create an additional card" — done for this case.
Historical captures self-heal via the existing startup re-keying pass.

Test with players that refresh manifests frequently.

## Media metadata — partially done
Fixed: hls/dash captures no longer report the manifest text file's
Content-Length as the media's size (was showing e.g. "500 B" for a real
multi-hundred-MB stream). Only a direct media capture's Content-Length is
trusted as a real size now; hls/dash size is left unknown until ffprobe
enrichment determines it, which is honest rather than wrong.

Also done, via variant grouping: a per-quality size estimate
(bandwidth x duration) and the estimate-vs-exact distinction this section
asked for. It is named an estimate the whole way through
(`estimated_size_bytes`, rendered `~1.2 GB est.`) and never written into
`size_bytes`, where it would be indistinguishable from a measured
Content-Length. Codecs, frame rate and bitrate are now carried per variant
too.

Still open, not attempted:
- HLS segment enumeration for a size estimate when the playlist declares no
  bandwidth and ffprobe cannot determine one.
- Codecs/frame rate/bitrate for a capture that is *not* a master playlist —
  those still come only from ffprobe.

## Short-media filtering — mostly done
Implemented as a flag, never a hard delete, per this section's original
requirement. `is_suspicious_capture` in the domain layer is now the single
source of truth, surfaced as `looks_suspicious` on `CaptureResponse` and
rendered in both the PWA and the extension popup.

Signals implemented:
- duration < threshold (`SHORT_DURATION_SECONDS`, 10s) — now applied to
  **every** capture type. Previously this was a hardcoded client-side check in
  React that only ran for `capture_type=media`, so an hls/dash capture that
  probed out to ~2s (the exact case CLAUDE.md's backlog cites) could never be
  flagged at all.
- tiny content length (`TINY_MEDIA_SIZE_BYTES`, 50KB) — direct media only,
  since hls/dash `size_bytes` is deliberately unset (it would be the
  manifest's size, not the media's).
- URL looks like segment/chunk — backend-side backstop mirroring the
  extension's own `isLikelyMediaSegment` filter, so captures predating that
  filter or from any non-extension client are still caught.

Still open, not attempted:
- MIME/content-type fragment detection as a distinct signal (the URL-shape
  check already covers the common cases in practice).
- manifest/direct-media relationship as a signal.
- Making the thresholds user-configurable at runtime; they are currently
  module-level constants, tunable in one place but not exposed in settings.

---

# Phase 3 — Smarter analysis and format selection

## Analyze URL
Create a first-class `Analyze` workflow:

```text
Paste URL
  ↓
Analyze
  ↓
Title
Duration
Thumbnail
Uploader/source
Media type
Formats
```

## Format model — done
`/api/analyze` already returned resolution, codec, container, audio codec,
bitrate, frame rate, estimated size and protocol per format
(`services/api/app/domain/analyzer.py`); `fps` and bitrate were captured but
never rendered in the UI. Now shown in the format chip.

## User selection — done
Best/1080p/720p/audio-only presets already existed; added 480p. The bigger
gap was that `/api/analyze`'s per-format list was display-only — its own code
comment said "Format selection will be added in a later release", and
`AnalyzeResult.tsx` (the component built for this) was never imported
anywhere. Wired it into `DownloadForm.tsx`: clicking a video format chip
selects that exact `format_id` for download, overriding the coarse preset
(`-f "<format_id>+bestaudio/best"`). Audio-only formats stay behind the
existing "Audio only" preset rather than being individually selectable, to
avoid double-merging audio. Backend: `format_id` threaded through
`QueueService` → `Downloader` protocol → `YtDlpService`, validated at the API
boundary (schema field_validator) and defensively re-checked in
`application/downloads/strategy.py:format_args` (now a pure, unit-tested
function; previously a private, untested `YtDlpService` method).

## Filename policy
Priority:
1. User-entered name.
2. Extracted title.
3. Page title.
4. Safe fallback.

Never use raw signed m3u8 query strings in filenames.

---

# Phase 4 — Browser experience

## Extension improvements — partially done
Done (popup polish, no backend changes needed beyond one existing endpoint
reused):
- Show duration/size/resolution in popup — already implemented
  (`metadataText()` in `popup.ts`) before this pass; not a gap after all.
- Popup Download action — already implemented before this pass.
- Clear/ignore capture actions — Remove button added, reuses the existing
  `DELETE /api/captures/{id}` endpoint the PWA already used.
- Open in PocketDL action — Open button opens the PWA at `?capture=<id>`;
  the PWA scrolls to, expands, and briefly highlights that card.
- Capture freshness/age — relative age ("5m ago") replaces the absolute
  timestamp, exact time kept as a tooltip.
- Better status/connection handling — `background.ts` now checks
  `response.ok` when posting a capture (previously any non-throwing fetch,
  including 4xx/5xx, counted as success) and records the outcome; the popup
  shows a dismissible banner on the most recent failure instead of the
  capture silently vanishing with zero signal.
- Live download progress in the popup — not originally on this list, added
  on request. `capture_id` was already threaded through the whole
  download-creation call chain but never persisted or used;
  `CaptureRepository.mark_downloaded()` existed but nothing ever called it.
  Both fixed: `DownloadJob` now carries `capture_id`, and `QueueService`
  calls `mark_downloaded` when a captured download reaches `COMPLETED`. The
  popup polls `/api/downloads` alongside `/api/captures` and replaces the
  Download button with live progress, then "Downloaded ✓ + Open folder" on
  success (reuses the existing open-download-directory endpoint) or the
  error + a retry option on failure.
- Copy-link button on each card — `navigator.clipboard.writeText`, no new
  permission needed.

Capture quality ranking — done. Variant chips in the popup (and the PWA)
select a specific quality, with a per-quality estimated size; the previously
deferred domain model, API shape change and UI all landed together. See
Phase 2's master/variant grouping entry.

Two things found while building it:
- The captured-download `preset` field was accepted by the API and then
  ignored — the ffmpeg path never read it — so the PWA card presented a
  quality selector that did nothing. Replaced with the real variant chips.
- The popup rebuilt its list on every 5s poll, closing any expanded card.
  Open state is now preserved, without which the quality picker is unusable.

Still open, not attempted:
- Better capture deduplication beyond what Phase 2 covers (multi-CDN /
  hostname rotation).

## Browser session support — future, explicit feature
Only if required by real sites.
Potential support:
- controlled cookie/session handoff.
- secure local storage.
- expiration/clearing.
- explicit opt-in.

Never silently export browser cookies.

---

# Phase 5 — Multi-platform extraction

Builds on the two-engine (yt-dlp + gallery-dl) router already designed for
Instagram — see
[instagram-full-profile-plan.md](instagram-full-profile-plan.md). That plan
is the pilot for this phase; once its router lands, adding a platform is
"add a routing-table entry and verify engine coverage," not new
architecture. Instagram is the first platform, not a special case.

## Router design
- `Platform` enum + a routing table mapping (platform, content type) →
  engine (`YT_DLP` | `GALLERY_DL`), centralized in one module (e.g.
  `application/platforms/router.py`) rather than branching per-service.
- URL → platform detection by hostname pattern lives in the router only —
  no duplicate hostname checks across API/application/infrastructure layers.
- `Collection`/`CollectionItem` (the playlist concept from the Instagram
  plan) is platform-agnostic from the start via a `platform` field, so the
  same save-a-selection-then-download-it flow works for every platform
  instead of rebuilding it per site.

## Candidate platforms and engine

| Platform | Recommended engine | Notes |
|---|---|---|
| YouTube | yt-dlp | already working today |
| TikTok | yt-dlp | public videos; no profile/story concept to mirror Instagram's |
| Reddit | gallery-dl (images/galleries) + yt-dlp (`v.redd.it` video) | one platform, two engines depending on content type |
| Twitter/X | yt-dlp (video) + gallery-dl (images/threads) | most content now sits behind a login wall; expect frequent breakage, budget for it |
| Facebook | yt-dlp | public videos/reels only — profile-wide scraping is high ToS-risk, not recommended |
| Pinterest | gallery-dl | boards/pins |
| Tumblr | gallery-dl | |
| Vimeo | yt-dlp | only videos the user can already access (public or password known to them) |
| Twitch | yt-dlp | VODs/clips only — never live streams or paid/subscriber-only content |
| SoundCloud | yt-dlp | audio |

## Explicit non-goals
- No DRM'd streaming services (Netflix, Disney+, Spotify, Prime Video, etc.)
  — hard boundary, already stated in this doc's non-goals and in CLAUDE.md.
- No mass/bulk account scraping. This stays a personal downloader for
  content the user already has legitimate access to, not scraping-as-a-service.
- Facebook and X full-profile scraping stays out of scope given ToS
  hostility and login-wall coverage — single post/video only, until proven
  otherwise on a case-by-case basis.

## Sequencing
Validate the router against a second, mostly-open platform (Reddit or
TikTok) right after Instagram, before assuming it generalizes cleanly to
the harder, login-walled ones (X, Facebook). Each new platform still needs
its own small discovery spike (does gallery-dl/yt-dlp actually cover the
content types we want, under Termux) before committing to full layer-by-layer
implementation, same as the Instagram plan's gallery-dl-on-Termux spike.

## Instagram pilot — implementation progress (branch feature/phase5-instagram-collections)
Bottom-up build in progress per instagram-full-profile-plan.md's sequencing.
Done so far, each landed as its own commit:
- gallery-dl added as a dependency; desktop install spike passed (pure
  Python, no native wheel step). Termux install still unverified.
- Domain: `Collection`/`CollectionItem`/`ProfileItemPreview`
  (`domain/collections.py`), `Platform` enum (Instagram only for now, field
  present on Collection from the start), `DownloadEngine` on `DownloadJob`
  orthogonal to `source_type`.
- Persistence: `collections`/`collection_items` tables
  (`infrastructure/collections.py`), `downloads.engine` column migration.
- Security: session cookie storage (`core/session_store.py`) — user-pasted
  browser Cookie header only, never a password, written as a Netscape
  cookies.txt gallery-dl's `--cookies` flag reads, in its own gitignored
  file separate from the main DB, never echoed back by any endpoint, with a
  scrub helper for defense-in-depth against the value leaking into engine
  error output.
- Infrastructure: `GalleryDlService` (`infrastructure/gallery_dl.py`) —
  `list_profile_items()` metadata-only discovery via `--resolve-json`,
  parsing gallery-dl's stable Message-tuple wire protocol; `download()`
  building `-D`/`-f` args via `media_paths.py`'s
  `<root>/<platform>/<subfolders>/<filename>` layout, scrubbing the session
  cookie out of captured output before it can reach `job.error_details`.
- Engine dispatch: `DownloadJob.collection_item_id` threaded through
  `QueueService`/`YtDlpService` exactly like the existing `capture_id`
  (`_run()` calls `CollectionRepository.mark_item_downloaded` on
  completion); `YtDlpService.download()` dispatches to `GalleryDlService`
  when `job.engine is DownloadEngine.GALLERY_DL`, checked before the
  existing `source_type` branch.
- Application: `ProfileDiscoveryService` (validates the profile URL, thin
  wrapper over discovery) and `CollectionService` (create/rename/delete a
  collection, add/remove items, `download_collection` fans out into
  `QueueService.create()` — one call per item, engine=GALLERY_DL — skipping
  items that already completed).
- API: `POST /api/instagram/profile/preview`,
  `GET/POST/DELETE /api/instagram/session`,
  `GET/POST /api/collections`, `GET/PUT/DELETE /api/collections/{id}`,
  `GET/POST /api/collections/{id}/items`,
  `DELETE /api/collections/{id}/items/{item_id}`,
  `POST /api/collections/{id}/download`.
- UI: `InstagramPanel.tsx` — session-cookie control, profile browser
  (URL + content-type checkboxes → preview grid → add selection to a
  playlist), playlists view (download all/selected, remove item, delete
  playlist), as a new collapsible section on the main page.

Important finding while building discovery (see CLAUDE.md's "Important
proven behavior"): an unauthenticated profile fetch fails with a
`NotFoundError` that looks like a wrong username, not a real 404 — every
profile fetch needs the session cookie today, not just Stories/Highlights.
`list_profile_items` now raises a distinct `InstagramAuthRequiredError` for
this, mapped to HTTP 401. Verified live end-to-end in a real browser
(Playwright driving the Vite dev server against the real FastAPI backend,
no chromium-cli available in this sandbox so Playwright was installed
directly): session save/clear, a real profile-preview call correctly
hitting the 401 case and surfacing it as a clean message, and a real
`download_collection` fan-out that queued and ran an actual gallery-dl job
end to end, visible in the Download Queue, failing cleanly with
`[instagram][error] HTTP redirect to login page` for the fake test
credentials used. `classify_download_error` now recognizes that message as
`authentication_required` rather than `unknown`.

Field-mapping accuracy for a *successful* authenticated preview
(username/caption/thumbnail extraction from gallery-dl's real JSON output)
is implemented from gallery-dl's own source but **still not live-verified
against a real signed-in session** — no login credentials were available
during this pass, only the well-proven unauthenticated failure path.
Verify with a real session cookie before trusting the preview output in
production; this is the one remaining gate before calling the pilot done,
same "stop and diagnose" discipline as an unverified mobile milestone.

Also still open, lower priority: gallery-dl under Termux is unverified
(only the desktop pip-install spike ran); a preview call against an
unauthenticated or slow-to-fail profile can take up to the 120s
subprocess timeout before surfacing an error, which is a UX rough edge
worth revisiting once real usage data exists.

---

# Phase 6 — Download manager maturity

Features to consider:
- real-time progress via WebSocket/SSE instead of polling.
- pause/resume where technically supported.
- retry policies.
- queue priorities.
- concurrent download limits.
- fragment concurrency.
- speed/ETA graphs or richer progress.
- download history.
- failed-download retry.
- partial-file recovery.
- duplicate file handling.
- conflict strategies: overwrite/rename/skip.
- background operation.

---

# Phase 7 — Mobile productization

- Termux startup service.
- Android share target.
- Mobile-friendly capture workflow.
- Persistent service health.
- PWA installation.
- Optional native Android shell if useful.
- Battery/background behavior documentation.
- Android storage permission UX.
- Optional notification for download completion.

Potential native shell options can be evaluated later. Do not introduce Flutter/React Native/Kotlin unless the PWA + Termux architecture proves insufficient.

## Planned: split the single-page UI into routed pages with a bottom nav
Not started. Raised 2026-08-27 while testing the Instagram pilot on a phone
screen: `App.tsx` is one long scroll (paste-URL, browser capture,
Instagram, downloads, settings) that keeps growing with every feature —
already a real usability problem on mobile, and will only get worse as
Phase 5 adds more platforms and Phase 6 adds more download-manager UI.

Plan:
- Bottom tab bar (mobile-standard pattern): Home (paste-URL + downloads),
  Capture, Instagram/Platforms, Settings, or similar grouping — exact tab
  split TBD.
- `react-router-dom` is already an installed dependency
  (`apps/web/package.json`) and currently completely unused — this is
  what it's for.
- Main design question to resolve when this is picked up: `App.tsx`'s 2s
  polling refresh (`refresh()` in the `useEffect`) currently drives
  downloads/captures/settings/system-status from one place. Splitting
  into routes means deciding what each page polls for itself vs. what
  stays lifted to a shared layout (the connection pill in the topbar
  needs system status regardless of which page is active).
- Scope as its own branch/session, same bottom-up-but-UI-only shape as
  other UI work here: doesn't need new backend endpoints, this is a
  frontend-only restructuring.

---

# Phase 8 — Reliability and security

- Threat model for localhost APIs.
- Strict origin checks.
- Extension authentication handshake.
- Request payload size limits.
- Header allowlists.
- URL validation/SSRF protections.
- Safe filesystem path handling.
- Filename sanitization.
- Download directory sandboxing.
- Rate/concurrency controls.
- Structured logs without sensitive URL/token leakage.
- Dependency vulnerability scanning.
- Reproducible builds where practical.

---

# Phase 9 — v1.0

Release criteria:
- Desktop stable.
- Android stable.
- Browser capture stable on major supported browser targets.
- Normal yt-dlp flow stable.
- Captured HLS/DASH flow stable.
- Database migrations tested.
- Comprehensive regression suite.
- Clean GitHub repository.
- Documented installation for Windows and Termux.
- Documented limitations (DRM, restricted browser pages, unsupported media technologies, etc.).

---

# Future idea backlog

These are ideas, not commitments:

- Multiple browser profiles.
- Import/export settings.
- Saved download presets.
- Playlist/batch capture.
- Watch-folder automation.
- Download scheduling.
- Bandwidth limits.
- Per-site request presets.
- Automatic title cleanup.
- Subtitle/language selector.
- Audio track selector.
- Chapter support.
- Thumbnail preview.
- Duplicate-file hashing.
- Optional aria2 integration for supported direct downloads.
- Plugin/adapter layer for site-specific extraction where browser capture is insufficient.
- Local API for other apps.
- Android share-sheet integration.
- Browser extension context menu: "Send to PocketDL".
- Local network control (disabled by default; explicit opt-in with authentication).

---

# Product-polish priority plan

The "make it easy for the user, full-fledged product" ask is mostly already
captured across Phase 6 (download manager maturity), Phase 7 (mobile
productization) and the future idea backlog above. This section prioritizes
those into tiers and adds a few items not previously listed, so the backlog
isn't just an unordered wishlist.

## Near-term (right after the Phase 5 pilot platform lands)
- Android share target + browser extension "Send to PocketDL" context menu
  (Phase 7 backlog) — the single biggest mobile usability win, and it's a
  PWA manifest feature (`share_target`), not a native app.
- Notification on download/collection completion (Phase 7 backlog).
- Batch URL input — paste N URLs, one per line, queue all at once. Not
  previously listed; pairs naturally with the Phase 5 collection/playlist
  work (add several profile items, or several plain URLs, in one action).
- Failed-download retry + partial-file resume (Phase 6) — yt-dlp already
  supports `--continue`; today a failed job means a full re-download.
- WebSocket/SSE progress instead of polling (Phase 6) — lower battery/CPU
  cost on Termux matters more than on desktop.

## Medium-term
- Storage/disk-usage dashboard with a per-platform breakdown and cleanup
  suggestions. Not previously listed — becomes more important once
  multi-platform full-profile downloads (Phase 5) can fill phone storage
  quickly.
- Wi-Fi-only download gating. Not previously listed — guards mobile data
  usage; checkable client-side via the Network Information API before a
  job is submitted, no backend change needed.
- Import/export settings and history (Phase 6 backlog) — cheap insurance
  before a phone reset or reinstall.
- Saved per-platform download presets (Phase 6 backlog) — e.g. "Instagram
  Reel -> best MP4" as one tap instead of reselecting quality every time.
- Rate-limit-aware retry messaging — surface "rate limited by <platform>,
  retrying in Xm" instead of an opaque failure. Grows more important as
  Phase 5 adds platforms that rate-limit harder than YouTube does.

## Later, needs its own security pass first
- Local network access beyond localhost (backlog item; this doc's
  non-goals already require it disabled by default with explicit opt-in +
  authentication) — needed for a "queue from my laptop, download happens
  on the phone" workflow, but land it after Phase 8 (reliability and
  security), not before.
- Watch-folder automation, download scheduling, bandwidth limits (backlog).

## New, not previously listed
- First-run setup wizard: pick the download directory, confirm storage
  permission, walk through installing the capture extension. Reduces the
  "why isn't this working" support burden for a self-hosted tool where
  there's no one else to ask.
- Update-available banner extending the existing yt-dlp version-check
  mechanism (`YtDlpService.versions` / `update_yt_dlp`) to gallery-dl once
  it ships, so both engines share one update path instead of yt-dlp being
  the only one that's easy to keep current.

---

# Non-goals / boundaries

Do not attempt to:
- bypass DRM.
- decrypt protected streams.
- silently collect browser credentials.
- expose the downloader to the LAN by default.
- embed paid downloader limits or adware.
- hardcode one site's quirks into the generic downloader core.
