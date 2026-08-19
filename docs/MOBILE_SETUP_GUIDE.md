# PocketDL — Mobile Setup Guide (From Scratch)

This is a walkthrough for setting up PocketDL on an Android phone that has
never had Termux on it before. It explains *why* each step exists, not just
what to type, and separates one-time setup from the commands you'll actually
use day to day.

For a more compact reference (once you already know the shape of this),
see [termux.md](termux.md). This guide is the narrated version of the same
ground, written for a first-time setup.

## What you're setting up

```text
Android
├── Termux                        one-time install, from F-Droid
│   ├── Python, Node.js, FFmpeg   the M1 runtime
│   ├── PocketDL backend          FastAPI, in a virtualenv
│   └── PocketDL PWA              built once, served by the backend
├── Termux:Boot                   optional — autostart after reboot
└── A Chromium browser            optional — browser capture (HLS/DASH)
```

Everything runs on-device. Nothing is sent anywhere except to the sites you
paste URLs from.

---

## Prerequisites — apps to install first

Install these from **F-Droid**, not the Play Store. This matters: Google's
background-execution policy changes broke the Play Store builds of Termux and
Termux:Boot years ago, and they were never fixed there — the maintainers
publish to F-Droid (and GitHub) instead. If you install from the Play Store,
things will break in ways that look like PocketDL's fault but aren't.

1. **F-Droid** itself, if you don't have it: <https://f-droid.org/>
2. **Termux** — the terminal PocketDL's backend and its dependencies run in.
3. **Termux:Boot** — only if you want PocketDL to start automatically after a
   reboot (Part 5 below). Skip it if you're fine starting it manually.
4. A Chromium-based browser that supports installing extensions from a file —
   only if you want browser capture for HLS/DASH sites yt-dlp can't reach
   directly (Part 6 below). This project has been used successfully with
   **Quetta**. Skip it if you only need standard downloads.

You do not need Git, Python, Node, or FFmpeg installed as separate apps —
those go *inside* Termux in the next part, not as standalone Android apps.

---

## Part 1 — One-time Termux runtime setup (M1)

Open Termux and run:

```bash
termux-setup-storage
```

**Why:** Termux is sandboxed from the rest of Android by default and cannot
see `/sdcard` (where your Downloads live) without this. It will prompt an
Android permission dialog — allow it. You only do this once per install.

```bash
pkg update && pkg upgrade
```

**Why:** freshly installed Termux ships with a package index that's often
already stale. Skipping this occasionally causes confusing install failures
later that look unrelated to PocketDL.

```bash
pkg install -y git
```

**Why:** you need `git` to clone the repository at all. (The installer script
in Part 2 will install PocketDL's other runtime dependencies — Python,
Node.js, FFmpeg — for you; you don't need to install those by hand.)

---

## Part 2 — Get the code and install PocketDL (M2 + M3)

```bash
git clone <repository-url> ~/pocketdl
cd ~/pocketdl
bash scripts/termux-install.sh
```

**Why `~/pocketdl`:** the scripts assume nothing about *where* you clone it —
they resolve their own location — but `~/pocketdl` is what every example in
this guide and in `termux.md` uses, so stick with it unless you have a reason
not to.

**What `termux-install.sh` actually does**, in order:

1. Requests storage access again (harmless if already granted).
2. Installs Termux packages: `python`, `ffmpeg`, plus a full C/Rust build
   toolchain (`clang`, `make`, `rust`, `pkg-config`, `libffi`, `openssl`, ...).
   **Why the toolchain:** Termux runs on Bionic, not glibc, so the prebuilt
   Python wheels most `pip install`s use elsewhere don't apply here. Several
   of PocketDL's dependencies — `pydantic-core`, `curl_cffi`, `uvloop`,
   `httptools`, `watchfiles` — get compiled from source on your device. This
   is the slowest part of the install; if something in this step fails, the
   failure is almost always in one of those packages, not in PocketDL itself.
3. Detects your existing Node.js rather than replacing it. **Why:** Termux
   ships `nodejs` and `nodejs-lts` as *mutually exclusive* packages —
   installing one silently removes the other. If you use Termux for other
   projects that depend on a specific Node build, this script won't touch it
   as long as it's v20+.
4. Creates a Python virtualenv at `services/api/.venv` and installs from
   `requirements.txt` into it — never into Termux's global Python. **Why:**
   this keeps PocketDL's dependencies isolated from anything else you run in
   Termux, the same way you'd use a venv on desktop.
5. Writes `~/.pocketdl/.env` (outside the repo, so `git pull` never touches
   it) pointing downloads at `/sdcard/Download/PocketDL`.
6. Builds the web UI (`npm ci && npm run web:build`) so the backend can serve
   it directly — see Part 4.
7. Symlinks a `pocketdl` command into Termux's `bin/`, so you can just type
   `pocketdl` from anywhere afterward instead of the full script path.

This step can take several minutes the first time (mostly step 2, compiling
native dependencies). Re-running it later after a `git pull` is fast, since
most of it is idempotent.

---

## Part 3 — Verify (do this before assuming anything works)

```bash
bash scripts/termux-doctor.sh --all
```

**Why:** rather than guessing whether the install worked, this mechanically
checks every piece: Termux itself, git/python/node/npm/ffmpeg/ffprobe on
PATH, storage access, that `/sdcard/Download/PocketDL` is actually writable,
that no source file is missing from the checkout (a real incident from this
project's history — see `docs/docs_POCKETDL_PROJECT_STATUS.md`), the
virtualenv and every Python dependency, and whether the web UI actually got
built. It exits non-zero if anything in the base runtime failed, so you can
tell at a glance whether you're ready to move on.

You should see `M1 PASS` and `M2 readiness: OK.` If not, fix what it reports
before continuing — everything downstream assumes this passed.

---

## Part 4 — Run it once, manually

```bash
pocketdl
```

This starts the backend in the foreground, attached to this terminal session
— closing Termux (or this session) stops it. That's fine for now; Part 5
covers making it persistent.

Open `http://127.0.0.1:8787/` in your Android browser. You should see the
PocketDL UI itself — not a 404. **Why this matters:** the backend serves the
built web UI directly from `apps/web/dist`; if that build ever fails silently,
you'd get a working API with no UI, which looks broken but isn't the API's
fault. `http://127.0.0.1:8787/docs` gets you the raw API (Swagger) if you
ever need it.

Paste a normal video URL and try a download. Confirm the file actually lands
in `/sdcard/Download/PocketDL` — check with a file manager app, not just the
PocketDL UI, the first time.

Stop it with Ctrl+C, or close the terminal.

---

## Part 5 — Optional: start automatically after reboot (M6)

Skip this if you're fine running `pocketdl` manually each time you want it.

This needs the **Termux:Boot** app from the prerequisites section — Android
does not let Termux itself react to a reboot; a separate app with that
specific permission is required.

```bash
bash scripts/termux-boot-install.sh
```

This symlinks `~/.termux/boot/pocketdl-start` to
`scripts/pocketdl-service.sh` — a supervisor, not the plain backend — so
`git pull` updates its behavior automatically without re-running this
install step.

**What the supervisor adds over just running `pocketdl` directly:**
- Holds a `termux-wake-lock` so Android doesn't suspend it while backgrounded.
- If the backend crashes or exits, it restarts automatically (with backoff:
  2s, 4s, 8s... capped at 60s, resetting once a run has stayed up 30s+, so a
  genuine crash loop doesn't hammer your battery).
- Refuses to start a second copy of itself if one is already running.

**Test it without a real reboot first** — this matters, because the one
real bug this exact setup hit during development only showed up through the
boot-hook symlink, not through running the script directly:

```bash
bash ~/.termux/boot/pocketdl-start &
bash scripts/pocketdl-status.sh
```

If `pocketdl-status.sh` shows the backend actually running and reachable,
**then** do a real reboot and check again — that's the real test, since
Termux:Boot itself (the app registering for the boot event, any OEM
battery-optimization restrictions) is only exercised by an actual reboot.

On some phones (MIUI, OxygenOS, One UI, and others) you'll also need to
manually allow "autostart" or disable battery optimization for both Termux
and Termux:Boot in Android's own app settings — no script can grant that
permission on your behalf; the OS blocks the boot receiver regardless of what
the app does until you do.

---

## Part 6 — Optional: browser capture for HLS/DASH (M5)

Skip this if standard downloads (Part 4) cover what you need. This is for
sites where the page works in a browser but yt-dlp can't reproduce the
request — see `CLAUDE.md`'s "Important proven behavior" section for why that
happens and why this is the intended fix rather than something to work around
with more yt-dlp flags.

Your mobile Chromium browser (Quetta, confirmed working) generally does
**not** offer desktop Chrome's "Load unpacked" folder picker — and even if it
did, Termux's home directory is a private app sandbox other apps can't browse
into. Instead, package the extension as a zip:

```bash
bash scripts/extension-package.sh
```

This rebuilds the extension and writes `apps/browser-extension/pocketdl-capture.zip`.
If you already granted storage access in Part 1, it also copies that zip to
`~/storage/shared/pocketdl-capture.zip` — that's the copy your browser's file
picker can actually reach (as "Internal storage/pocketdl-capture.zip"),
since it can't see into Termux directly either.

In your browser: open its extensions page → install/load from file → pick
that zip.

**Using it:** open a page with the video playing in that browser, let it
start playing so the extension observes the manifest/media request, then
check the **Browser captures** section in the PocketDL UI and download from
there.

**After an extension code update:** re-run `extension-package.sh`, then
reload the extension from the same file in your browser rather than
reinstalling from scratch — check your browser's own extensions page for a
reload action.

---

## Day-to-day commands (the ones you'll actually use often)

Assuming Part 5's autostart is set up, you mostly won't run anything — the
backend is already running after every reboot. These are for when you do:

| Command | When | Why |
|---|---|---|
| `bash scripts/pocketdl-status.sh` | Checking whether it's actually up | Live check: service running, backend running, uptime, whether the API actually answers (not just whether a process exists), autostart configured. |
| `bash scripts/pocketdl-stop.sh` | Before a manual restart, or to free the port/battery | Stops it cleanly — releases the wake-lock and removes the PID file, rather than leaving a zombie process. |
| `pocketdl` | Not using autostart, or want it in the foreground to watch logs live | Starts the plain backend, attached to your terminal. |
| `tail -f ~/.pocketdl/run/service.log` | Watching what the supervised service is doing right now | The supervisor's own log — restarts, crashes, backoff timing. Rotates at 2MB (one backup kept, `.log.1`), so it's safe to tail long-term. |

---

## Updating PocketDL after a code change

```bash
cd ~/pocketdl
git pull
```

Then, depending on what changed:

| What changed | What to run | Why |
|---|---|---|
| Backend Python code only | Nothing extra — just restart | `python -m app.main` re-imports fresh source on every start; no build step for Python. |
| `services/api/requirements.txt` changed | `services/api/.venv/bin/python -m pip install -r services/api/requirements.txt` | New/changed dependencies need installing into the venv; a plain `git pull` doesn't do this for you. |
| Anything under `apps/web/` (the PWA) | `npm run web:build` | The backend serves a pre-built `dist/`, not your source files live — a UI change is invisible until rebuilt. |
| Anything under `apps/browser-extension/` | `bash scripts/extension-package.sh`, then reload it in your browser | Same reasoning — the browser has its own installed copy, not a live view of the source. |
| If you're using autostart (Part 5) | `bash scripts/pocketdl-stop.sh` then let the boot hook or a manual `pocketdl` start it again | The already-running supervisor process won't pick up new code by itself — it needs to actually restart. |

**When in doubt**, running the full installer again is safe and mostly a
no-op if nothing changed:

```bash
bash scripts/termux-install.sh
```

---

## Troubleshooting toolkit (commands you'll only need occasionally)

Reach for these when something's actually wrong, not as routine maintenance.

| Command | When to use it | What it tells you |
|---|---|---|
| `bash scripts/termux-doctor.sh --all` | Anything seems broken and you don't know where to start | Full runtime + backend readiness + M6 setup check, in one pass — usually narrows down the problem immediately. |
| `tail -n 60 ~/.pocketdl/run/service.log` | The service is running but the backend keeps failing/restarting | The actual error, not just "it crashed" — e.g. a real bug this exact setup hit: the service resolving its own location incorrectly through the boot-hook symlink, visible directly in this log as a `No such file or directory` on every restart attempt. |
| `ps aux \| grep app.main` | Suspecting a stale/duplicate backend process (e.g. after a crashed session) | Whether an old process is still bound to the port, blocking a new one from starting. |
| `curl -s http://127.0.0.1:8787/api/system/status` | Downloads are failing and you're not sure if it's PocketDL or a missing dependency | Reports the actual `yt_dlp_version`/`ffmpeg_version`/`aria2_version` the *running backend* can see — `null` for any of these means that tool isn't reachable at runtime even if `pkg` shows it installed. |
| `cat ~/.pocketdl/.env` | Downloads are landing in the wrong place, or the port seems wrong | Shows the actual config in effect. Remember the PocketDL UI's own Settings can override `DOWNLOAD_DIRECTORY` here via the database — the UI's reported path is more authoritative than this file if they disagree. |

---

## Reference — where things actually live

| Path | What it is |
|---|---|
| `~/pocketdl` | The git checkout. Everything version-controlled lives here. |
| `~/pocketdl/services/api/.venv` | The backend's Python virtualenv. Not in git; recreated by the installer. |
| `~/pocketdl/apps/web/dist` | The built PWA the backend serves at `/`. Not in git; rebuilt by `npm run web:build`. |
| `~/.pocketdl/.env` | Runtime config (port, database path, download directory). Outside the repo on purpose, so `git pull` never overwrites your settings. |
| `~/.pocketdl/pocketdl.db` | SQLite database — download history, capture history, persisted settings. |
| `~/.pocketdl/run/` | The supervised service's PID file, status file, and rotating log. Only exists if you've used Part 5. |
| `~/.termux/boot/pocketdl-start` | The Termux:Boot hook (a symlink). Only exists if you've run `termux-boot-install.sh`. |
| `/sdcard/Download/PocketDL` | Default download location. Configurable from the PocketDL UI's Settings, which takes priority over `.env`. |
| `http://127.0.0.1:8787/` | The app itself, once running. |
| `http://127.0.0.1:8787/docs` | Raw API reference (Swagger). |
