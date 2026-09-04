#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ICON="$ROOT/config/quickshell/maho-lock/MahoIconV2.qml"

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

pass() {
    printf 'PASS  %s\n' "$*"
}

[ -r "$ICON" ] || fail "missing MahoIconV2.qml"

grep -Fq 'interactionWidth' "$ICON" || fail "semantic status hit width missing"
grep -Fq 'interactionHeight' "$ICON" || fail "semantic status hit height missing"
grep -Fq 'return 69' "$ICON" || fail "battery target no longer covers percentage text"
grep -Fq 'return 55' "$ICON" || fail "keyboard target no longer covers layout text"
grep -Fq 'return 40' "$ICON" || fail "Wi-Fi target is below desktop-size hit area"
grep -Fq 'id: interactionPlate' "$ICON" || fail "whole-control hover plate missing"
grep -Fq 'width: root.interactionWidth' "$ICON" || fail "MouseArea does not use semantic hit width"
grep -Fq 'height: root.interactionHeight' "$ICON" || fail "MouseArea does not use semantic hit height"
grep -Fq 'z: 200' "$ICON" || fail "status hit target can fall behind sibling labels"
grep -Fq 'visualNudgeX' "$ICON" || fail "status cluster optical spacing nudge missing"
grep -Fq 'return -3' "$ICON" || fail "Wi-Fi is no longer optically separated from battery"
grep -Fq 'return 3' "$ICON" || fail "keyboard is no longer optically separated from battery"
grep -Fq 'root.statusInteractive ? 1.10 : 1' "$ICON" || fail "interactive status glyphs lost larger resting scale"
grep -Fq 'root.statusInteractive ? 1.16 : 1.075' "$ICON" || fail "interactive status hover scale drifted"
grep -Fq 'to: 0.82' "$ICON" || fail "charging pulse is too strong or missing"

pass "top-right status controls expose full targets with calm optical spacing"
