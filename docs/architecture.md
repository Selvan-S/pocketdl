# PocketDL Architecture

## Applications

```text
apps/
├── web/                    # React + TypeScript PWA
└── browser-extension/     # Chrome Manifest V3 capture extension

services/
└── api/                    # FastAPI application
```

## Backend layers

```text
api/
  routes + request/response schemas
        |
application/
  capture service
  download queue service
        |
domain/
  DownloadJob
  CapturedSource
  RequestContext
  ports / enums / errors
        |
infrastructure/
  SQLite repositories
  yt-dlp integration
  FFmpeg captured-media integration
```

## Source selection

A `DownloadJob` contains `source_type`:

- `standard`: use yt-dlp and its normal format/extractor path.
- `captured`: use the browser-provided media URL and request context with FFmpeg.

This keeps the browser-specific transport logic out of the normal yt-dlp service.

## Capture API

`POST /api/captures` accepts a browser-observed request. The payload is validated, sensitive authentication headers are rejected, and the result is persisted in SQLite.

`POST /api/captures/{id}/download` converts a captured source into a normal PocketDL queue job with `source_type=captured`.

## Security

The backend binds to loopback by default. Browser extension requests must include the PocketDL extension protocol header. CORS only allows the local web app and Chrome extension origins.

The extension never stores Cookie or Authorization values in v0.2.
