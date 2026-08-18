#!/data/data/com.termux/files/usr/bin/bash
# PocketDL — supervised background service.
#
# Runs the backend under a restart-with-backoff loop and holds a Termux
# wake-lock so Android does not suspend the process while it is backgrounded
# (there is no foreground activity or notification keeping it alive
# otherwise). Intended to be started by the Termux:Boot hook installed via
# termux-boot-install.sh, but can also be run directly to test without a
# reboot: `bash scripts/pocketdl-service.sh`.
#
# Stop with scripts/pocketdl-stop.sh, or send SIGTERM to the PID in
# ~/.pocketdl/run/service.pid.
set -uo pipefail

# The Termux:Boot hook invokes this script through a symlink
# (~/.termux/boot/pocketdl-start -> this file). dirname on ${BASH_SOURCE[0]}
# would resolve against the symlink's own location, not its target, and land
# outside the repo entirely. Resolve the real path first, same as scripts/pocketdl.
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
REPO_DIR="$(cd "$(dirname "$SELF")/.." && pwd)"
RUN_DIR="$HOME/.pocketdl/run"
PID_FILE="$RUN_DIR/service.pid"
STATUS_FILE="$RUN_DIR/status"
LOG_FILE="$RUN_DIR/service.log"
LOG_MAX_BYTES=$((2 * 1024 * 1024))

mkdir -p "$RUN_DIR"

rotate_log_if_needed() {
  [ -f "$LOG_FILE" ] || return 0
  local size
  size=$(wc -c < "$LOG_FILE" 2>/dev/null || printf '0')
  if [ "${size:-0}" -ge "$LOG_MAX_BYTES" ]; then
    mv -f "$LOG_FILE" "$LOG_FILE.1"
  fi
}

log() {
  rotate_log_if_needed
  printf '%s %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG_FILE"
}

if [ -f "$PID_FILE" ]; then
  existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
    log "already running as pid $existing_pid, not starting a second instance"
    printf 'PocketDL service already running (pid %s). See %s\n' "$existing_pid" "$LOG_FILE"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

child_pid=''
rotator_pid=''

forward_and_exit() {
  local sig="$1"
  log "received $sig, stopping"
  [ -n "$child_pid" ] && kill "-$sig" "$child_pid" 2>/dev/null
  exit 0
}

cleanup() {
  [ -n "$child_pid" ] && kill -TERM "$child_pid" 2>/dev/null
  [ -n "$rotator_pid" ] && kill "$rotator_pid" 2>/dev/null
  if command -v termux-wake-unlock >/dev/null 2>&1; then
    termux-wake-unlock 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  log 'service stopped'
}

trap 'forward_and_exit TERM' TERM
trap 'forward_and_exit INT' INT
trap cleanup EXIT

echo $$ > "$PID_FILE"
log "service starting (pid $$, repo $REPO_DIR)"

if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock
  log 'wake-lock acquired'
else
  log 'termux-wake-lock not available; Android may suspend this process in the background'
fi

# Backend log volume (every request/download) is unbounded between restarts,
# so rotate on a timer too, not only around a restart.
(
  while true; do
    sleep 3600
    rotate_log_if_needed
  done
) &
rotator_pid=$!

backoff=2
max_backoff=60
min_uptime_for_reset=30

while true; do
  start_ts=$(date +%s)
  log 'starting backend'
  bash "$REPO_DIR/scripts/start.sh" >> "$LOG_FILE" 2>&1 &
  child_pid=$!
  printf 'started_at=%s\nservice_pid=%s\nbackend_pid=%s\n' "$start_ts" "$$" "$child_pid" > "$STATUS_FILE"

  wait "$child_pid"
  code=$?
  child_pid=''
  end_ts=$(date +%s)
  uptime=$((end_ts - start_ts))
  log "backend exited (code=$code, uptime=${uptime}s)"

  if [ "$uptime" -ge "$min_uptime_for_reset" ]; then
    backoff=2
  fi
  log "restarting in ${backoff}s"
  sleep "$backoff"
  backoff=$((backoff * 2))
  [ "$backoff" -gt "$max_backoff" ] && backoff=$max_backoff
done
