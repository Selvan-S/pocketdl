#!/data/data/com.termux/files/usr/bin/bash
# PocketDL — Android/Termux milestone verification.
#
# M1 checks the runtime only (Termux, git, python, node, npm, ffmpeg, storage).
# M2 checks are reported but never fail M1, so the milestones stay ordered:
# fix M1 first, then re-run to look at M2.
#
# Usage:
#   bash scripts/termux-doctor.sh          # M1 acceptance (exit 1 on failure)
#   bash scripts/termux-doctor.sh --all    # also report M2 readiness
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO_DIR/services/api"
VENV_DIR="$API_DIR/.venv"
CHECK_M2=0
[ "${1:-}" = "--all" ] && CHECK_M2=1

m1_failures=0
m2_failures=0

pass() { printf '  [ OK ]  %s\n' "$*"; }
warn() { printf '  [WARN]  %s\n' "$*"; }
fail() { printf '  [FAIL]  %s\n' "$*"; }

section() { printf '\n%s\n' "$*"; }

# Report a tool's version, or record a failure. Scope is "m1" or "m2".
require_tool() {
  local scope="$1" name="$2"; shift 2
  local path version
  path="$(command -v "$name" 2>/dev/null)"
  if [ -z "$path" ]; then
    fail "$name not found on PATH"
    if [ "$scope" = "m1" ]; then m1_failures=$((m1_failures + 1)); else m2_failures=$((m2_failures + 1)); fi
    return 1
  fi
  version="$("$@" 2>&1 | head -n 1)"
  pass "$name — ${version:-present} ($path)"
}

printf 'PocketDL Android/Termux doctor\n'
printf 'Repository: %s\n' "$REPO_DIR"

section 'M1 — Termux runtime'

IS_TERMUX=0
if [ -n "${PREFIX:-}" ] && [ "${PREFIX#/data/data/com.termux}" != "${PREFIX}" ]; then
  IS_TERMUX=1
  pass "Termux detected (PREFIX=$PREFIX)"
else
  fail "Not running under Termux (PREFIX=${PREFIX:-unset}). PocketDL's Android defaults key off this."
  m1_failures=$((m1_failures + 1))
fi

require_tool m1 git     git --version
require_tool m1 python  python --version
require_tool m1 node    node --version
require_tool m1 npm     npm --version
require_tool m1 ffmpeg  ffmpeg -version
require_tool m1 ffprobe ffprobe -version

# aria2 is an optional accelerator for direct downloads, never required.
if command -v aria2c >/dev/null 2>&1; then
  pass "aria2c — $(aria2c --version 2>&1 | head -n 1)"
else
  warn 'aria2c not found (optional: only speeds up direct downloads)'
fi

section 'M1 — Android storage access'

if [ "$IS_TERMUX" -eq 0 ]; then
  # Never probe Android paths on a non-Android host; it would create stray
  # directories on the developer machine. The Termux check above already failed.
  warn 'skipped: not running under Termux'
else

# termux-setup-storage creates ~/storage; /sdcard is the shared-storage symlink.
if [ -d "$HOME/storage/shared" ]; then
  pass "Termux storage granted (~/storage/shared)"
else
  fail 'Termux storage not granted. Run: termux-setup-storage'
  m1_failures=$((m1_failures + 1))
fi

# This must match _default_download_directory() in services/api/app/core/config.py.
DOWNLOAD_DIR='/sdcard/Download/PocketDL'
if mkdir -p "$DOWNLOAD_DIR" 2>/dev/null && [ -w "$DOWNLOAD_DIR" ]; then
  probe="$DOWNLOAD_DIR/.pocketdl-write-test"
  if printf 'ok' > "$probe" 2>/dev/null; then
    rm -f "$probe"
    pass "$DOWNLOAD_DIR is writable"
  else
    fail "$DOWNLOAD_DIR exists but is not writable"
    m1_failures=$((m1_failures + 1))
  fi
else
  fail "Cannot create $DOWNLOAD_DIR (storage permission missing?)"
  m1_failures=$((m1_failures + 1))
fi

fi  # IS_TERMUX

section 'M1 — Repository checkout integrity'

# Guards the prior incident where .gitignore omitted a real source file and
# Android failed at import time rather than at checkout time.
missing=0
for f in \
  services/api/app/main.py \
  services/api/app/application/downloads/service.py \
  services/api/app/application/downloads/strategy.py \
  services/api/app/application/downloads/errors.py \
  services/api/app/application/captures/service.py \
  services/api/requirements.txt ; do
  if [ ! -f "$REPO_DIR/$f" ]; then
    fail "missing source file: $f"
    missing=$((missing + 1))
  fi
done
if [ "$missing" -eq 0 ]; then
  pass 'all required backend source files present'
else
  m1_failures=$((m1_failures + missing))
fi

if [ "$CHECK_M2" -eq 1 ]; then
  section 'M2 — Backend readiness (reported, does not affect M1)'

  # Same resolution order as start.sh: POCKETDL_VENV override, then the default
  # layout, then a repo-root venv. bin/python on Termux, Scripts/python.exe when
  # the same repo is checked out on the Windows development machine.
  [ -f "$HOME/.pocketdl/.env" ] && . "$HOME/.pocketdl/.env"
  VENV_PYTHON=''
  for candidate in \
    "${POCKETDL_VENV:-}/bin/python" \
    "${POCKETDL_VENV:-}/Scripts/python.exe" \
    "$VENV_DIR/bin/python" \
    "$VENV_DIR/Scripts/python.exe" \
    "$REPO_DIR/.venv/bin/python" \
    "$REPO_DIR/.venv/Scripts/python.exe" ; do
    case "$candidate" in /bin/python|/Scripts/python.exe) continue ;; esac
    [ -x "$candidate" ] && { VENV_PYTHON="$candidate"; break; }
  done

  if [ -n "$VENV_PYTHON" ]; then
    pass "virtualenv present ($VENV_PYTHON)"
    for mod in fastapi uvicorn pydantic aiosqlite yt_dlp curl_cffi; do
      if out="$("$VENV_PYTHON" -c "import $mod, sys; print(getattr($mod, '__version__', 'present'))" 2>&1)"; then
        pass "python module $mod — $out"
      else
        fail "python module $mod failed to import"
        m2_failures=$((m2_failures + 1))
      fi
    done
  else
    fail "no virtualenv at $VENV_DIR — run scripts/termux-install.sh"
    m2_failures=$((m2_failures + 1))
  fi

  if [ -f "$REPO_DIR/apps/web/dist/index.html" ]; then
    pass 'web UI built (apps/web/dist)'
  else
    fail 'apps/web/dist missing — backend will return 404 at / and serve no PWA'
    m2_failures=$((m2_failures + 1))
  fi
fi

section 'Result'
if [ "$m1_failures" -eq 0 ]; then
  printf '  M1 PASS — Termux runtime verified.\n'
else
  printf '  M1 FAIL — %d check(s) failed. Fix these before starting M2.\n' "$m1_failures"
fi
if [ "$CHECK_M2" -eq 1 ]; then
  if [ "$m2_failures" -eq 0 ]; then
    printf '  M2 readiness: OK.\n'
  else
    printf '  M2 readiness: %d issue(s).\n' "$m2_failures"
  fi
fi
printf '\n'

[ "$m1_failures" -eq 0 ] || exit 1
exit 0
