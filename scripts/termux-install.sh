#!/data/data/com.termux/files/usr/bin/bash
# PocketDL — Termux installer.
#
# Runs in place against this checkout; it does not clone, copy or delete the
# repository. Update the code with `git pull` and re-run this script.
#
# Dependencies come from services/api/requirements.txt and the npm lockfile so
# that Android and desktop resolve the same versions. Do not add package
# installs here that are not declared in those files.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO_DIR/services/api"
VENV_DIR="$API_DIR/.venv"
CONFIG_DIR="$HOME/.pocketdl"
ENV_FILE="$CONFIG_DIR/.env"
PORT="${POCKETDL_PORT:-8787}"

# Must match _default_download_directory() in services/api/app/core/config.py.
DOWNLOAD_DIR='/sdcard/Download/PocketDL'

printf '\nPocketDL installer\n'
printf 'Repository: %s\n\n' "$REPO_DIR"

if [ -z "${PREFIX:-}" ] || [ "${PREFIX#/data/data/com.termux}" = "${PREFIX}" ]; then
  printf 'This installer targets Termux on Android (PREFIX=%s).\n' "${PREFIX:-unset}" >&2
  exit 1
fi

printf '==> Requesting Android storage permission\n'
# Safe to re-run; it is a no-op once the permission has been granted.
termux-setup-storage || true

printf '==> Installing Termux packages\n'
pkg update -y

# These are shared, device-global tools, deliberately installed with pkg rather
# than vendored per project. git/python/ffmpeg are the M1 runtime; the rest is
# the build toolchain. Termux uses Bionic rather than glibc, so manylinux wheels
# do not apply and pydantic-core, uvloop, httptools, watchfiles, curl_cffi,
# brotli and pycryptodomex are compiled from source into the venv.
pkg install -y \
  git \
  python \
  ffmpeg \
  clang \
  make \
  binutils \
  pkg-config \
  rust \
  libffi \
  openssl

# Termux ships `nodejs` (current) and `nodejs-lts` as MUTUALLY EXCLUSIVE
# packages: installing one removes the other. Node is a device-global tool that
# other projects depend on, so never swap it out from under them. Only install
# when there is no usable Node already.
NODE_MIN_MAJOR=20
if command -v node >/dev/null 2>&1; then
  node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
  if [ "${node_major:-0}" -ge "$NODE_MIN_MAJOR" ]; then
    printf '    keeping existing Node %s (device-global, shared with other projects)\n' "$(node --version)"
  else
    printf '    Node %s is older than v%s and cannot build the web UI.\n' "$(node --version)" "$NODE_MIN_MAJOR" >&2
    printf '    Upgrade it yourself so you control which Termux node package wins:\n' >&2
    printf '      pkg install nodejs-lts   # or: pkg install nodejs\n' >&2
    exit 1
  fi
else
  printf '    no Node found; installing nodejs-lts\n'
  pkg install -y nodejs-lts
fi

# Optional. aria2 only accelerates direct downloads; python-pip is a separate
# package on some Termux versions and bundled with python on others.
for optional in aria2 python-pip; do
  pkg install -y "$optional" || printf '    optional package %s unavailable, continuing\n' "$optional"
done

printf '==> Creating Python virtualenv\n'
if [ ! -x "$VENV_DIR/bin/python" ]; then
  python -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel

printf '==> Installing backend dependencies from requirements.txt\n'
"$VENV_DIR/bin/python" -m pip install -r "$API_DIR/requirements.txt"

printf '==> Writing configuration\n'
mkdir -p "$CONFIG_DIR"
if [ -f "$ENV_FILE" ]; then
  cp "$ENV_FILE" "$ENV_FILE.bak"
  printf '    existing config backed up to %s\n' "$ENV_FILE.bak"
fi
cat > "$ENV_FILE" <<ENV
HOST=127.0.0.1
PORT=$PORT
DATABASE_PATH=$CONFIG_DIR/pocketdl.db
DOWNLOAD_DIRECTORY=$DOWNLOAD_DIR
MAX_CONCURRENT_DOWNLOADS=2
DEFAULT_CONCURRENT_FRAGMENTS=8
DEFAULT_RETRIES=10
ENV
mkdir -p "$DOWNLOAD_DIR"

printf '==> Building the web UI\n'
cd "$REPO_DIR"
# npm ci installs exactly what the committed lockfile pins, so Android matches
# the desktop tree. Fall back to npm install only if the lockfile is absent.
if [ -f package-lock.json ]; then
  npm ci --no-audit --no-fund
else
  npm install --no-audit --no-fund
fi
npm run web:build

printf '==> Installing the launcher\n'
mkdir -p "$PREFIX/bin"
ln -sf "$REPO_DIR/scripts/pocketdl" "$PREFIX/bin/pocketdl"
chmod +x \
  "$REPO_DIR/scripts/pocketdl" \
  "$REPO_DIR/scripts/start.sh" \
  "$REPO_DIR/scripts/termux-doctor.sh" \
  "$REPO_DIR/scripts/pocketdl-service.sh" \
  "$REPO_DIR/scripts/pocketdl-stop.sh" \
  "$REPO_DIR/scripts/pocketdl-status.sh" \
  "$REPO_DIR/scripts/termux-boot-install.sh"

printf '\nPocketDL installed.\n'
printf '  Config:    %s\n' "$ENV_FILE"
printf '  Downloads: %s\n' "$DOWNLOAD_DIR"
printf '  Start:     pocketdl\n'
printf '  Verify:    bash %s/scripts/termux-doctor.sh --all\n' "$REPO_DIR"
printf '  Then open: http://127.0.0.1:%s/  (Swagger at /docs)\n\n' "$PORT"
printf 'Optional: start automatically after reboot (needs the separate\n'
printf 'Termux:Boot app from F-Droid):\n'
printf '  bash %s/scripts/termux-boot-install.sh\n\n' "$REPO_DIR"
