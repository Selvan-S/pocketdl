#!/data/data/com.termux/files/usr/bin/bash
# Package the PocketDL Capture extension into a .zip for browsers that only
# accept a packaged file (.zip/.crx), not "load unpacked from a folder" --
# Quetta on Android is the reason this exists; Termux's home directory is a
# private app sandbox other apps cannot browse into via a folder picker.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT_DIR="$REPO_DIR/apps/browser-extension"
OUT_ZIP="${1:-$EXT_DIR/pocketdl-capture.zip}"

# `command -v` only checks that *something* exists at that name -- on Windows,
# `python3` often resolves to a non-functional App Execution Alias stub rather
# than a real interpreter, which would silently shadow a working `python`.
# Actually invoke each candidate rather than trusting existence alone.
PYTHON=''
for candidate in python python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" --version >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  printf 'No working python interpreter found on PATH.\n' >&2
  exit 1
fi

printf '==> Building the extension\n'
cd "$REPO_DIR"
npm run extension:build

printf '==> Packaging %s\n' "$OUT_ZIP"
"$PYTHON" - "$EXT_DIR" "$OUT_ZIP" <<'PY'
import sys
import zipfile
from pathlib import Path

ext_dir = Path(sys.argv[1])
out_zip = Path(sys.argv[2])

# manifest.json must sit at the zip root; dist/*.js paths must match what
# manifest.json references (background.service_worker, popup script imports).
# .map files, node_modules, src/, package.json etc. are dev-only and excluded
# to keep the package small and avoid shipping source layout details.
files = [ext_dir / 'manifest.json', ext_dir / 'popup.html']
files += sorted((ext_dir / 'dist').glob('*.js'))

missing = [f for f in files if not f.is_file()]
if missing:
    print('Missing expected file(s), run npm run extension:build first:', file=sys.stderr)
    for f in missing:
        print(f'  {f}', file=sys.stderr)
    sys.exit(1)

out_zip.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in files:
        zf.write(f, arcname=f.relative_to(ext_dir))

print(f'Wrote {out_zip} ({out_zip.stat().st_size} bytes, {len(files)} files)')
PY

# Best-effort convenience copy into Android shared storage, where Quetta's
# file picker can actually reach it. Silently skipped elsewhere (e.g. the
# Windows/desktop dev machine), where it isn't meaningful.
SHARED_DIR="$HOME/storage/shared"
if [ -d "$SHARED_DIR" ]; then
  cp "$OUT_ZIP" "$SHARED_DIR/pocketdl-capture.zip"
  printf '==> Also copied to %s/pocketdl-capture.zip\n' "$SHARED_DIR"
  printf '    Pick it from "Internal storage/pocketdl-capture.zip" in Quetta.\n'
fi
