#!/data/data/com.termux/files/usr/bin/bash
# Stop a PocketDL service started by pocketdl-service.sh (directly or via the
# Termux:Boot hook). Releasing the wake-lock and removing the PID file is
# handled by pocketdl-service.sh's own cleanup on SIGTERM.
set -uo pipefail

PID_FILE="$HOME/.pocketdl/run/service.pid"

if [ ! -f "$PID_FILE" ]; then
  printf 'PocketDL service is not running (no %s).\n' "$PID_FILE"
  exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
  printf 'PocketDL service is not running (stale %s).\n' "$PID_FILE"
  rm -f "$PID_FILE"
  exit 0
fi

printf 'Stopping PocketDL service (pid %s)...\n' "$pid"
kill -TERM "$pid"

for _ in $(seq 1 20); do
  kill -0 "$pid" 2>/dev/null || { printf 'Stopped.\n'; exit 0; }
  sleep 0.5
done

printf 'Service did not stop within 10s, sending SIGKILL.\n' >&2
kill -KILL "$pid" 2>/dev/null || true
rm -f "$PID_FILE"
