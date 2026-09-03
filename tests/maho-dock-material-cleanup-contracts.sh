#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DOCK="$ROOT/config/quickshell/maho-shell/MahoDock.qml"

fail() { echo "FAIL: $*" >&2; exit 1; }
require_text() { grep -Fq -- "$2" "$1" || fail "$3"; }
reject_text() { if grep -Fq -- "$2" "$1"; then fail "$3"; fi; }

echo "=== bottom optical anchor ==="
require_text "$DOCK" 'bottom: 2' "Dock is still floating too far above the physical bottom edge"
echo PASS

echo "=== dark-wallpaper glass lift ==="
require_text "$DOCK" 'darkGlassLift' "Dock has no dark-wallpaper self-luminance compensation"
require_text "$DOCK" 'brightBackdrop ? 0.40 : 0.34' "dark material still over-mixes toward shadow"
require_text "$DOCK" 'brightBackdrop ? 0.020 : 0.085' "dark glass does not lift toward foreground"
require_text "$DOCK" 'shellReflection' "Dock lost broad reflection material"
echo PASS

echo "=== clean single hover grammar ==="
require_text "$DOCK" 'width: 66' "shared hover lens is still oversized"
require_text "$DOCK" 'height: 66' "shared hover lens is still oversized"
require_text "$DOCK" '0.16' "hover lens material is still too heavy"
require_text "$DOCK" 'y: 8 - appCell.hoverProgress * 1.5' "icon hover still jumps too far vertically"
require_text "$DOCK" 'scale: 1 + appCell.hoverProgress * 0.016' "icon hover still magnifies too aggressively"
reject_text "$DOCK" 'hoverProgress * 3' "legacy large icon lift remains"
reject_text "$DOCK" 'hoverProgress * 0.026' "legacy hover magnification remains"
echo PASS

echo "ALL MAHO DOCK MATERIAL CLEANUP CONTRACTS PASS"
