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
grep -Fq 'hoverWidth' "$ICON" || fail "independent visual hover width missing"
grep -Fq 'hoverHeight' "$ICON" || fail "independent visual hover height missing"
grep -Fq 'statusLabelWidth' "$ICON" || fail "battery target does not accept the rendered percentage width"
grep -Fq 'statusContentWidth + 14' "$ICON" || fail "battery hit target does not cover the full percentage label"
grep -Fq 'return 52' "$ICON" || fail "keyboard target no longer covers layout text safely"
grep -Fq 'return 34' "$ICON" || fail "Wi-Fi target drifted into neighboring control"
grep -Fq 'statusContentWidth + 8' "$ICON" || fail "battery hover capsule does not cover the full percentage label"
grep -Fq 'return 46' "$ICON" || fail "keyboard hover capsule width drifted"
grep -Fq 'return 30' "$ICON" || fail "Wi-Fi hover capsule width drifted"
grep -Fq 'id: interactionPlate' "$ICON" || fail "status hover plate missing"
grep -Fq 'width: root.hoverWidth' "$ICON" || fail "hover plate is incorrectly using the larger hit geometry"
grep -Fq 'width: root.interactionWidth' "$ICON" || fail "MouseArea does not use semantic hit width"
grep -Fq 'height: root.interactionHeight' "$ICON" || fail "MouseArea does not use semantic hit height"
grep -Fq 'z: 200' "$ICON" || fail "status hit target can fall behind sibling labels"
grep -Fq 'visualNudgeX' "$ICON" || fail "status cluster optical spacing nudge missing"
grep -Fq 'return -2' "$ICON" || fail "Wi-Fi is no longer optically separated from battery"
grep -Fq 'return 2' "$ICON" || fail "keyboard is no longer optically separated from battery"
grep -Fq 'root.statusInteractive ? 1.075 : 1' "$ICON" || fail "interactive status resting scale drifted"
grep -Fq 'root.statusInteractive ? 1.12 : 1.075' "$ICON" || fail "interactive status hover scale drifted"
grep -Fq 'to: 0.84' "$ICON" || fail "charging pulse is too strong or missing"

pass "top-right status controls keep generous clicks and non-overlapping hover geometry"
