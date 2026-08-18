#!/data/data/com.termux/files/usr/bin/bash
# Start the PocketDL backend from this checkout using its virtualenv.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO_DIR/services/api"
VENV_PYTHON="$API_DIR/.venv/bin/python"

# Config lives outside the repository so `git pull` never clobbers it.
set -a
if [ -f "$HOME/.pocketdl/.env" ]; then
  . "$HOME/.pocketdl/.env"
fi
set +a

if [ ! -x "$VENV_PYTHON" ]; then
  printf 'No virtualenv at %s. Run scripts/termux-install.sh first.\n' "$API_DIR/.venv" >&2
  exit 1
fi

cd "$API_DIR"
export PYTHONPATH="$API_DIR"
exec "$VENV_PYTHON" -m app.main
