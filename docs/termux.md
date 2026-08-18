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
2. Install the M1 runtime — git, Python, Node.js LTS, FFmpeg, aria2.
3. Install the build toolchain needed to compile the Python dependencies.
4. Create `services/api/.venv` and install `services/api/requirements.txt`.
5. Write `~/.pocketdl/.env` targeting `/sdcard/Download/PocketDL`.
6. Build the web UI from the committed npm lockfile.
7. Symlink a `pocketdl` launcher into `$PREFIX/bin`.

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

## Configuration

`~/.pocketdl/.env` lives outside the repository so `git pull` never clobbers it.
The installer backs up any existing file to `~/.pocketdl/.env.bak` before
rewriting it. The download directory can also be changed from the PocketDL UI,
which persists the value in the database and overrides the `.env` default.

## Security

The API binds to `127.0.0.1` by default. Do not expose it to a LAN or the public
internet until authentication and an explicit bind setting are added.
