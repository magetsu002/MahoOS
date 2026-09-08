#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_SOURCE="$ROOT/config/quickshell/maho-shell/MahoDockState.qml"
PROBE_SOURCE="$ROOT/tests/fixtures/maho-dock-state-probe.qml"

fail() { printf 'FAIL  %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS  %s\n' "$*"; }

QUICKSHELL="$(command -v quickshell || true)"
[ -n "$QUICKSHELL" ] || fail "Quickshell is unavailable"

sandbox="$(mktemp -d)"
trap 'rm -rf -- "$sandbox"' EXIT
mkdir -p "$sandbox/config" "$sandbox/state"
cp "$STATE_SOURCE" "$sandbox/config/MahoDockState.qml"
cp "$PROBE_SOURCE" "$sandbox/config/shell.qml"

run_probe() {
    local pin="${1:-}" log="$2"
    XDG_STATE_HOME="$sandbox/state" \
        MAHO_DOCK_PROBE_PIN="$pin" \
        timeout 5s "$QUICKSHELL" -vv -p "$sandbox/config/shell.qml" --no-color \
        >"$log" 2>&1
}

run_probe vesktop.desktop "$sandbox/first.log"
state_file="$sandbox/state/quickshell/by-shell/maho-dock-state-probe/maho-dock.json"
[ -s "$state_file" ] || fail "first process did not write Dock state"
grep -Fq 'vesktop.desktop' "$state_file" \
    || fail "first process did not persist the requested pin"
pass "first process persisted a pin"

run_probe "" "$sandbox/second.log"
grep -Fq 'MAHO_DOCK_PROBE_PINS=["vesktop.desktop"]' "$sandbox/second.log" \
    || { sed -n '1,160p' "$sandbox/second.log" >&2; fail "fresh process did not load the persisted pin"; }
pass "fresh process restored the persisted pin"
