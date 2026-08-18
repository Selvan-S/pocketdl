# Changelog

## Unreleased — Android/Termux M1 baseline

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
