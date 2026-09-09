#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$ROOT/config/quickshell/maho-shell/GuardianState.qml"
EDGE="$ROOT/config/quickshell/maho-shell/EdgeBar.qml"
SIDE="$ROOT/config/quickshell/maho-shell/SideEdgeBar.qml"
WHEEL="$ROOT/config/quickshell/maho-shell/GuardianWheel.qml"
BACKDROP="$ROOT/config/quickshell/maho-shell/GuardianBackdropPulse.qml"
ROTOR="$ROOT/config/quickshell/maho-shell/maho-guardian-rotor.png"
SOUND_SOURCE="$ROOT/config/quickshell/maho-shell/sounds/SOURCE.txt"

fail() { echo "FAIL: $*" >&2; exit 1; }

for path in "$STATE" "$EDGE" "$SIDE" "$WHEEL" "$BACKDROP" "$ROTOR" "$SOUND_SOURCE"; do
    [ -s "$path" ] || fail "missing Guardian surface asset: $path"
done

grep -Fq '"/.local/bin/maho-guard"' "$STATE" || fail "Guardian state does not use managed maho-guard"
grep -Fq '"guardian-status"' "$STATE" || fail "Guardian state does not read Guardian assessments"
grep -Fq '"--json"' "$STATE" || fail "Guardian state reader is not structured"
grep -Fq 'Math.max(0, Math.min(4' "$STATE" || fail "Guardian state severity is not bounded L0-L4"
grep -Fq 'Preserve the last known severity' "$STATE" || fail "reader failure must not imply incident resolution"

for surface in "$EDGE" "$SIDE"; do
    grep -Fq 'GuardianState {' "$surface" || fail "Edge surface lacks Guardian state"
    grep -Fq 'edge.guardianPresentationActive ? "guardian"' "$surface" || fail "Guardian presentation does not own Edge mode priority"
    if grep -Fq 'guardianState.active ? "guardian"' "$surface"; then fail "active incident permanently latches Guardian presentation"; fi
    grep -Fq 'id: guardianPresentationTimer' "$surface" || fail "Guardian presentation lacks bounded lifetime"
    grep -Fq 'onTriggered: edge.guardianPresentationActive = false' "$surface" || fail "Guardian presentation does not retract automatically"
    if grep -Fq 'visible: guardianState.active && !edge.guardianPresentationActive' "$surface"; then fail "post-ritual incident dot must not remain in Edge"; fi
    grep -Fq 'guardianPresentationDuration(severity)' "$surface" || fail "Guardian presentation duration is not severity-aware"
    grep -Fq 'GuardianWheel {' "$surface" || fail "accepted Guardian Wheel is not mounted"
    grep -Fq 'targetSeverity: guardianState.highestSeverity' "$surface" || fail "Wheel is not driven by real severity"
    grep -Fq 'enabled: edge.enabled && edge.mode !== "guardian"' "$surface" || fail "normal wheel/middle-click controls remain active under Guardian ownership"
done

grep -Fq 'root.playLockSound(root._displayedSeverity)' "$WHEEL" || fail "accepted mechanical lock audio lost"
grep -Fq 'const turns = next === 4 ? 720 : 360' "$WHEEL" || fail "every Guardian stage does not have a visible full spin"
grep -Fq 'root._stageTargetAngle = root._angle + turns + 90' "$WHEEL" || fail "Guardian stage spin does not end in a mechanical quarter lock"
grep -Fq 'Before public release, confirm and record the exact source URLs' "$SOUND_SOURCE" || fail "sound licensing release blocker is no longer explicit"

grep -Fq 'oldSeverity < 4 && highest === 4' "$STATE" || fail "catastrophic transition is not derived from real severity state"
grep -Fq 'catastrophicTransitionSerial += 1' "$STATE" || fail "catastrophic transition serial is not edge-triggered"
for surface in "$EDGE" "$SIDE"; do
    grep -Fq 'catastrophicTransitionSerial: guardianState.catastrophicTransitionSerial' "$surface" || fail "Wheel lacks real L4 transition authority"
    grep -Fq 'onCatastrophicLocked: edge.catastrophicLocked()' "$surface" || fail "L4 mechanical lock is not surfaced to Shell"
done
grep -Fq 'root.catastrophicTransitionSerial > root._handledCatastrophicSerial' "$WHEEL" || fail "L4 sound/impact is not one-shot transition gated"
grep -Fq 'root.playLockSound(4)' "$WHEEL" || fail "catastrophic sound contract lost"
grep -Fq 'onCatastrophicLocked: root.handleGuardianCatastrophicLocked()' "$ROOT/config/quickshell/maho-shell/shell.qml" || fail "Shell does not wait for the completed catastrophic wheel lock"
grep -Fq 'interval: 700' "$ROOT/config/quickshell/maho-shell/shell.qml" || fail "post-lock catastrophic hook lacks the short pause"
grep -Fq 'MAHO_GUARDIAN_CATASTROPHIC_HOOK' "$ROOT/config/quickshell/maho-shell/shell.qml" || fail "optional local catastrophic hook is missing"
grep -Fq 'WlrLayershell.layer: WlrLayer.Bottom' "$BACKDROP" || fail "catastrophic wallpaper pulse is not confined below application windows"
grep -Fq 'mask: Region {}' "$BACKDROP" || fail "catastrophic wallpaper pulse must not capture input"
grep -Fq 'to: 0.46' "$BACKDROP" || fail "catastrophic wallpaper fade-in contract lost"
grep -Fq 'duration: 285' "$BACKDROP" || fail "catastrophic wallpaper fade-out contract lost"
grep -Fq 'guardianBackdropPulse.trigger()' "$ROOT/config/quickshell/maho-shell/shell.qml" || fail "Shell does not trigger wallpaper pulse at real L4 lock"
echo "ALL GUARDIAN WHEEL INTEGRATION CONTRACTS PASS"
