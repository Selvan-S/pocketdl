#!/data/data/com.termux/files/usr/bin/bash
# PocketDL — enable Termux:Boot autostart (M6).
#
# This only wires up the boot hook; it does not install the Termux:Boot app
# itself. Termux:Boot is a separate app (install from F-Droid, not the
# frequently-stale Play Store build) that Android requires for anything to run
# automatically after a reboot — Termux itself cannot receive the boot event.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOT_DIR="$HOME/.termux/boot"
BOOT_LINK="$BOOT_DIR/pocketdl-start"
SERVICE_SCRIPT="$REPO_DIR/scripts/pocketdl-service.sh"

if [ -z "${PREFIX:-}" ] || [ "${PREFIX#/data/data/com.termux}" = "${PREFIX}" ]; then
  printf 'This script targets Termux on Android (PREFIX=%s).\n' "${PREFIX:-unset}" >&2
  exit 1
fi

mkdir -p "$BOOT_DIR"
chmod +x "$SERVICE_SCRIPT" "$REPO_DIR/scripts/pocketdl-stop.sh" "$REPO_DIR/scripts/pocketdl-status.sh"

# A symlink (rather than a copy) means `git pull` updates boot behavior
# without re-running this installer.
ln -sf "$SERVICE_SCRIPT" "$BOOT_LINK"
printf 'Boot hook installed: %s -> %s\n' "$BOOT_LINK" "$SERVICE_SCRIPT"

# Best-effort only: package visibility is restricted on some Android
# versions, so a miss here is a hint, not a reliable negative.
if command -v pm >/dev/null 2>&1 && pm list packages 2>/dev/null | grep -q 'com\.termux\.boot'; then
  printf 'Termux:Boot app: detected.\n'
else
  printf 'Termux:Boot app: not detected (or undetectable on this Android version).\n'
  printf '  Install it from F-Droid if you have not: https://f-droid.org/packages/com.termux.boot/\n'
  printf '  Open it once after installing so it registers for the boot event.\n'
fi

cat <<'NOTE'

On some phones (MIUI, OxygenOS, One UI, ...) you also need to manually allow
autostart / disable battery optimization for Termux and Termux:Boot in
Android's app settings, or the OS will not let the boot receiver run.

Test now without rebooting:
  bash ~/.termux/boot/pocketdl-start &
  bash scripts/pocketdl-status.sh

Test the real path:
  reboot the device, then: bash scripts/pocketdl-status.sh

Stop the service:
  bash scripts/pocketdl-stop.sh
NOTE
