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
