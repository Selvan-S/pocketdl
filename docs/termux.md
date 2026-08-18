# Termux installation

PocketDL follows the official yt-dlp Android path: Termux + Python + yt-dlp, with
FFmpeg for post-processing and captured HLS/DASH downloads. yt-dlp also supports
concurrent HLS/DASH fragments and optional aria2 as an external downloader.

## Install

Clone the repository on the device, then run the installer from the checkout:

```bash
git clone <repository-url> ~/pocketdl
cd ~/pocketdl
bash scripts/termux-install.sh
```

The installer runs **in place**. It does not clone, copy or delete the
repository, so `git pull && bash scripts/termux-install.sh` is the update path.

It will:

1. Request Termux storage permission (`termux-setup-storage`).
2. Install the M1 runtime — git, Python, FFmpeg — and the build toolchain.
3. Create `services/api/.venv` and install `services/api/requirements.txt`.
4. Write `~/.pocketdl/.env` targeting `/sdcard/Download/PocketDL`.
5. Build the web UI from the committed npm lockfile.
6. Symlink a `pocketdl` launcher into `$PREFIX/bin`.

## How this coexists with your other projects

The intended layout is device-global tools plus a per-project virtualenv:

```text
Termux global (pkg)          Projects
├── python                   ├── PocketDL
├── nodejs                   │   └── services/api/.venv
├── ffmpeg                   ├── Project B
├── git                      │   └── .venv
└── rust                     └── Project C
                                 └── .venv
```

The installer follows this: `pkg` for shared tools, a virtualenv for PocketDL's
Python dependencies. It never installs Python packages globally.

**Node is treated as yours.** Termux ships `nodejs` and `nodejs-lts` as mutually
exclusive packages — installing one removes the other. The installer therefore
keeps whatever Node you already have as long as it is v20 or newer, and only
installs `nodejs-lts` when no Node is present. If your Node is too old it stops
and asks you to upgrade it yourself, rather than swapping a global tool other
projects depend on.

**A virtualenv elsewhere.** If you keep virtualenvs outside the default layout,
set `POCKETDL_VENV` in `~/.pocketdl/.env`:

```bash
POCKETDL_VENV=/data/data/com.termux/files/home/.venvs/pocketdl
```

`start.sh` and `termux-doctor.sh` check `POCKETDL_VENV` first, then
`services/api/.venv`, then a repo-root `.venv`.

## Why a build toolchain is required

Termux uses Bionic rather than glibc, so manylinux wheels do not apply. Several
runtime dependencies are compiled from source on the device: `pydantic-core` and
`watchfiles` (Rust), and `uvloop`, `httptools`, `curl_cffi`/`cffi`, `brotli` and
`pycryptodomex` (C). That is why the installer adds `rust`, `clang`, `make`,
`binutils`, `pkg-config`, `libffi` and `openssl` beyond the M1 runtime itself.

This is the slowest step of the install. If a build fails, the failure is in one
of those packages, not in PocketDL.

## Verify

```bash
bash scripts/termux-doctor.sh          # M1 runtime only
bash scripts/termux-doctor.sh --all    # also report M2 backend readiness
```

The doctor exits non-zero if an M1 check fails, so it can gate later milestones.
It checks Termux itself, git/python/node/npm/ffmpeg/ffprobe, Android storage
access, that `/sdcard/Download/PocketDL` is writable, and that the backend source
files that a previous `.gitignore` incident once omitted are actually present in
the checkout.

M2 reporting additionally checks the virtualenv, the importability of fastapi,
uvicorn, pydantic, aiosqlite, yt_dlp and curl_cffi, and whether `apps/web/dist`
has been built. Without `apps/web/dist` the backend serves the API but returns
404 at `/`.

## Run

```bash
pocketdl
```

Then open `http://127.0.0.1:8787/` in the Android browser; Swagger is at
`/docs`, and `/api/system/status` reports the yt-dlp, FFmpeg and aria2 versions
the backend can actually see.

## Background service and autostart (M6)

Running `pocketdl` directly keeps the backend attached to that terminal
session — closing it stops the backend. For a persistent background service
that survives a reboot, use the supervisor instead.

**Enable autostart.** This needs the separate **Termux:Boot** app — Android
does not let Termux itself receive the boot-completed event, so a dedicated
app with that permission is required:

1. Install **Termux:Boot** from **F-Droid** (not the Play Store build, which is
   frequently stale): https://f-droid.org/packages/com.termux.boot/
2. Open it once after installing so it registers.
3. On some phones (MIUI, OxygenOS, One UI, ...) also allow autostart / disable
   battery optimization for Termux and Termux:Boot in Android's app settings —
   the OS otherwise blocks the boot receiver regardless of what the app does.
4. Run:
   ```bash
   bash scripts/termux-boot-install.sh
   ```
   This symlinks `~/.termux/boot/pocketdl-start` to
   `scripts/pocketdl-service.sh`, so `git pull` updates its behavior without
   re-running the installer.

**What the service does.** `scripts/pocketdl-service.sh` holds a
`termux-wake-lock` so Android does not suspend a backgrounded process, and
restarts the backend with exponential backoff (2s up to 60s) if it exits or
crashes. It refuses to start a second instance if one is already running.

**Check it.**
```bash
bash scripts/pocketdl-status.sh
```
Reports whether the service and backend are running, uptime, whether the
backend API actually answers, and whether autostart is configured. This is a
live-state check; `termux-doctor.sh --all`'s M6 section checks setup
(wake-lock tool present, boot hook installed, Termux:Boot app detected —
best-effort, since package visibility is restricted on some Android versions)
rather than duplicating this.

**Stop it.**
```bash
bash scripts/pocketdl-stop.sh
```

**Test without rebooting**, once the boot hook is installed:
```bash
bash ~/.termux/boot/pocketdl-start &
bash scripts/pocketdl-status.sh
```

Service logs are at `~/.pocketdl/run/service.log`, rotated once they exceed
2MB (one backup kept, `.log.1`).

## Configuration

`~/.pocketdl/.env` lives outside the repository so `git pull` never clobbers it.
The installer backs up any existing file to `~/.pocketdl/.env.bak` before
rewriting it. The download directory can also be changed from the PocketDL UI,
which persists the value in the database and overrides the `.env` default.

## Security

The API binds to `127.0.0.1` by default. Do not expose it to a LAN or the public
internet until authentication and an explicit bind setting are added.
