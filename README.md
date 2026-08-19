# PocketDL v0.2.2

PocketDL is a local, maintainable downloader built around yt-dlp and FFmpeg. Version 0.2 adds the first browser-capture workflow for difficult HLS/DASH sites; 0.2.2 focuses on capture hygiene, metadata, and scrolling UX.

## What is new

- Chrome Manifest V3 extension for observing `.m3u8` and `.mpd` requests.
- Captures page URL/title, Referer, Origin, User-Agent and non-sensitive request headers.
- Local FastAPI capture API with CORS restricted to localhost and the PocketDL extension origin.
- Persistent SQLite capture history.
- Captured HLS/DASH downloads are routed to FFmpeg directly instead of forcing yt-dlp to reproduce a browser request.
- Existing yt-dlp downloads, analysis, queueing, filenames and error diagnostics remain available.
- Browser captures are visible in the React PWA and can be queued with a custom filename.
- Obvious media segments are filtered, historical duplicates are collapsed, and the newest signed URL is retained.
- Captures expose best-effort duration, size, and dimensions using browser Content-Length and asynchronous ffprobe enrichment.
- Capture cards and major queue/capture sections are collapsible.
- Automatic SQLite migrations preserve an existing v0.1.x database.

## Architecture

```text
Chrome / Chromium
      |
      | webRequest observation
      v
PocketDL Capture Extension
      |
      | JSON over localhost
      v
FastAPI
  |-- CaptureService -> SQLite
  |-- QueueService
  |      |-- standard source -> yt-dlp
  |      `-- captured source -> FFmpeg + captured request context
  `-- System / Analysis APIs
      |
      v
React PWA
```

The browser extension uses the non-blocking `webRequest` API to observe requests. Manifest V3 still supports normal `webRequest` observation; only blocking modification requires the restricted `webRequestBlocking` permission.

## Desktop development

### Requirements

- Python 3.11+
- Node.js + npm
- FFmpeg + ffprobe on PATH
- Chrome/Chromium for extension testing

### Backend

```powershell
cd services\api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m app.main
```

Backend: `http://127.0.0.1:8787`
Swagger: `http://127.0.0.1:8787/docs`

### Web UI

```powershell
cd apps\web
npm install
npm run dev
```

Open `http://localhost:5173`.

### Browser extension

From the repository root:

```powershell
npm install
npm run extension:build
```

Then open:

`chrome://extensions`

Enable **Developer mode** → **Load unpacked** → select:

`apps/browser-extension`

The extension observes media requests on pages where it has host access. Chrome documents that `webRequest` requires the API permission plus host permissions for the requested URL and initiator.

For an Android Chromium browser (tested with Quetta), "Load unpacked" from a
folder generally isn't offered and Termux's storage isn't browsable from
other apps anyway — see [docs/termux.md](docs/termux.md#browser-extension-on-android)
for `scripts/extension-package.sh`, which packages a `.zip` instead.

### Test workflow

1. Start the FastAPI backend.
2. Start the React PWA.
3. Load the PocketDL Capture extension.
4. Open a video page in Chrome.
5. Play the video.
6. When an HLS/DASH manifest is requested, the extension sends the captured request context to PocketDL.
7. Open PocketDL and check **Browser captures**.
8. Choose a filename and download the captured stream.

The extension deliberately does not capture Cookie or Authorization headers in v0.2. Sites that genuinely require those values will be addressed by a separate, explicit browser-session feature rather than silently storing credentials.

## Security model

The backend stays bound to `127.0.0.1` by default. The capture API requires the `X-PocketDL-Extension: 0.2` header and JSON requests. CORS accepts the local web app and Chrome extension origins only.

The extension is intentionally a capture/observation tool, not a request-blocking or request-modifying extension. Chrome's Manifest V3 migration guidance recommends declarativeNetRequest for blocking/modifying traffic; PocketDL does not need those capabilities for v0.2.

## Tests

Backend tests. The test-only dependencies (pytest, pytest-asyncio, httpx2) live
in `requirements-dev.txt`, which already includes `requirements.txt`:

```powershell
cd services\api
pip install -r requirements-dev.txt
pytest -q
```

Extension typecheck/build:

```powershell
cd apps\browser-extension
npm run typecheck
npm run build
```

## Android / Termux

Setting up on a phone for the first time? See
[docs/MOBILE_SETUP_GUIDE.md](docs/MOBILE_SETUP_GUIDE.md) — a from-scratch
walkthrough with the reasoning behind each step. The quick version, from a
checkout on the device:

```bash
bash scripts/termux-install.sh          # install runtime + deps, build the web UI
bash scripts/termux-doctor.sh --all     # verify the runtime (M1) and backend readiness (M2)
pocketdl                                # start the backend
```

The installer runs in place against the checkout — it does not clone, copy or
delete the repository. Update with `git pull` and re-run it. Configuration is
written to `~/.pocketdl/.env`, outside the repository, and downloads default to
`/sdcard/Download/PocketDL`.

`termux-doctor.sh` exits non-zero when an M1 runtime check fails, so it can gate
the later milestones. See [docs/termux.md](docs/termux.md) for the compact
reference, including the background-service (M6) and browser-extension (M5)
setup this guide's quick version above skips.

## Versioning

- v0.1.x: local downloader foundation, queue, filenames, diagnostics, analysis.
- v0.2.x: browser capture + captured media download path + capture metadata/UX
  hardening, plus the Android/Termux deployment baseline (current).
- v0.3.x: richer format selection, real-time progress, browser-session options and cross-browser work.
- v0.4.x: Android/Termux productization — background service, share target, notifications.
