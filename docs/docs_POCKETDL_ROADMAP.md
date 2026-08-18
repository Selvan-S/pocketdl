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

## Capture deduplication — partially done
Fixed: signed tokens embedded in the media URL's *path* (not just the query
string, which was already handled) no longer create a new card on every
refresh. `normalize_media_url` replaces path segments that look like opaque,
request-scoped tokens (UUIDs, long hex, long mixed alphanumeric) with a
placeholder before hashing, conservatively — numeric IDs and short/word-like
segments are left alone so distinct videos and quality variants stay
distinguishable. "When a signed URL changes: update existing capture with
newest URL/context, do not create an additional card" — done for this case.
Historical captures self-heal via the existing startup re-keying pass.

Still open, not attempted:
- Grouping a master manifest with its own quality-variant sub-manifests
  (`master.m3u8` vs `720p.m3u8`) into one card — these have genuinely
  different paths, not a rotating token, so today's fix correctly leaves
  them distinct. This needs a different mechanism (e.g. parsing the master
  playlist's variant list) if it's wanted.
- Multi-CDN / hostname rotation for the same content.
- host/path normalization beyond token stripping, codec information, a
  broader stable-identity hash.

Test with players that refresh manifests frequently.

## Media metadata — partially done
Fixed: hls/dash captures no longer report the manifest text file's
Content-Length as the media's size (was showing e.g. "500 B" for a real
multi-hundred-MB stream). Only a direct media capture's Content-Length is
trusted as a real size now; hls/dash size is left unknown until ffprobe
enrichment determines it, which is honest rather than wrong.

Still open, not attempted:
- HLS segment enumeration for a best-effort size estimate when ffprobe can't
  determine one.
- codecs, frame rate, bitrate.
- Never display an exact size when it is only an estimate — no
  estimate-vs-exact UI distinction exists yet; today it's exact-or-unknown
  ("—"), which side-steps the "never show a wrong exact number" requirement
  without yet building the labeled-estimate UI this line originally asked for.

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

## Format model
Expose:
- resolution.
- codec.
- container.
- audio codec.
- bitrate.
- frame rate.
- estimated size.
- protocol (HLS, DASH, HTTP, etc.).

## User selection
Allow:
- Best.
- 1080p.
- 720p.
- 480p.
- audio-only.
- custom format/codec where appropriate.

## Filename policy
Priority:
1. User-entered name.
2. Extracted title.
3. Page title.
4. Safe fallback.

Never use raw signed m3u8 query strings in filenames.

---

# Phase 4 — Browser experience

## Extension improvements
- Better capture deduplication.
- Capture quality ranking.
- Show duration/size/resolution in popup.
- Popup Download action.
- Open in PocketDL action.
- Capture freshness/age.
- Clear/ignore capture actions.
- Better status/connection handling.

## Browser session support — future, explicit feature
Only if required by real sites.
Potential support:
- controlled cookie/session handoff.
- secure local storage.
- expiration/clearing.
- explicit opt-in.

Never silently export browser cookies.

---

# Phase 5 — Download manager maturity

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

# Phase 6 — Mobile productization

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

---

# Phase 7 — Reliability and security

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

# Phase 8 — v1.0

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

# Non-goals / boundaries

Do not attempt to:
- bypass DRM.
- decrypt protected streams.
- silently collect browser credentials.
- expose the downloader to the LAN by default.
- embed paid downloader limits or adware.
- hardcode one site's quirks into the generic downloader core.
