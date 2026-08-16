#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

APP_DIR="$HOME/.pocketdl"
REPO_DIR="$APP_DIR/app"
PORT="8787"

printf '\nPocketDL installer\n\n'

termux-setup-storage
pkg update -y
pkg install -y python ffmpeg aria2 git nodejs

mkdir -p "$APP_DIR"

python -m pip install --upgrade pip
python -m pip install --upgrade 'yt-dlp[default]' 'fastapi<1.0' 'uvicorn[standard]<1.0' 'pydantic>=2.11,<3.0' 'pydantic-settings>=2.10,<3.0' 'aiosqlite>=0.21,<1.0'

cat > "$APP_DIR/.env" <<ENV
APP_VERSION=0.1.0
HOST=127.0.0.1
PORT=$PORT
DATABASE_PATH=$APP_DIR/pocketdl.db
DOWNLOAD_DIRECTORY=/sdcard/Download
MAX_CONCURRENT_DOWNLOADS=2
DEFAULT_CONCURRENT_FRAGMENTS=8
DEFAULT_RETRIES=10
ENV

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rm -rf "$REPO_DIR"
mkdir -p "$REPO_DIR"
cp -R "$SOURCE_DIR/services" "$SOURCE_DIR/apps" "$SOURCE_DIR/scripts" "$SOURCE_DIR/package.json" "$REPO_DIR/"

cd "$REPO_DIR/apps/web"
npm install --no-audit --no-fund
npm run build

printf 'PocketDL installed at %s\n' "$APP_DIR"
printf 'Start it with: %s/scripts/pocketdl\n' "$REPO_DIR"
