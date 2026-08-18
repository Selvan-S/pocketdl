# PocketDL — Claude Development Instructions

## Role
You are continuing development of PocketDL, a local/self-hosted downloader built for desktop development first and Android/Termux deployment later.

Treat this as a real software project. Maintainable architecture, tests, migrations, type safety, observability, and backwards compatibility matter more than quickly adding features.

## Current state
- Current desktop milestone: v0.2.2 core workflow is working.
- Browser capture works for HLS/direct-media sources.
- Captured downloads work.
- Normal yt-dlp downloads work.
- UI-configurable download location works.
- Collapsible capture sections/cards work.
- Duration metadata is generally accurate.
- Capture duplicates still exist in some cases.
- Captured media size is not yet reliable.
- Mobile/Termux deployment is the current active workstream.
- Do not start v0.3 feature work until the mobile baseline is working, unless explicitly requested.

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
1. Duplicate captured cards still appear for some sites.
   - Signed URLs change between requests.
   - Some players issue multiple logically equivalent requests.
   - Normalization/deduplication is not yet perfect.
2. Captured media size is unreliable.
   - Duration is generally accurate.
   - Exact size is not always knowable before downloading, especially for HLS/DASH.
3. Very short/wrong captures can occur.
   - Example: a legitimate-looking media request may represent ~2 seconds and a few KB.
   - The UI should help users identify suspicious captures.
4. Browser/mobile extension compatibility is not yet proven on Android.
5. Background service / Termux:Boot is not yet implemented.

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
The immediate priority is Android/Termux deployment and testing, not v0.3 format analysis.
After Android works end-to-end, return to the known duplicate-capture and media-size issues, then move to richer format/quality analysis.
