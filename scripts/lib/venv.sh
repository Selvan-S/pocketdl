# Shared virtualenv resolution for PocketDL's Termux/desktop scripts.
# Source this file, then call resolve_venv_python "$REPO_DIR".
#
# Checked in order: POCKETDL_VENV (read from ~/.pocketdl/.env by the caller
# before sourcing this), services/api/.venv, then a repo-root .venv. Each is
# tried as bin/python (Termux/Linux/macOS) and Scripts/python.exe (Windows, for
# developing this repo's scripts outside Termux).
#
# Prints the resolved python path and returns 0, or prints nothing and
# returns 1.
resolve_venv_python() {
  local repo_dir="$1" api_dir candidate
  api_dir="$repo_dir/services/api"
  for candidate in \
    "${POCKETDL_VENV:-}/bin/python" \
    "${POCKETDL_VENV:-}/Scripts/python.exe" \
    "$api_dir/.venv/bin/python" \
    "$api_dir/.venv/Scripts/python.exe" \
    "$repo_dir/.venv/bin/python" \
    "$repo_dir/.venv/Scripts/python.exe" ; do
    case "$candidate" in /bin/python|/Scripts/python.exe) continue ;; esac
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}
