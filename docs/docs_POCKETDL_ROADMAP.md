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

# Phase 1 — Android/Termux deployment ← CURRENT

## M1 — Termux runtime
Install and verify:
- Termux.
- Git.
- Python.
- Node.js/npm.
- FFmpeg.
- Android storage access.

Acceptance:
```text
python --version
node --version
npm --version
ffmpeg -version
```
all succeed.

## M2 — Backend on Android
- Clone repository from GitHub.
- Create `.venv`.
- Install `requirements.txt`.
- Verify yt-dlp and curl_cffi.
- Start FastAPI.
- Open Swagger from Android browser.
- Verify `/api/health` and `/api/system/status`.

## M3 — PWA on Android
- Start Vite dev server initially.
- Open PocketDL in Android browser.
- Verify frontend → backend communication.

## M4 — Normal mobile download
- Test a permitted normal media source.
- Verify yt-dlp works on Android.
- Verify FFmpeg works on Android.
- Verify output path under Android Downloads/PocketDL.
- Change path from PocketDL UI and verify persisted value.

## M5 — Browser capture on Android
- Test supported Chromium browser with extension support.
- Verify extension → localhost backend communication.
- Capture HLS/DASH.
- Download captured source.
- Verify Android file output.

## M6 — Background service
- Add Termux:Boot.
- Start PocketDL backend automatically after reboot.
- Consider wake-lock/background process behavior.
- Add a simple health/startup status indicator.

---

# Phase 2 — Stabilization after mobile

## Capture deduplication
Improve identity model beyond URL normalization.

Potential identity inputs:
- page URL normalization.
- host/path normalization.
- manifest path.
- media MIME type.
- title/page title.
- stream dimensions.
- codec information.
- a stable hash of normalized source identity.

When a signed URL changes:
- update existing capture with newest URL/context.
- do not create an additional user-visible card.

Test with players that refresh manifests frequently.

## Media metadata
Improve:
- duration.
- width/height.
- codecs.
- frame rate.
- bitrate where available.
- content length where available.
- HLS segment enumeration for best-effort size estimates.

Never display an exact size when it is only an estimate. Label estimates.

## Short-media filtering
Use configurable heuristics rather than hard deletes.
Possible signals:
- duration < threshold.
- tiny content length.
- URL looks like segment/chunk.
- MIME/content-type is clearly a fragment.
- manifest/direct-media relationship.

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
