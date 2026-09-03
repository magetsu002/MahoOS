#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DOCK="$ROOT/config/quickshell/maho-shell/MahoDock.qml"

fail() { echo "FAIL: $*" >&2; exit 1; }
require_text() { grep -Fq -- "$2" "$1" || fail "$3"; }
reject_text() { if grep -Fq -- "$2" "$1"; then fail "$3"; fi; }

echo "=== bottom optical anchor ==="
require_text "$DOCK" 'bottom: 2' "Dock drifted away from the physical bottom edge"
echo PASS

echo "=== accepted translucent glass recipe ==="
require_text "$DOCK" 'brightBackdrop ? 0.038 : 0.120' "dark-wallpaper glass lift is not the accepted value"
require_text "$DOCK" 'theme.semanticForeground, brightBackdrop ? 0.012 : 0.042' "glass source is mixing back toward muddy shadow"
require_text "$DOCK" 'brightBackdrop ? 0.32 : 0.29' "resting Dock transmission drifted from the accepted V3 target"
require_text "$DOCK" 'brightBackdrop ? 0.46 : 0.41' "raised preview transmission drifted from the accepted target"
require_text "$DOCK" 'brightBackdrop ? 0.31 : 0.35' "specular strength drifted from the accepted target"
require_text "$DOCK" 'brightBackdrop ? 0.105 : 0.125' "reflection strength drifted from the accepted target"
require_text "$DOCK" 'brightBackdrop ? 0.045 : 0.058' "inner glass well is too opaque"
require_text "$DOCK" 'color: root.theme.alpha(root.theme.semanticShadow, brightBackdrop ? 0.13 : 0.075)' "Dock depth became too heavy"
echo PASS

echo "=== radius-matched continuous reflection ==="
require_text "$DOCK" 'id: dockReflectionField' "Dock lost its continuous reflection field"
require_text "$DOCK" 'radius: dockShell.radius' "Dock reflection can leak through rounded shell corners"
require_text "$DOCK" 'opacity: 0.72 * root.dockRevealProgress' "Dock reflection field intensity drifted"
require_text "$DOCK" 'id: previewReflectionField' "preview lost the continuous reflection field"
require_text "$DOCK" 'radius: previewShell.radius' "preview reflection can leak through rounded shell corners"
require_text "$DOCK" 'anchors.fill: parent' "reflection fields are no longer full-shell layers"
require_text "$DOCK" 'Qt Quick' "rounded reflection rationale disappeared"
reject_text "$DOCK" 'height: Math.max(2, 21 * root.dockRevealProgress)' "legacy short Dock reflection strip returned"
reject_text "$DOCK" 'previewShell.clip gives it the exact optical silhouette' "preview reflection incorrectly relies on rectangular clip semantics"
reject_text "$DOCK" 'experimentalRightGlint' "legacy side-glint artifact returned"
reject_text "$DOCK" 'experimentalGlassBloom' "legacy local rounded bloom returned"
echo PASS

echo "=== clean single hover grammar ==="
require_text "$DOCK" 'width: 66' "shared hover lens is oversized"
require_text "$DOCK" 'height: 66' "shared hover lens is oversized"
require_text "$DOCK" 'root.hoverLensFocused ? 0.052 : 0.078' "hover lens became too heavy"
require_text "$DOCK" 'root.hoverLensFocused ? 0.019 : 0.028' "hover lens rim became too loud"
require_text "$DOCK" 'y: 8 - appCell.hoverProgress * 1.5' "icon hover jumps too far vertically"
require_text "$DOCK" 'scale: 1 + appCell.hoverProgress * 0.016' "icon hover magnification drifted"
reject_text "$DOCK" 'hoverProgress * 3' "legacy large icon lift remains"
reject_text "$DOCK" 'hoverProgress * 0.026' "legacy hover magnification remains"
echo PASS

echo "ALL MAHO DOCK MATERIAL CLEANUP CONTRACTS PASS"
