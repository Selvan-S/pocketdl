# Changelog

## Unreleased

### Download robustness: disguised HLS segment extensions and broken cert chains
User-reported failures on two real sites, both fixed with regression tests:
- A captured HLS download failed with `FFmpeg exited with code 183` /
  `is not in allowed_segment_extensions`. The site serves its `.m3u8`
  playlist and segments with `.txt`/`.css` extensions (a common
  ad-blocker/bandwidth-saver evasion trick); ffmpeg's hls demuxer rejects
  segment URLs whose extension isn't on its small built-in allowlist unless
  told otherwise. Added `-allowed_extensions ALL` to both the ffmpeg
  download command and the ffprobe duration-probe call in
  `CapturedMediaService`.
- A standard (yt-dlp) download of a direct `.mp4` URL failed with
  `[SSL: CERTIFICATE_VERIFY_FAILED] ... unable to get local issuer
  certificate`. The site serves an incomplete certificate chain (missing
  intermediate) that browsers silently repair via AIA chasing but Python's
  `ssl` module does not. Added a new, narrow retry fallback: on
  `SSL_CERTIFICATE_ERROR` (a new `DownloadErrorCategory`), retry the same
  attempt once more with `--no-check-certificate`, visible in the attempt
  label (`...+no-check-certificate`) and in `job.error_details` rather than
  silently disabling verification by default.

### Extension popup actions (Phase 4)
- Added a Remove button to each captured-stream card, wired to the existing
  `DELETE /api/captures/{id}` endpoint the PWA's `CaptureList` already used —
  no backend changes needed.
- Added an Open button that opens the PWA at `?capture=<id>`; the PWA now
  scrolls to, expands, and briefly highlights that capture card, then strips
  the query param.
- Replaced the absolute capture timestamp with a relative age ("5m ago"),
  keeping the exact time as a hover tooltip.
- `background.ts`'s capture-post fetch never checked `response.ok`, so a
  4xx/5xx from the backend (not just a network failure) was silently treated
  as success and the capture just vanished with no signal anywhere. It now
  records the outcome of every attempt to `chrome.storage.local`, and the
  popup shows a dismissible banner on the most recent failure instead of
  nothing.
- "Show duration/size/resolution in popup" and "Popup Download action",
  also listed under this roadmap phase, turned out to already be
  implemented. "Capture quality ranking" (grouping a master manifest with
  its variant sub-manifests into one selectable card) remains out of scope —
  it needs its own domain-model/API design, tracked separately.

### Connection status resilience
- The PWA's "Connecting…"/"Backend connected" pill was gated behind
  `Promise.all` over four endpoints (downloads, system status, captures,
  settings); one endpoint failing kept the pill stuck on "Connecting…"
  forever even though most of the API was healthy and `/api/health` reported
  fine. Switched to `Promise.allSettled` so each piece of state updates
  independently and only a genuinely failing request surfaces in the status
  message.
- The backend-served PWA build never served `/manifest.webmanifest` (404) —
  only `/` and `/assets` were mounted. Added the missing route.

### Format selection (Phase 3)
- `AnalyzeResult.tsx` was built but never imported anywhere; `DownloadForm.tsx`
  rendered a separate minimal inline summary instead, so the format list
  `/api/analyze` already returned was effectively dead — its own code comment
  said "Format selection will be added in a later release." Wired it in:
  clicking a video format chip now selects that exact `format_id`, which
  overrides the coarse quality preset for that download
  (`-f "<format_id>+bestaudio/best"`). Audio-only formats are shown but not
  individually selectable — they'd double up with the `+bestaudio` merge —
  and continue to go through the existing "Audio only" preset.
- Added a `480p` preset, completing the roadmap's listed preset set
  (Best/1080p/720p/480p/audio-only).
- Format chips now also show fps and bitrate; both were already threaded
  through the full domain → schema → route → frontend pipeline but never
  rendered.
- `format_id` is validated at the API boundary (a pydantic field_validator
  rejecting anything outside `[A-Za-z0-9_.+-]`) and, defensively, again where
  it's consumed — a malformed value degrades to the preset instead of
  reaching yt-dlp's `-f` argument unshaped.
- Moved format-argument construction out of a private, untested
  `YtDlpService` method into `application/downloads/strategy.py:format_args`,
  a pure function alongside the module's existing retry-strategy logic.
  Added 8 regression tests covering every preset, format_id overriding a
  preset, a composite `format_id` (e.g. `"137+140"`), and the malformed-input
  fallback.
- Verified end-to-end against a live backend instance: a malformed
  `format_id` is rejected with 422 before reaching yt-dlp; a valid one is
  accepted (201) and actually reaches yt-dlp as a real subprocess — confirmed
  by yt-dlp's own output showing it parsed the `-f 137+bestaudio/best`
  argument successfully and only failed at the (expected, URL was fake)
  network fetch step, not at argument parsing.

### Extension packaging for Android
- Added `scripts/extension-package.sh`. Android Chromium browsers with
  extension support (confirmed with Quetta) generally accept a packaged
  `.zip`/`.crx`, not desktop Chrome's "Load unpacked" folder picker — and
  Termux's home directory is a private app sandbox other apps can't browse
  into via a folder picker regardless. The script rebuilds the extension,
  zips exactly `manifest.json`, `popup.html`, and `dist/*.js` (excluding
  source maps, `node_modules`, and other dev-only files), and — best-effort,
  only when Termux storage access is granted — copies the result to
  `~/storage/shared/pocketdl-capture.zip` so Quetta's file picker can reach
  it. Verified: the zip's internal layout matches what `manifest.json`
  references, its `manifest.json` is byte-identical to the source, and all
  four packaged `.js` files parse as valid JavaScript.
- Fixed a latent cross-platform bug in the script's python-interpreter
  detection during that verification: `command -v` only checks that
  something exists at a given name, and on Windows `python3` frequently
  resolves to a non-functional App Execution Alias stub. Naive
  `command -v python3 || command -v python` would have preferred the broken
  stub over a working `python`. Fixed by actually invoking each candidate
  (`--version`) rather than trusting existence alone.

### Suspicious/short capture detection
- Moved short-media detection out of the React component and into the domain
  layer as `is_suspicious_capture`, exposed as `looks_suspicious` on
  `CaptureResponse` and rendered in both the PWA and the extension popup
  (previously the extension popup showed no warning at all).
- The old check was a hardcoded 10s duration threshold that only applied to
  `capture_type=media`, so an hls/dash capture whose probed duration turned
  out to be ~2s — the exact scenario CLAUDE.md's backlog describes — could
  never be flagged. Duration now applies to every capture type.
- Added two signals the roadmap asked for and the duration-only check missed:
  tiny direct-media size (<50KB; direct media only, since hls/dash
  `size_bytes` is deliberately unset), and segment/chunk-shaped URLs. The
  latter mirrors the extension's own client-side `isLikelyMediaSegment`
  filter as a backend-side backstop, so captures predating that filter, or
  from any non-extension client, are still caught.
- Still a flag, never a hard delete, per the roadmap's explicit requirement —
  a legitimate short clip stays downloadable, just marked. Thresholds are
  module-level constants, tunable in one place but not yet user-configurable
  at runtime; that and MIME-based fragment detection remain open.
- Added 8 domain tests covering each signal plus the cases that must NOT be
  flagged (normal-length streams, plausible full media, and hls/dash size
  which must never factor in). Full backend suite: 35/35.

### Capture deduplication and size accuracy
- Fixed duplicate capture cards for signed tokens embedded in the media URL's
  *path* rather than its query string (e.g.
  `/media/8f7a2b91c3d445fabb0e7a1c9d4e6f21/master.m3u8`, token rotating on
  every request). Query-string tokens were already handled — the whole query
  is dropped during normalization — but a path-embedded token changed the
  dedup hash on every refresh, since the path was previously kept verbatim.
  `normalize_media_url` now replaces path segments that look like opaque,
  request-scoped tokens (UUIDs, long hex strings, long mixed alphanumeric
  strings) with a placeholder before hashing. Deliberately conservative: pure
  numeric segments and short/word-like segments are left untouched, so
  distinct videos, quality variants (`master.m3u8` vs `720p.m3u8`), and
  numeric content IDs remain distinguishable. Historical captures self-heal
  on the next backend start via the existing startup re-keying pass — no
  migration needed. Known remaining gap, not attempted here: grouping a
  master manifest with its own quality-variant sub-manifests into one card is
  a different problem (they have genuinely different paths, not just a
  rotating token) and is left for later, as the roadmap already scopes it
  separately.
- Fixed hls/dash captures showing a tiny, wrong media size (e.g. "500 B" for
  a real multi-hundred-MB stream). The browser reports `Content-Length` for
  whatever it fetched — for hls/dash that is the manifest *text file*, not
  the media — and it was being stored directly as `size_bytes`. Only a direct
  `media` capture's `Content-Length` is now stored; hls/dash size is left
  unknown (shown as "—") until ffprobe enrichment determines it, which is
  honest given true HLS/DASH size generally requires enumerating every
  segment — a further improvement explicitly left to a later pass, not
  attempted here.
- Added `services/api/tests/test_capture_domain.py` (7 tests) and 3 new tests
  in `test_capture_service.py` covering both fixes plus the cases that must
  NOT collapse (distinct variants, distinct slugs, distinct numeric IDs).
  Full suite: 27/27 passing, no regressions.

### Android/Termux M1–M6 baseline

- Fixed `pocketdl-service.sh` resolving its own location to `~/.termux`
  instead of the repository when started via the Termux:Boot hook, which
  crash-looped the backend forever after every real reboot (confirmed on
  device: `code=127`, `.../.termux/scripts/start.sh: No such file or
  directory`). The hook invokes the script through a symlink
  (`~/.termux/boot/pocketdl-start -> pocketdl-service.sh`); `dirname` on
  `${BASH_SOURCE[0]}` resolves against the symlink's own location, not its
  target, so `REPO_DIR` landed one level up from the boot directory instead of
  the real checkout. `scripts/pocketdl` already handled this correctly with
  `readlink -f`; `pocketdl-service.sh` now does the same. The direct-invocation
  path (`bash scripts/pocketdl-service.sh` from the repo) was unaffected and
  is why this was not caught in prior testing — only the boot-hook symlink
  path was broken. Regression-tested the direct path after the fix on the
  Windows development machine, which lacks the privilege to create real
  symlinks and so could not reproduce the symlink path itself; that path
  still needs on-device re-verification after a reboot.
- Added M6: a supervised background service (`scripts/pocketdl-service.sh`)
  and Termux:Boot autostart. The service holds a `termux-wake-lock` so Android
  does not suspend a backgrounded process, restarts the backend with
  exponential backoff (2s–60s) on crash or exit, and refuses to start a
  second instance if one is already running. `scripts/pocketdl-stop.sh` stops
  it cleanly (SIGTERM, wake-lock release, PID cleanup all verified). Enabling
  autostart requires manually installing the separate Termux:Boot app from
  F-Droid — Android does not let Termux itself receive the boot event — so
  `scripts/termux-boot-install.sh` only wires up the boot hook
  (`~/.termux/boot/pocketdl-start`, symlinked so `git pull` updates it in
  place). Added `scripts/pocketdl-status.sh` as a live-state health/startup
  indicator (service/backend running, uptime, backend API reachability,
  autostart configured), and an M6 section in `termux-doctor.sh --all` for the
  setup-time checks (wake-lock tool present, boot hook installed, Termux:Boot
  app detected best-effort). The supervisor's restart/backoff/signal-forwarding
  logic was verified functionally (start, crash-and-recover, clean stop); the
  actual Termux:Boot-triggered reboot path still needs on-device verification.
- Factored the venv-resolution logic duplicated across `start.sh` and
  `termux-doctor.sh` into `scripts/lib/venv.sh`, now shared by those plus the
  three new M6 scripts.
- Fixed removing a download or capture requiring a manual page refresh to
  disappear. The 2s poll and the delete action both called `refresh()` with no
  sequencing; a poll-triggered call that started just before a delete could
  resolve after it with stale data and silently overwrite the correct state.
  `refresh()` now tags each call with a sequence number and only applies the
  most-recently-*started* call's result. Delete/remove also update local state
  immediately and reconcile afterward, restoring the item and showing an error
  if the delete actually fails.
- Mobile pass: raised `.actions button` (Cancel/Remove on download cards) from
  a 34px to the ~44px touch target the rest of the UI already used, and made
  `.app-shell` pad for `env(safe-area-inset-*)` so content and tap targets
  stay clear of the status bar / gesture-nav strip on notched Android devices
  — `viewport-fit=cover` was declared but nothing had consumed the insets it
  exposes.
- Fixed the web build, which failed with 342 TypeScript errors from a clean
  install because `@types/react` and `@types/react-dom` were never declared.
  Without `apps/web/dist` the backend served no PWA and returned 404 at `/`.
- Fixed a `CaptureList` type error that the missing React types had masked:
  `CaptureCard` was typed `Props & { item }`, requiring an `items` array it
  neither used nor received.
- Declared the test-only dependencies in `services/api/requirements-dev.txt` and
  a `dev` extra. `pytest-asyncio` was undeclared, so both capture regression
  tests errored instead of running. Backend suite now runs 17/17.
- Pinned `apps/web` and extension dependencies off `latest` to the verified
  versions, so Windows and Termux resolve the same tree.
  TypeScript was later repinned from `^7.0.2` to `^5.9.3`: TypeScript 7 is
  a native binary with per-platform packages, and it does not publish an
  `android-arm64` build, so `tsc` cannot run on Termux at all. Verified
  vite's native deps (`rolldown`, `lightningcss`) do ship `android-arm64`
  builds, so only TypeScript needed the downgrade.
- Rewrote `scripts/termux-install.sh`: installs from `requirements.txt` into a
  virtualenv instead of a divergent hand-written list that dropped the
  `curl-cffi` extra; adds the build toolchain the Python dependencies need on
  Bionic; runs in place instead of copying and `rm -rf`-ing a second checkout;
  writes `APP_VERSION`-free config targeting `/sdcard/Download/PocketDL` rather
  than `/sdcard/Download`.
- Added `scripts/termux-doctor.sh`, mechanical M1/M2 verification that exits
  non-zero on M1 failure.
- The installer no longer forces `nodejs-lts`. Termux ships `nodejs` and
  `nodejs-lts` as mutually exclusive packages, so `pkg install -y nodejs-lts`
  would have silently swapped a device-global tool other projects depend on. It
  now keeps any existing Node >= v20 and only installs when none is present.
- `start.sh` and `termux-doctor.sh` resolve the virtualenv via `POCKETDL_VENV`,
  then `services/api/.venv`, then a repo-root `.venv`, so a virtualenv kept
  outside the default layout is supported.
- `scripts/start.sh` and `scripts/pocketdl` now resolve the checkout from their
  own location instead of a hardcoded `~/.pocketdl/app`.
- Marked all scripts executable in the Git index; they were committed 100644 and
  were not runnable after a fresh clone on Android.
- Added `.gitattributes` enforcing LF for shell scripts, so a CRLF shebang can
  never reach Termux from the Windows development machine.
- Ignored `*.tsbuildinfo`.

## 0.2.2

- Fixed historical capture duplicates by normalizing and re-keying captures during startup.
- Added captured media metadata: duration, size, dimensions, and metadata status.
- Added background ffprobe metadata enrichment using captured request context.
- Filtered obvious media segments from browser capture and prefer manifest captures once HLS/DASH is seen.
- Added media-size reporting from browser response Content-Length when available.
- Made capture cards and major web sections collapsible to reduce scrolling.
- Added duration/size information and collapsible capture rows to the browser extension popup.
- Added warnings for suspiciously short direct-media captures.
