#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
set -a
if [ -f "$HOME/.pocketdl/.env" ]; then
  . "$HOME/.pocketdl/.env"
fi
set +a
cd "$HOME/.pocketdl/app/services/api"
export PYTHONPATH="$PWD"
exec python -m app.main
