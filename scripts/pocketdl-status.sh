#!/data/data/com.termux/files/usr/bin/bash
# PocketDL — health/startup status indicator (M6).
#
# Reports whether the supervised service is running right now, whether the
# backend actually answers, and whether autostart-on-boot is configured.
# This is a live-state check; scripts/termux-doctor.sh checks setup/readiness
# instead and does not overlap with this.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$REPO_DIR/scripts/lib/venv.sh"

RUN_DIR="$HOME/.pocketdl/run"
PID_FILE="$RUN_DIR/service.pid"
STATUS_FILE="$RUN_DIR/status"
BOOT_LINK="$HOME/.termux/boot/pocketdl-start"

[ -f "$HOME/.pocketdl/.env" ] && set -a && . "$HOME/.pocketdl/.env" && set +a
PORT="${PORT:-8787}"
HOST="${HOST:-127.0.0.1}"

printf 'PocketDL status\n\n'

service_pid=''
if [ -f "$PID_FILE" ]; then
  service_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
fi

if [ -n "$service_pid" ] && kill -0 "$service_pid" 2>/dev/null; then
  printf 'Service:       running (pid %s)\n' "$service_pid"
  if [ -f "$STATUS_FILE" ]; then
    started_at=''
    backend_pid=''
    while IFS='=' read -r key value; do
      case "$key" in
        started_at) started_at="$value" ;;
        backend_pid) backend_pid="$value" ;;
      esac
    done < "$STATUS_FILE"
    if [ -n "$started_at" ]; then
      now=$(date +%s)
      uptime=$((now - started_at))
      printf 'Uptime:        %dh %dm %ds (started_at=%s epoch)\n' "$((uptime / 3600))" "$(((uptime % 3600) / 60))" "$((uptime % 60))" "$started_at"
    fi
    if [ -n "$backend_pid" ]; then
      if kill -0 "$backend_pid" 2>/dev/null; then
        printf 'Backend:       running (pid %s)\n' "$backend_pid"
      else
        printf 'Backend:       exited, service is restarting it (see log)\n'
      fi
    fi
  fi
else
  printf 'Service:       not running\n'
  printf '               start with: bash scripts/pocketdl-service.sh\n'
fi

if VENV_PYTHON="$(resolve_venv_python "$REPO_DIR")"; then
  health_json="$("$VENV_PYTHON" - "$HOST" "$PORT" <<'PY' 2>/dev/null
import sys, urllib.request, json
host, port = sys.argv[1], sys.argv[2]
try:
    with urllib.request.urlopen(f'http://{host}:{port}/api/health', timeout=3) as resp:
        print(resp.read().decode())
except Exception as exc:
    print(json.dumps({"error": str(exc)}))
PY
)"
  if printf '%s' "$health_json" | grep -q '"status"'; then
    printf 'Backend API:   reachable at http://%s:%s (%s)\n' "$HOST" "$PORT" "$health_json"
  else
    printf 'Backend API:   not reachable at http://%s:%s\n' "$HOST" "$PORT"
  fi
else
  printf 'Backend API:   cannot check (no virtualenv found)\n'
fi

printf '\n'
if command -v termux-wake-lock >/dev/null 2>&1; then
  printf 'Wake-lock:     tool available\n'
else
  printf 'Wake-lock:     termux-wake-lock not found (base Termux should provide it)\n'
fi

if [ -L "$BOOT_LINK" ] || [ -f "$BOOT_LINK" ]; then
  printf 'Boot autostart: configured (%s)\n' "$BOOT_LINK"
else
  printf 'Boot autostart: not configured — run scripts/termux-boot-install.sh\n'
fi

printf '\nLog: %s\n' "$RUN_DIR/service.log"
