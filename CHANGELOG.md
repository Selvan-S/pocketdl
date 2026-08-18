# Changelog

## Unreleased — Android/Termux M1–M6

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
