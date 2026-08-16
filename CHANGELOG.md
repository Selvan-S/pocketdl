# Changelog

## 0.2.2

- Fixed historical capture duplicates by normalizing and re-keying captures during startup.
- Added captured media metadata: duration, size, dimensions, and metadata status.
- Added background ffprobe metadata enrichment using captured request context.
- Filtered obvious media segments from browser capture and prefer manifest captures once HLS/DASH is seen.
- Added media-size reporting from browser response Content-Length when available.
- Made capture cards and major web sections collapsible to reduce scrolling.
- Added duration/size information and collapsible capture rows to the browser extension popup.
- Added warnings for suspiciously short direct-media captures.
