#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$ROOT/config/quickshell/maho-shell/GuardianState.qml"
EDGE="$ROOT/config/quickshell/maho-shell/EdgeBar.qml"
SIDE="$ROOT/config/quickshell/maho-shell/SideEdgeBar.qml"
WHEEL="$ROOT/config/quickshell/maho-shell/GuardianWheel.qml"
ROTOR="$ROOT/config/quickshell/maho-shell/maho-guardian-rotor.png"
SOUND_SOURCE="$ROOT/config/quickshell/maho-shell/sounds/SOURCE.txt"

fail() { echo "FAIL: $*" >&2; exit 1; }

for path in "$STATE" "$EDGE" "$SIDE" "$WHEEL" "$ROTOR" "$SOUND_SOURCE"; do
    [ -s "$path" ] || fail "missing Guardian surface asset: $path"
done

grep -Fq '"/.local/bin/maho-guard"' "$STATE" || fail "Guardian state does not use managed maho-guard"
grep -Fq '"guardian-status"' "$STATE" || fail "Guardian state does not read Guardian assessments"
grep -Fq '"--json"' "$STATE" || fail "Guardian state reader is not structured"
grep -Fq 'Math.max(0, Math.min(4' "$STATE" || fail "Guardian state severity is not bounded L0-L4"
grep -Fq 'Preserve the last known severity' "$STATE" || fail "reader failure must not imply incident resolution"

for surface in "$EDGE" "$SIDE"; do
    grep -Fq 'GuardianState {' "$surface" || fail "Edge surface lacks Guardian state"
    grep -Fq 'guardianState.active ? "guardian"' "$surface" || fail "Guardian does not own Edge mode priority"
    grep -Fq 'GuardianWheel {' "$surface" || fail "accepted Guardian Wheel is not mounted"
    grep -Fq 'targetSeverity: guardianState.highestSeverity' "$surface" || fail "Wheel is not driven by real severity"
    grep -Fq 'enabled: edge.enabled && edge.mode !== "guardian"' "$surface" || fail "normal wheel/middle-click controls remain active under Guardian ownership"
done

grep -Fq 'root.playLockSound(root._displayedSeverity)' "$WHEEL" || fail "accepted mechanical lock audio lost"
grep -Fq 'Before public release, confirm and record the exact source URLs' "$SOUND_SOURCE" || fail "sound licensing release blocker is no longer explicit"

echo "ALL GUARDIAN WHEEL INTEGRATION CONTRACTS PASS"
