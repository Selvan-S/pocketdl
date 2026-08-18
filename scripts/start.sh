#!/data/data/com.termux/files/usr/bin/bash
# Start the PocketDL backend from this checkout using its virtualenv.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO_DIR/services/api"

# Config lives outside the repository so `git pull` never clobbers it. Set
# POCKETDL_VENV there to point at a virtualenv kept outside the default layout.
set -a
if [ -f "$HOME/.pocketdl/.env" ]; then
  . "$HOME/.pocketdl/.env"
fi
set +a

# bin/python on Termux; Scripts/python.exe when this repo is checked out on the
# Windows development machine.
VENV_PYTHON=''
for candidate in \
  "${POCKETDL_VENV:-}/bin/python" \
  "${POCKETDL_VENV:-}/Scripts/python.exe" \
  "$API_DIR/.venv/bin/python" \
  "$API_DIR/.venv/Scripts/python.exe" \
  "$REPO_DIR/.venv/bin/python" \
  "$REPO_DIR/.venv/Scripts/python.exe" ; do
  case "$candidate" in /bin/python|/Scripts/python.exe) continue ;; esac
  [ -x "$candidate" ] && { VENV_PYTHON="$candidate"; break; }
done

if [ -z "$VENV_PYTHON" ]; then
  printf 'No virtualenv found. Looked in:\n' >&2
  [ -n "${POCKETDL_VENV:-}" ] && printf '  %s (POCKETDL_VENV)\n' "$POCKETDL_VENV" >&2
  printf '  %s\n  %s\n' "$API_DIR/.venv" "$REPO_DIR/.venv" >&2
  printf 'Run scripts/termux-install.sh, or set POCKETDL_VENV in ~/.pocketdl/.env.\n' >&2
  exit 1
fi

cd "$API_DIR"
export PYTHONPATH="$API_DIR"
exec "$VENV_PYTHON" -m app.main
