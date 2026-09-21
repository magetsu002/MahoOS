#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_QML="$ROOT/config/quickshell/maho-link/shell.qml"

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

grep -Fq 'stateBase + "/maho/link-position.json"' "$SHELL_QML" \
    || fail 'Link does not use the product-scoped v4 state path'
grep -Fq '"python3", positionHelperPath, "load"' "$SHELL_QML" \
    || fail 'runtime does not load through the mode-keyed position authority'
grep -Fq '"python3", positionHelperPath, "save"' "$SHELL_QML" \
    || fail 'runtime does not save through the mode-keyed position authority'
grep -Fq 'id: placementSave' "$SHELL_QML" \
    || fail 'save lifetime is not owned by the Link process'
grep -Fq 'if (placementSave.running || placementSavePending)' "$SHELL_QML" \
    || fail 'Link can exit before its latest position is durable'
grep -Fq 'closeAfterPlacementSave = true' "$SHELL_QML" \
    || fail 'close is not serialized behind save completion'
grep -Fq 'modeAfterPlacementSave = requestedMode' "$SHELL_QML" \
    || fail 'mode switch can race the previous mode save'
grep -Fq 'reloadPlacement || modeChanged || !placementReady' "$SHELL_QML" \
    || fail 'mode switch can reuse the other mode position'
if grep -Fq 'Quickshell.execDetached([' "$SHELL_QML" \
    && grep -A2 -F 'Quickshell.execDetached([' "$SHELL_QML" | grep -Fq 'positionHelperPath, "save"'; then
    fail 'position save is detached and can race the next mode load'
fi
grep -Fq 'x: 0' "$SHELL_QML" \
    || fail 'a startup x binding can still overwrite restored placement'
grep -Fq 'y: 0' "$SHELL_QML" \
    || fail 'a startup y binding can still overwrite restored placement'
if grep -Fq 'Quickshell.statePath("link-position.json")' "$SHELL_QML"; then
    fail 'runtime-scoped placement authority returned'
fi
if grep -Fq 'onAdapterUpdated: writeAdapter()' "$SHELL_QML"; then
    fail 'multi-property asynchronous state writes can corrupt a coordinate snapshot'
fi

grep -Fq 'target: "link"' "$SHELL_QML" \
    || fail 'running Link process has no IPC mode authority'
grep -Fq 'function showMode(mode: string): bool' "$SHELL_QML" \
    || fail 'Edge cannot switch the running Link process between modes'
grep -Fq 'return root.showMode(mode, false)' "$SHELL_QML" \
    || fail 'IPC mode switch does not reach the mode-keyed placement loader'
grep -Fq 'quickshell ipc --pid "$pid" call link showMode "$MODE"' "$ROOT/bin/maho-link" \
    || fail 'singleton wrapper does not address the exact same-runtime process'
grep -Fq 'quickshell ipc --pid "$pid" call link toggleMode "$MODE"' "$ROOT/bin/maho-link" \
    || fail 'keyboard Link toggle does not address the exact same-runtime process'
grep -Fq 'function toggleMode(mode: string): bool' "$SHELL_QML" \
    || fail 'running Link process has no atomic same-mode toggle'
grep -Fq 'root.presented && !closeTimer.running && root.activeMode === requestedMode' "$SHELL_QML" \
    || fail 'Link toggle does not distinguish an already-open matching mode'
if grep -Fq 'maho-link: already running' "$ROOT/bin/maho-link"; then
    fail 'singleton wrapper still reports success after dropping a mode request'
fi

python3 "$ROOT/tests/maho-link-position-tests.py"

printf 'PASS  executable Maho Link independent-position roundtrip and geometry contracts\n'
