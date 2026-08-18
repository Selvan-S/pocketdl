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
# python/nodejs-lts/ffmpeg/git are the M1 runtime. The remainder is the build
# toolchain: Termux uses Bionic rather than glibc, so manylinux wheels do not
# apply and pydantic-core, uvloop, httptools, watchfiles, curl_cffi, brotli and
# pycryptodomex are compiled from source here.
pkg install -y \
  git \
  python \
  python-pip \
  nodejs-lts \
  ffmpeg \
  aria2 \
  clang \
  make \
  binutils \
  pkg-config \
  rust \
  libffi \
  openssl

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
chmod +x "$REPO_DIR/scripts/pocketdl" "$REPO_DIR/scripts/start.sh" "$REPO_DIR/scripts/termux-doctor.sh"

printf '\nPocketDL installed.\n'
printf '  Config:    %s\n' "$ENV_FILE"
printf '  Downloads: %s\n' "$DOWNLOAD_DIR"
printf '  Start:     pocketdl\n'
printf '  Verify:    bash %s/scripts/termux-doctor.sh --all\n' "$REPO_DIR"
printf '  Then open: http://127.0.0.1:%s/  (Swagger at /docs)\n\n' "$PORT"
