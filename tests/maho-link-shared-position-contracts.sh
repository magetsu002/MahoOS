#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_QML="$ROOT/config/quickshell/maho-link/shell.qml"

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

grep -Fq 'stateBase + "/maho/link-position.json"' "$SHELL_QML" \
    || fail 'Link does not use the product-scoped v3 state path'
grep -Fq '"python3", positionHelperPath, "load"' "$SHELL_QML" \
    || fail 'runtime does not load through the shared position authority'
grep -Fq '"python3", positionHelperPath, "save"' "$SHELL_QML" \
    || fail 'runtime does not save through the shared position authority'
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

python3 "$ROOT/tests/maho-link-position-tests.py"

printf 'PASS  executable Maho Link shared-position roundtrip and geometry contracts\n'
