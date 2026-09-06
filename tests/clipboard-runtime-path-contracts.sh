#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WRAPPER="$ROOT/bin/maho-clipboard"
HELPER="$ROOT/lib/runtime-instance.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

RELEASE="$TMP/release"
CURRENT="$TMP/current"
CAPTURE="$TMP/capture.txt"
RUNTIME_DIR="$TMP/run"
mkdir -p "$RELEASE/bin" "$RELEASE/lib" "$RELEASE/config/quickshell/maho-clipboard" "$TMP/fake-bin" "$RUNTIME_DIR"
cp "$WRAPPER" "$RELEASE/bin/maho-clipboard"
cp "$HELPER" "$RELEASE/lib/runtime-instance.sh"
printf '%s\n' '// test shell' > "$RELEASE/config/quickshell/maho-clipboard/shell.qml"
ln -s "$RELEASE" "$CURRENT"

cat > "$TMP/fake-bin/quickshell" <<'EOF_QS'
#!/usr/bin/env bash
set -euo pipefail
{
    printf 'QML_DISABLE_DISK_CACHE=%s\n' "${QML_DISABLE_DISK_CACHE:-<unset>}"
    printf 'MAHO_RUNTIME_IDENTITY=%s\n' "${MAHO_RUNTIME_IDENTITY:-<unset>}"
    printf 'ARGS='
    printf '%q ' "$@"
    printf '\n'
} > "${MAHO_TEST_CAPTURE:?}"
EOF_QS
chmod +x "$TMP/fake-bin/quickshell"

for command in flock cliphist wl-copy hyprctl; do
    cat > "$TMP/fake-bin/$command" <<'EOF_TRUE'
#!/usr/bin/env bash
exit 0
EOF_TRUE
    chmod +x "$TMP/fake-bin/$command"
done

cat > "$TMP/fake-bin/pgrep" <<'EOF_PGREP'
#!/usr/bin/env bash
exit 1
EOF_PGREP
chmod +x "$TMP/fake-bin/pgrep"

MAHO_TEST_CAPTURE="$CAPTURE" \
XDG_RUNTIME_DIR="$RUNTIME_DIR" \
PATH="$TMP/fake-bin:$PATH" \
bash "$CURRENT/bin/maho-clipboard"

[ -s "$CAPTURE" ] || fail "clipboard wrapper never launched Quickshell"
grep -Fqx "QML_DISABLE_DISK_CACHE=1" "$CAPTURE" || fail "clipboard launch did not disable stale QML disk cache"
grep -Fqx "MAHO_RUNTIME_IDENTITY=$RELEASE" "$CAPTURE" || fail "runtime identity did not resolve to immutable release"
grep -Fq -- "-p $RELEASE/config/quickshell/maho-clipboard/shell.qml" "$CAPTURE" \
    || fail "Quickshell config path still uses runtime/current instead of immutable release"

printf '%s\n' 'PASS  Clipboard resolves immutable QML path and disables cross-release disk cache'
