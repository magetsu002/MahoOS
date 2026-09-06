#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

EXPECTED="$(python3 "$ROOT/apps/maho-files/source-fingerprint.py" "$ROOT/apps/maho-files")"
BUILD="$TMP/build"

# This is the actual selection path used by a repository/development runtime.
# It must build a missing cache and the selected ELF must expose current source.
ACTUAL="$(
    CXXFLAGS='-fsanitize=address -fno-omit-frame-pointer' \
    LDFLAGS='-fsanitize=address' \
    MAHO_ROOT="$ROOT" MAHO_FILES_BUILD_DIR="$BUILD" \
        bash "$ROOT/bin/maho-files" run --source-fingerprint
)"
[ "$ACTUAL" = "$EXPECTED" ] || fail "selected development artifact does not match current source"
grep -aoEm1 "MAHO_FILES_SOURCE_FINGERPRINT=$EXPECTED" "$BUILD/maho-files" >/dev/null \
    || fail "selected ELF does not contain its claimed source identity"

# Drive an actual initial listing and normal Qt shutdown under ASAN. The old
# implicit member destruction order let KCoreDirLister emit clear() after the
# model's QList storage was freed, which source/provenance checks could not see.
mkdir -p "$TMP/home"
ASAN_OPTIONS=abort_on_error=1:detect_leaks=0 \
QT_QPA_PLATFORM=offscreen HOME="$TMP/home" \
    "$BUILD/maho-files" --test-shutdown-after-load "$TMP/home" \
    >/dev/null 2>"$TMP/shutdown.err" || {
        cat "$TMP/shutdown.err" >&2
        fail "native Maho Files failed clean shutdown under ASAN"
    }
if grep -Fq 'AddressSanitizer' "$TMP/shutdown.err"; then
    cat "$TMP/shutdown.err" >&2
    fail "native Maho Files reported a shutdown memory error"
fi

# Reproduce the rejected delivery bug exactly: a runtime source change beside
# an older executable must fail closed rather than launching the stale QML.
STALE="$TMP/stale-runtime"
mkdir -p "$STALE/apps" "$STALE/bin"
cp -a "$ROOT/apps/maho-files" "$STALE/apps/maho-files"
cp "$ROOT/bin/maho-files" "$STALE/bin/maho-files"
mkdir -p "$STALE/apps/maho-files/prebuilt"
cp "$BUILD/maho-files" "$STALE/apps/maho-files/prebuilt/maho-files"
printf '\n// delivery-provenance regression fixture\n' >> "$STALE/apps/maho-files/qml/Main.qml"

if MAHO_ROOT="$STALE" bash "$STALE/bin/maho-files" run --source-fingerprint \
    >"$TMP/stale.out" 2>"$TMP/stale.err"; then
    fail "changed Main.qml silently launched the old embedded-QML artifact"
fi
grep -Fq 'refusing native binary with stale or missing source identity' "$TMP/stale.err" \
    || fail "stale packaged artifact did not fail with provenance evidence"

echo "PASS  selected native artifact matches source and stale embedded QML fails closed"
