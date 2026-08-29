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

**Status: backend and UI both feature-complete on the instaloader engine.
One gate remains, and it needs real credentials, not more code — see
"What's left" below.**

### Round 1 — gallery-dl pilot (superseded as Instagram's live engine, kept as infrastructure)
Built the full vertical slice bottom-up (domain -> DB -> infra -> app -> API
-> UI) on gallery-dl as the second engine: `Collection`/`CollectionItem`/
`ProfileItemPreview` domain models, `collections`/`collection_items` tables,
session cookie storage (`core/session_store.py`, Netscape cookies.txt,
never a password, never echoed back), `GalleryDlService` (profile discovery
via `--resolve-json`, download via `-D`/`-f`), engine dispatch through
`QueueService`/`YtDlpService`, `ProfileDiscoveryService`/`CollectionService`,
the `/api/instagram/*` and `/api/collections*` routes, and
`InstagramPanel.tsx` (session control, profile browser, playlists view).
Verified live in a real browser end to end, including a real queued
download job.

Two live findings on gallery-dl drove the round 2 swap below: an
unauthenticated profile fetch returns a `NotFoundError` indistinguishable
from "wrong username" (not a real 404), and — with an actual pasted session
cookie — a real profile returned `AbortExtraction: HTTP redirect to home
page`, which could mean a private/unfollowed profile *or* Instagram
fingerprinting non-browser request traffic, with gallery-dl giving no way
to tell which apart. Both are recorded in CLAUDE.md's "Important proven
behavior".

gallery-dl itself is **not removed** — `GalleryDlService` stays constructed
and tested in `main.py`, just not routed to by anything live. Phase 5's own
design reserves it as the generic engine for the *next* platform
(Reddit/TikTok), so this isn't dead code, it's ahead-of-need infrastructure.

### Round 2 — instaloader swap (this session, in response to explicit user request for date-range filtering)
Requested mid-session: real date-range filtering for profile browsing, plus
the home-page-redirect finding above made a purpose-built Instagram tool
worth evaluating over a generic multi-site one. Spiked instaloader the same
way gallery-dl was spiked (pip install + API inspection before committing),
confirmed it gives typed exceptions (`ProfileNotExistsException`,
`LoginRequiredException`, `PrivateProfileNotFollowedException`,
`TooManyRequestsException`) instead of gallery-dl's ambiguous free text,
`Post.date_utc` for real dates, and `context.test_login()` to verify a
pasted session cookie immediately.

Landed, each its own commit:
- `instaloader` dependency (pyproject.toml/requirements.txt/termux-doctor.sh).
- `DownloadEngine.INSTALOADER` (third engine value; docstring corrected --
  instaloader runs in-process via `asyncio.to_thread`, not as a subprocess
  like the other two).
- `posted_at` on `CollectionItem`/`ProfileItemPreview`, migrated onto
  `collection_items` (ALTER-TABLE-if-missing, since real local DBs from
  testing this branch already existed without it).
- `load_cookie_pairs()` in `session_store.py` — reads the same stored
  Netscape file back as a plain dict for `instaloader.context.update_cookies()`,
  one storage format shared with gallery-dl's file-path consumption.
- `InstaloaderService` (`infrastructure/instaloader_service.py`) --
  `list_profile_items()` with since/until early-stopping the
  reverse-chronological feed (posts/reels only; stories/highlights aren't
  meaningfully date-bounded), `download()` re-fetching a post fresh by
  shortcode at download time (`Post.from_shortcode`) since collection items
  are persisted and may be downloaded much later, `test_session()` wrapping
  `test_login()`. Stories/highlights have no stable re-fetchable identifier
  (Instagram expires stories, commonly ~24h) -- `download()` falls back to
  a direct authenticated fetch of the exact media URL captured at preview
  time for those, documented as a known limitation, not silently pretended
  to be as durable as a permanent post.
- `YtDlpService` dispatches `DownloadEngine.INSTALOADER` jobs to
  `InstaloaderService`, same pattern as the `GALLERY_DL` branch.
  `ProfileDiscoveryService`/`CollectionService`/`main.py` all now point at
  `InstaloaderService` instead of `GalleryDlService` for Instagram.
- API: `InstagramProfilePreviewRequest` gained `posted_after`/
  `posted_before`; `ProfileItemPreviewResponse`/`CollectionItemResponse`
  gained `posted_at`; `InstagramSessionStatusResponse` gained
  `verified_username`, populated automatically right after `POST
  .../session` saves and on demand via new `POST .../session/verify`,
  both calling `test_login()` -- **live-verified against real Instagram
  servers** with a fake cookie: got a real 401 rate-limit response back
  from `instagram.com/graphql/query`, handled cleanly, returned
  `verified_username: null` rather than crashing. This is the concrete
  fix for the session confusion hit earlier in this session.

### Round 3 — UI wiring (this session)
Closed the UI gap Round 2 left open, no backend changes needed:
- `apps/web/src/types/api.ts` / `api/client.ts`: `posted_at` added to
  `ProfileItemPreview`/`CollectionItem`; `posted_after`/`posted_before`
  added to `InstagramProfilePreviewRequest`; `verified_username` added to
  `InstagramSessionStatus`; `api.verifyInstagramSession()` calls
  `POST /api/instagram/session/verify`.
- `InstagramPanel.tsx`: `ProfileBrowser` gained `<input type="date">`
  "Posted after"/"Posted before" fields, converted to UTC day-boundary ISO
  strings before the request (`dateInputToRangeStart`/`dateInputToRangeEnd`
  -- date-only strings would parse as tz-naive on the backend and crash
  comparing against instaloader's tz-aware `post_date`, see
  `InstaloaderService._collect_posts`) and client-side validated
  (after > before rejected before the request). `formatPostedAt` renders
  `posted_at` on both profile-preview cards and saved-playlist items.
  `SessionControl` now shows "Verified as @username" /
  "Session configured (unverified)" instead of a flat configured/not
  badge, plus an explicit "Verify" button calling the new endpoint --
  replaces the old guesswork about whether a pasted cookie actually works.
- Live-verified in a real headless browser (Playwright, installed fresh
  into the scratchpad since it wasn't already on this machine; a
  dev-server pair on 8787/5173): expanded the Instagram section, saved a
  cookie and watched the badge go to "Session Configured (Unverified)"
  with Verify/Replace/Clear all present, clicked Verify and got a clean
  re-check (no crash), filled both date inputs and submitted -- request
  carried `posted_after`/`posted_before` as UTC ISO strings and the
  backend responded with a typed `ValueError` ("profile does not exist"),
  not a stack trace. Also smoke-tested the same four endpoints directly
  with curl beforehand for the same result. This is exactly as far as
  verification can go without a real login: with a fake cookie,
  `verified_username` correctly stays `null` and nothing crashes -- the
  actual "does a real signed-in preview return real items" check below is
  still open because it was never reachable, not because it was skipped.

### Round 4 — fixed a real 5+ minute hang, found via the first real-credential attempt
The first actual test with a real session cookie against a real profile
(Reels selected, no date range set) hung for 5+ minutes -- Chrome DevTools
showed the request "Stalled", and the polling requests piling up behind it
made the whole tab sluggish to scroll. Root-caused to two compounding gaps:

1. `_build_loader()` never overrode instaloader's own defaults --
   `request_timeout=300s` *per HTTP call*, `max_connection_attempts=3` on
   top -- and none of `list_profile_items`/`download`/`test_session`
   wrapped their `asyncio.to_thread(...)` call in any outer timeout (the
   gallery-dl round's equivalent code had an explicit
   `asyncio.wait_for(..., timeout=120)`; this one didn't). Now:
   `request_timeout=20s`, `max_connection_attempts=2`, and all three public
   methods wrap their thread call in `asyncio.wait_for` (90s for
   preview/session-check, 600s for an actual media download -- downloads
   legitimately take longer). `list_profile_items` raises a new
   `InstaloaderTimeoutError` (a `RuntimeError`, so the existing 502 mapping
   in routes.py needed no change); `test_session` treats a timeout as "not
   verified" rather than raising.
2. The likely dominant cause for *this specific report*: with no `since`
   bound, `_collect_posts` had nothing to stop pagination early --
   `get_reels()`/`get_posts()` page through a profile's entire history for
   an active account, each page its own request with instaloader's own
   rate-limit courtesy delay between them (`sleep=True`). Added
   `_MAX_ITEMS_WITHOUT_DATE_RANGE=50`, verified with an infinite-generator
   test that the cap actually stops iteration rather than truncating a
   finite list after the fact. An explicit date range still overrides it.

Live-verified against real Instagram servers with a fake cookie
afterward: the same class of call that used to hang now fails cleanly in
7 seconds. UI hint text updated to mention the cap.

### Round 5 — second real-credential attempt: preview still times out, and Verify breaks after reload (open, not yet diagnosed)
After Round 4's fix, the same real session cookie was retried against the
same profile: preview now fails cleanly instead of hanging, but still hits
the 90s `InstaloaderTimeoutError` -- Instagram is not responding in time
even with the shorter per-request timeout, not just failing to respond
*eventually*. Two new reports from this attempt, neither fixed yet:

1. **Preview still times out at 90s against a real profile with a real
   session.** Round 4's fix (shorter per-request timeout, item cap, outer
   wait_for) reduced a 5+ minute hang to a clean 90s failure, but 90s is
   still a failure, not success -- something is still slow or being
   throttled even after the fixes. Not yet known whether this is
   Instagram-side rate-limiting of this specific session (plausible: this
   session had already made a failed 5-minute-hang attempt shortly before,
   and this project's own earlier testing independently observed Instagram
   returning "please wait a few minutes before you try again" 401s), a
   remaining unbounded-request-count issue elsewhere in
   `InstaloaderService`, or something else. **Needs a real cookie to
   actually reproduce and step through** -- the user has offered to
   provide one next session, which is the actual unlock here: every prior
   round's testing (including Round 4's fix verification) only ever used
   a fake cookie, which fails fast in a way that never exercises this
   slow-real-session path at all.
2. **Session verification breaks after a page reload and does not recover
   via the Verify button** -- only fixed by clearing the session and
   re-pasting the cookie. Confirmed by reading the code (not yet
   reproduced live): `GET /api/instagram/session` deliberately never calls
   `verify_session()` (by design, to avoid a network call on every poll --
   see Round 3), so showing "unverified" immediately after a reload is
   *expected*, not the bug. The actual bug is that clicking **Verify**
   afterward doesn't succeed either. Leading hypothesis: the preceding
   failed/slow preview attempt got this specific session throttled by
   Instagram, and the Verify click's `test_session()` call (same
   `InstaloaderService`, same 90s cap since Round 4) keeps hitting that
   same throttling and timing out too -- which would mean the cookie file
   on disk was never actually broken, and simply waiting out Instagram's
   cooldown (not clearing+re-pasting) would likely have also worked. This
   is a hypothesis, not a confirmed diagnosis; a genuine bug in
   `SessionControl`'s state handling on the frontend, or in how
   `save_session_cookie`/`clear_session_cookie` interact, has not been
   ruled out. A real cookie makes this directly testable: reload, click
   Verify, observe whether it actually times out (supporting the
   throttling theory) or fails some other way (pointing at a real bug).

### Round 6 — real session cookie in hand: root-caused and fixed; first successful authenticated preview (done)
The user supplied a real Instagram session cookie, which was the unlock
every prior round was waiting on. Reproducing directly against instaloader
with per-HTTP-request timing (rather than through the UI) found that the
session itself was never the problem -- individual Instagram requests
answered in ~0.8s throughout. Four distinct bugs came out of it, all fixed.

**1. `update_cookies()` never actually logged instaloader in.** The engine
attached the stored cookies with `InstaloaderContext.update_cookies()`,
which only pushes cookies into the requests session. It does *not* set
`context.username` -- which is precisely what `context.is_logged_in`
tests -- and it does *not* set the `X-CSRFToken` request header. So every
request ran as an anonymous scraper that merely happened to be carrying a
valid cookie. Consequences, both live-verified:

* `Profile.get_posts()` branches on `is_logged_in`. On the anonymous
  branch, Instagram answered its doc_id query with a **302 to the
  homepage**, which instaloader surfaced as
  `ConnectionException: JSON Query to graphql/query: Expecting value:
  line 1 column 1 (char 0)`. Profile posts therefore failed outright, not
  slowly. This is very likely the same phenomenon as the gallery-dl
  "AbortExtraction: HTTP redirect to home page" recorded in Round 2 --
  i.e. that was probably never about a bad cookie or a private profile
  either.
* On the logged-in branch the identical call returns full per-post
  metadata (date, caption, owner, media URLs), 12 items per request, with
  no follow-up request per item.

Fixed by switching to `context.load_session(username, pairs)`, which sets
both. The username behind a pasted cookie isn't known up front, so
`_build_loader` uses a placeholder (any truthy value satisfies
`is_logged_in`) and `test_session()` caches the real username, keyed by
the cookie so replacing the session invalidates it. Zero extra requests in
the normal flow, since the UI verifies a cookie right after it is pasted.

**2. `get_reels()` costs one extra HTTP request per reel, by design.** This
was the actual cause of the 90s preview timeout. instaloader's reels
connection returns a media struct with no `taken_at`, `caption`, or
`user.username` -- verified to be missing whether logged in or not -- so
its own `node_wrapper` issues a `Post.from_shortcode()` refetch for every
single reel (instaloader's source comments say as much). Measured live:
**5 reels in 70s across 17 HTTP requests**, i.e. ~12-14s per reel once
instaloader's `sleep=True` courtesy delays are included. The 50-item cap
added in Round 4 therefore implied ~10 minutes of work, so the 90s outer
timeout was doing exactly what it should.

Fixed by not calling `get_reels()` at all: reels are read as the
`product_type == 'clips'` entries of the ordinary timeline, which returns
complete metadata 12 items per request. The clips entries were verified to
be *exactly* the same posts, in the same order, that `get_reels()`
produced -- the same five shortcodes, in 3 requests instead of 17.
`_MAX_POSTS_SCANNED = 200` bounds the scan, since filtering means more
posts are read than reels are kept.

**3. Pinned posts broke the date-range early-exit.** `_collect_posts` broke
out of the loop at the first post older than `since`, on the assumption
that the timeline is strictly reverse-chronological. It isn't: Instagram
serves pinned posts at the head of the timeline regardless of age. Live
example -- a profile whose first three timeline entries (Aug 19, Aug 18,
Aug 12) all predated its fourth (Aug 27). A `since` of Aug 20 would have
returned nothing at all. Pinned entries carry a non-empty
`timeline_pinned_user_ids`; they are now skipped rather than treated as
the start of the older tail.

**4. Downloads wrote nothing and still reported success.** Not one of the
reported bugs -- found while verifying the rest, and the more serious
find. `_download_sync` passed the absolute target directory as
`download_post(target=...)`. instaloader substitutes that into its
`dirname_pattern` via `_PostPathFormatter`, which runs every *substituted*
value through `sanitize_path()` -- and on Windows that rewrites `:` to a
fullwidth colon and `\` to a small reverse solidus **unconditionally**
(the `sanitize_paths` constructor flag only forces that behaviour on
non-Windows; it does not disable it). The absolute path therefore became a
single literal directory name, mojibake and all, created under the
process's working directory. `download_post()` still returned `True`, the
`target_dir.glob()` found nothing, `output_path` came back `None` -- and
`download()` marked the job **COMPLETED** anyway. So Instagram downloads
had never once worked, and said they had.

Fixed three ways: the target directory now goes into `dirname_pattern` as
a literal (patterns are not sanitized, only substituted values, so it
round-trips; braces are escaped for `str.format`); `_download_sync` raises
instead of returning `None` when the target directory is empty; and
`download()` refuses to report COMPLETED unless the output file actually
exists on disk.

**5. Posts and reels paged the same timeline twice.** Found while measuring
the fix. Both buckets are views of `Profile.get_posts()`, so requesting
both -- the common "everything" selection -- scanned it once per bucket:
63s for 100 items, uncomfortably close to the 90s budget. `_scan_timeline`
now reads the timeline once and fills both buckets, with each bucket
keeping its own item cap. Same 100 items in **45s**.

#### Live verification (real session cookie, real profile, `nasa`)
Through the real HTTP API, with the real `InstaloaderService`:

| Call | Result |
| --- | --- |
| `POST /api/instagram/session` | 200, `verified_username` returned, 1.8s |
| `GET` then `POST /api/instagram/session/verify` | 200, verified, 2.7s |
| `POST /api/instagram/profile/preview` posts+reels, no date range | 200, **100 items, 45.1s** |
| `POST /api/instagram/profile/preview` posts, `posted_after` set | 200, 8 items, 9.4s |
| `DELETE /api/instagram/session` | 200, status returns to unconfigured |

Preview items carry real captions, real dates, real author usernames
(including co-authored posts attributed to the co-author), working
thumbnail URLs, and correct `post`/`carousel`/`reel` classification -- so
the JSON field-mapping that had been implemented-but-unverified since
Round 1 is now confirmed against real authenticated data.

Downloads were verified end-to-end too: a reel wrote a 5.3 MB
`Dcea3BiPTBm_GraphVideo.mp4` (ffprobe: h264 + aac, 41.2s) into
`Instagram/<user>/Posts/`, and a carousel wrote both of its images. No
stray sanitized directories are created any more.

**This clears the gate no previous round had cleared:** a successful
authenticated profile preview returning real, correctly-mapped items.

Round 5's second report -- "session verification breaks after reload and
does not recover via Verify" -- did not reproduce once the login wiring
above was fixed: `POST /api/instagram/session/verify` returns the verified
username in under 3s, including after a reload with an already-stored
cookie. The Round 5 hypothesis that this was Instagram-side throttling was
probably wrong; the more likely explanation is that Verify shared the same
broken anonymous-session path as everything else. `GET
/api/instagram/session` still deliberately reports `verified_username:
null` without a network call, which is by design (Round 3).

35 regression tests were added for the above (209 backend tests pass).

### Round 7 — user testing on a real profile: reels came back empty, and four other gaps (done)
Round 6's fix was verified only against `nasa`. User testing on
`penvi_bomnyo` immediately found reels returning **zero** items while posts
worked fine, plus a set of product gaps. Diagnosis and fixes below; a real
session cookie now lives at `.secrets/instagram_session.json`
(gitignored -- see "Test credentials" at the end of this section) so these
paths can be re-verified without asking the user for one each time.

#### 1. Reels came back empty — the Reels tab is not a subset of the grid
Round 6 replaced `Profile.get_reels()` with "timeline entries where
`product_type == 'clips'`", having verified on `nasa` that the two produced
the same posts in the same order. That generalized badly. Measured on
`penvi_bomnyo`:

- Timeline: 25 posts (`mediacount=25`, i.e. the whole grid), **0 clips**
- Reels tab: 15+ reels, **not one of them present in the timeline**

The two collections are entirely disjoint on that account, because Instagram
lets a reel be published without showing on the profile grid. So the Round 6
approach returns nothing at all for such a profile, not merely "sometimes
fewer".

Going back to `get_reels()` was not an option either: re-measured at **15
reels in 179 seconds**, because its `node_wrapper` issues a
`Post.from_shortcode()` refetch per reel to fill in metadata the connection
omits. Correct but unusable; Round 6's version was usable but wrong.

**The fix takes neither.** `_collect_reels` drives the reels connection
directly through `instaloader.NodeIterator` with a `node_wrapper` that hands
back the raw media struct instead of refetching, so a page of 12 reels costs
one request. The struct has `code`, `image_versions2` and
`clips_tab_pinned_user_ids` but no `taken_at` and no `caption`. The date is
recovered from the media `pk`, which is Snowflake-like:
`(pk >> 23) + 1314220021721` ms. Validated against known-good dates:

| shortcode | derived | true | delta |
| --- | --- | --- | --- |
| `Dbuhr-nvu3G` | 05:21:46 | 05:22:36 | −50s |
| `DZXsJJyvkix` | 15:27:48 | 15:28:36 | −47s |
| `DWytxt5DyRF` | 13:47:24 | 13:57:25 | −10m |
| `DcYSnllvjCn` | 10:38:12 | 11:09:01 | −31m |

Always early, by 47s to ~31min -- the pk is stamped when the upload begins,
not when the post publishes. Good enough to sort by and to filter a
day-granularity range with, and it is treated as an approximation, not
presented as exact: see #5 below for how it gets corrected.

Result on the same profile: **50 reels in 23.2s**, versus 0 items before.

#### 2. Downloads scattered across other people's folders
`_post_to_preview` set `author_username` from `post.owner_username`, and the
download folder keyed on that. Instagram credits a co-authored post to the
collaborator (live-verified: a post browsed on `nasa` reports
`nasajohnson`), so downloading one profile spread its files across other
users' folders.

`ProfileItemPreview`/`CollectionItem` now carry a separate
`profile_username` -- the profile the item was *discovered under* -- with an
idempotent column migration. Downloads key on it, falling back to
`author_username` for rows saved before the column existed;
`author_username` stays the true credit. To answer the question that
prompted this: highlights, stories, posts and reels for one profile all land
under `Instagram/<profile>/`, in `Posts`/`Reels`/`Stories`/`Highlights`.

#### 3. Adding the same item twice silently duplicated it
`collection_items` had no uniqueness constraint, so previewing a profile
again and re-adding the same selection duplicated every row. Now a unique
index on `(collection_id, COALESCE(external_id, source_url))` -- the
COALESCE because stories/highlights have no shortcode, and SQLite treats
NULLs in a unique index as distinct. `add_item` became an upsert that
returns the row already stored, so re-adding is a quiet no-op rather than an
error.

Databases written before this can already contain duplicates, which would
make `CREATE UNIQUE INDEX` fail on exactly the databases that need it, so
`_ensure_item_uniqueness` collapses them first, keeping the earliest row of
each group so a recorded `downloaded_job_id` is not thrown away.

#### 4. Filenames lost the date, and captions were not written
Round 6 set `filename_pattern='{shortcode}_{typename}'` and
`post_metadata_txt_pattern=''`, the latter reasoning that the caption is
already in the database. Both were wrong for an archive that should be
readable without PocketDL, and the user pointed out that instaloader's own
defaults already do the right thing (`'{date_utc}_UTC'` and `'{caption}'`).

Filenames are now `{date_utc:%Y-%m-%d_%H-%M-%S}_{shortcode}` -- date first
so a folder sorts chronologically, shortcode retained so the name is
collision-free and a generated gallery can link back to the post.
instaloader's literal default renders with colons, which hit the same
Windows `sanitize_path` mangling documented in Round 6, hence the explicit
format spec. The `<basename>.txt` caption sidecar is back on; the heavier
per-post JSON stays off. Note instaloader writes no sidecar when a post's
caption is empty (`if metadata_string:`) -- that is expected, not a failure.

Existing downloads keep their old names by the user's explicit choice: no
rename migration, they will delete and re-download the handful affected.

#### 5. Exact caption and date backfilled at download time
The consequence of #1 is that a reel preview has no caption and an
approximate date. But downloading fetches the real post anyway, so
`_download_sync` now returns a `DownloadResult` carrying the exact caption
and `date_utc`, and `download()` writes them onto the collection item.
Live-verified: the stored item's `posted_at` moved from the derived
`2026-08-23T10:38:12` to the true `2026-08-23T11:09:01` once downloaded.
`update_item_metadata` only ever fills gaps -- a reel with genuinely no
caption never blanks one that discovery did supply.

#### 6. Polling does not, and must not, reach Instagram
The user asked whether the PWA's polling could get the account
rate-limited. It cannot, and that is now a tested contract rather than a
comment. The 2s refresh loop calls `/api/downloads`, `/api/system/status`,
`/api/captures` and `/api/settings` -- all local (SQLite plus memoised
version strings; `versions()` caches, so no subprocess per tick). The panel
reads `/api/instagram/session` once on mount, and that route deliberately
does not verify (Round 3).

`tests/test_polling_does_not_hit_instagram.py` trips an assertion if any
polled endpoint reaches `InstaloaderService`, and asserts the converse --
that explicit verification still does -- so the tripwire cannot be satisfied
by simply breaking verification. This required the project's first
HTTP-level test harness, the `api_client` fixture in `tests/conftest.py`,
which builds the real app against a throwaway database.

#### Live verification (real session, `penvi_bomnyo`)
| Call | Result |
| --- | --- |
| Reels preview, no date range | **50 items, 23.2s** (was 0 items) |
| Posts + reels, no date range | 75 items, 27.3s |
| Posts, `posted_after` set | 3 items, 8.7s, correct cutoff |
| Add same item twice | 1 row in the playlist |
| Download | `Instagram/penvi_bomnyo/Reels/2026-08-23_11-09-01_DcYSnllvjCn.mp4` |
| Carousel download | 6 images + one shared `.txt` caption sidecar |
| "Download all" again | 0 jobs queued -- completed items skipped |

235 backend tests pass (up from 209).

#### Test credentials
`.secrets/` is gitignored (whole directory, so a future platform's test
session can be dropped in without touching `.gitignore` again).
`.secrets/instagram_session.json` holds a real browser session export used
to exercise these paths against live data. It is a full account credential,
not a scoped token: never commit it, never log it, never echo it into a
response or a test fixture.

### Round 8 — UI responsiveness: the browser was downloading 16x more image than it needed, and being woken every 2s (done)
The user's most-felt complaint. Three compounding causes, all fixed; none of
them was the one originally suspected (the preview request's own latency).

#### 1. Preview thumbnails were the full-size originals
`_post_to_preview` sent `post.url`, which is the *original* upload --
measured at **3024x4032** on a real profile. Instagram offers the same image
at a dozen renditions in `image_versions2.candidates`, and the reels
connection was likewise handing back the 640px entry because it took
`candidates[0]`. A preview grid renders up to 100 of these at once.

`_pick_thumbnail` now takes the smallest rendition at least 320px wide
(sorting by width, since Instagram lists candidates largest-first and then
appends a second set at a different aspect ratio, so position means nothing).
Measured on the reported profile by summing `Content-Length` across every
card:

| | 25 post cards |
| --- | --- |
| Before (`post.url`) | **10.22 MB** |
| After (~320px rendition) | **0.62 MB** |
| | **16.5x smaller** |

At the 50-100 card sizes a real preview returns, the old behaviour was tens
of megabytes of image, against a browser cap of ~6 connections per host.
This was the dominant cause of the page becoming hard to scroll.

#### 2. The 2s poll woke the client whether or not anything had changed
`App.tsx` polled four endpoints every two seconds unconditionally, replacing
the `downloads` and `captures` arrays each time, so React re-rendered both
lists constantly even on a completely idle app.

Replaced with server-sent events at `GET /api/events`. SSE rather than a
WebSocket: the traffic is entirely server-to-client, it is plain HTTP so it
survives the Termux/reverse-proxy setup with no upgrade path, browsers
reconnect on their own, and it needs no new dependency. (The backend had no
WebSocket endpoint at all -- the `/ws` line in `apps/web/vite.config.ts` was
aspirational and unused.)

The stream compares each snapshot against the last one it sent and emits a
comment-only keepalive instead when they match, so an idle app receives
nothing that reaches its handler. Waking is driven by `ChangeNotifier`:

- An HTTP middleware fires it after any non-GET request that succeeded, so a
  new mutating route cannot forget to.
- `QueueService` fires it on every download progress tick, which changes
  state without any request at all.
- Each stream also has a 15s heartbeat, so correctness never depends on
  every mutation site remembering.

**The notifier is level-triggered, not edge-triggered**, and this was a real
bug caught by its own test rather than by review. A subscriber spends most of
its cycle *not* waiting -- building a snapshot, writing it, then throttling
400ms before the next -- and a plain broadcast fired inside that window was
simply lost, stranding the client until the next heartbeat: 15 seconds of
apparently frozen UI. Each notification now bumps a version, and a subscriber
reads the version *before* building its snapshot and waits on "has it moved
past that", which cannot miss a change however the two interleave.

The client keeps `refresh()` as a fallback: if `EventSource` is missing or
the stream errors, it resumes the 2s poll and stops again as soon as a frame
arrives.

#### 3. Re-rendering on unchanged data
Even with pushes, applying every snapshot would replace the arrays and
re-render. `applyServerState` compares each section and returns the previous
value unchanged when it matches, which makes React bail out of the render
entirely.

#### Verification
Backend behaviour is covered by `tests/test_events_stream.py`, which drives
the route's own body iterator -- httpx's `ASGITransport` buffers a response
to completion before returning it and therefore cannot consume an endless
stream at all, so an HTTP-level test of SSE is not possible with the current
test client.

Verified over real HTTP against `uvicorn`: an idle stream sends one state
frame and then nothing; a `PUT /api/settings` produced a second frame
carrying the new value within the throttle window; `GET /` and
`GET /api/events` are served from the same origin, and the built bundle
really does construct an `EventSource` against `/api/events`.

**Not machine-verified:** the browser-side behaviour itself. There is no
browser automation in this environment, so whether the page *feels* faster is
the user's call. The thumbnail measurement above is objective; the SSE
behaviour is verified server-side and by unit test, but nobody has watched
it drive a real page.

251 backend tests pass (up from 235).

### Round 9 — selecting a whole profile, and two playlist UI bugs (done)
Reported after using Round 8: a profile with 128 reels only ever showed 50,
with no way to reach the rest; adding to a playlist reported success while
the playlist showed nothing; and creating a new playlist became impossible
after deleting one.

#### 1. Results truncated at 50 with no way to see the rest
`_MAX_ITEMS_WITHOUT_DATE_RANGE` cut every result at 50 and said nothing.
The user asked whether previewing should be gated behind a date filter
instead -- it should not: a date range can exceed 50 just as easily, so
gating would trade a silent cap for a mandatory guess.

Three changes instead:

- **The cap became a page size.** `limit` (default 50, max 200) always
  applies, and the response now carries `has_more` -- true only when a
  content type exactly filled its page, never because a scan ceiling was hit
  or a feed ran out, so "Load older items" appears exactly when there really
  is more. Note this also *changed* behaviour: the cap previously applied
  only when no `since` was given, on the theory that a date range bounds the
  work by itself. It does not -- "everything since 2019" is an unbounded walk
  of a whole profile in one request.
- **The cursor is a date, not an opaque handle.** instaloader can
  `freeze()`/`thaw()` a `NodeIterator`, but that state expires, has to be
  carried across restarts, and has to be rebuilt identically to be usable.
  Both feeds here are already reverse-chronological and the code already
  filters on `until`, so the next page is simply "older than the oldest item
  I have" -- reusing machinery that exists and is verified. The cost is that
  page N re-scans the N-1 pages above it, and that an item sharing a
  timestamp with the last of a page can reappear, so callers de-duplicate by
  `external_id`. The cursor is the *oldest* item, not the last one, because
  pinned posts break feed ordering.
- **`POST /api/collections/{id}/profile-items` adds everything matching, in
  one call.** This is the real answer to "how do I select 128 reels": you
  should not have to render 128 cards to tick them. It runs the same query
  server-side up to 200 items and adds what it matches, reporting `added`,
  `already_present`, and `has_more` so a truncated bulk add says so instead
  of quietly adding a subset.

A large page raises its own timeout (240s vs the default 90s), since
otherwise asking for 200 items would reliably fail at 90s having already
done most of the work.

**Live-verified on the reported profile:** page 1 returned 50 reels in 20.5s
with `has_more=true`; the cursor fetched 50 more in 31.1s, 49 new after
de-duplication and 1 expected overlap; and a single bulk add took **40.8s to
add all 128 reels** with `has_more=false`, confirming the user's own count.
Running it again added 0 and reported 128 already present.

#### 2. A playlist showed nothing after items were added to it
`PlaylistCard` fetched its item list once, on first expand, and cached it in
component state forever. Adding items afterwards refreshed the header count
but not the list underneath -- so "Added 50 item(s)" was followed by an empty
playlist, and there was no way to see what "Download all" would act on.

It now re-fetches when the server's count differs from the count the list was
last loaded for. Keyed on the count rather than compared against
`items.length` deliberately: if the two ever disagreed persistently,
comparing lengths would re-fetch on every render forever.

`CollectionService.add_items` also now reports `added` and `already_present`
separately, so a bulk add can no longer claim to have added items the
playlist already held -- which is what made the original report confusing.

#### 3. "New playlist" stopped offering a name field
After adding, the panel pins its playlist selector to the playlist just used.
Deleting that playlist left the selector holding an id that no longer
existed: the `<select>` fell back to *displaying* its first option ("New
playlist...") while the state still said otherwise, so `{!targetCollectionId
&& <input/>}` never rendered and there was no way to create a playlist at
all. The selection is now cleared whenever it no longer matches a known
playlist.

#### Also
- **Select all / clear selection** on the loaded results, deliberately scoped
  to what is on screen -- selecting items the user has not seen is what "Add
  all matching" is for, and that runs server-side rather than pretending a
  hidden page is loaded.
- The user reported seeing "101" in the network tab and asked whether that
  was the event stream. It is not: 101 is a protocol upgrade, which is Vite's
  own dev-server HMR socket. PocketDL's stream is a plain `200` with
  `text/event-stream` that stays open.

266 backend tests pass (up from 252).

**Not machine-verified:** the three UI behaviours above are frontend-only and
there is no browser automation in this environment. The build and typecheck
are clean and the logic was traced by reading, but nobody has watched them in
a real page.

### Round 10 — long-list management (planned, not started)
Reported after using Round 9. Three related complaints, all the same shape:
**lists only ever grow, and they do not update themselves.** Treat them as
one piece of work, not three, because the fix is a shared pattern.

1. **A playlist is one unbroken scroll.** Completed items stay in it
   alongside pending ones, so it grows every time more is added and there is
   no way to see "what is left to download" separately from "what is already
   on disk". Wanted: tabs (at minimum pending / downloaded / all) plus
   pagination within each.
2. **A playlist does not update live.** Downloading an item does not move it
   to "Downloaded" or update its badge until the page is reloaded. Round 8
   put downloads, captures, status and settings on the SSE stream but **not
   collections**, so `PlaylistCard` only refreshes when an action in the
   panel happens to call `onCollectionsChanged`.
3. **The downloads list has the same problem** -- it grows without bound and
   has no filtering or paging of its own.

#### Design notes for whoever picks this up
- **Live playlists (item 2) is the enabling change; do it first.** Add
  collections (and, for an expanded playlist, its items) to the
  `_event_snapshot` payload in `app/api/routes.py`. The notifier already
  fires on every successful mutation and on download progress, so nothing
  new has to be instrumented -- but see the level-triggered contract in
  `app/application/events.py` before touching the stream loop, and note that
  `tests/test_events_stream.py` drives the route's `body_iterator` directly
  because httpx's `ASGITransport` cannot consume an endless stream.
  - Watch the payload size: a playlist with 128 items in every snapshot is
    not free. Prefer sending collection *summaries* (id, name, counts by
    state) always, and full items only for a playlist the client says is
    open -- or keep items on their existing endpoint and let the summary
    counts drive a re-fetch, which is what `PlaylistCard` already does via
    `loadedForCount`.
- **Counts by state belong on the server.** `CollectionResponse.item_count`
  should grow siblings (e.g. `downloaded_count`), so a tab can show
  "Pending 78 / Downloaded 50" without shipping every row to compute it.
  `collection_items.downloaded_job_id` already records the state.
- **Paginate `GET /api/collections/{id}/items`** with limit/offset and a
  `state` filter. This one is a plain SQLite query -- unlike the Instagram
  feed cursor in Round 9, there is no reverse-chronological remote feed to
  work around, so ordinary offset paging is fine here and the date-cursor
  reasoning does *not* apply.
- **Downloads (item 3) wants the same treatment**, but its list is on the
  SSE snapshot, so paging it server-side interacts with the stream: either
  send only recent/active jobs in the snapshot and page history separately,
  or keep sending all and filter client-side. Sending everything forever is
  what makes the payload grow, so prefer the former -- but note the client
  currently diffs the whole array to decide whether to re-render, and that
  comparison has to stay meaningful.
- A "clear completed" / "remove downloaded from playlist" action is the
  cheap complement to all of this and probably worth doing at the same time.

Nothing here is started. No code has been written for Round 10.

### What's left
- **Stories and Highlights have still never been live-verified**, and
  `_collect_stories`/`_collect_highlights` still call
  `get_stories()`/`get_highlights()` directly -- they may carry the same
  per-item refetch cost `get_reels()` did. Measure before trusting.
- **Only public profiles tested.** A private profile the session follows,
  and one it does not, still need checking for correct
  `InstagramAuthRequiredError` classification.
- **Bulk add stops at 200.** Beyond that the only route is narrowing the
  date range; the response says so rather than truncating silently, but a
  profile with thousands of items still cannot be taken in one action.
- **UI responsiveness** is addressed in Round 8 above, but only the
  server side is verified -- whether the page actually feels better is
  still unconfirmed by anyone but the user. A backend thumbnail proxy was
  considered and *not* built: it would not lift the browser's
  per-host connection cap, and picking a smaller rendition removed 94% of
  the bytes without adding an SSRF-shaped endpoint.
- **Long-list management (Round 10 above) is the next piece of work** and
  the user's current top priority: playlists and the downloads list both
  grow without bound, cannot be filtered by download state, and playlists do
  not update live because collections are absent from the SSE snapshot.
- Merging the pilot to `main`.

### Resuming this work
On branch `feature/phase5-instagram-collections`, not yet merged to `main`,
working tree clean apart from a local `allowedHosts: true` tweak in
`apps/web/vite.config.ts` that is deliberately left uncommitted.

The session cookie in `.secrets/instagram_session.json` (gitignored) makes
every live check above repeatable -- `penvi_bomnyo` is the profile the last
three rounds were verified against (25 grid posts, 128 reels, disjoint).

Two standing constraints worth re-reading before changing anything here:
`tests/test_polling_does_not_hit_instagram.py` (nothing the client polls may
reach Instagram) and the level-triggered notifier contract in
`app/application/events.py`.

There is no browser automation in this environment, so any UI change is
verifiable only by build + typecheck + reading; say so rather than implying
it was seen working.

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
