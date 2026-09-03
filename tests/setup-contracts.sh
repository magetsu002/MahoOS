#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_CONFIG_HOME="$TMP/config"
export XDG_DATA_HOME="$TMP/data"
export XDG_STATE_HOME="$TMP/state"
export XDG_CACHE_HOME="$TMP/cache"
export PATH="$TMP/fake-bin:/usr/bin:/bin"

mkdir -p \
    "$HOME/.local/bin" \
    "$XDG_CONFIG_HOME" \
    "$XDG_DATA_HOME" \
    "$XDG_STATE_HOME" \
    "$XDG_CACHE_HOME" \
    "$TMP/fake-bin"

SYSTEMCTL_LOG="$TMP/systemctl.log"
export MAHO_TEST_SYSTEMCTL_LOG="$SYSTEMCTL_LOG"

cat >"$TMP/fake-bin/systemctl" <<'EOF_SYSTEMCTL'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$MAHO_TEST_SYSTEMCTL_LOG"

case "$*" in
    '--user show-environment')
        exit 0
        ;;
    '--user daemon-reload')
        [ "${MAHO_TEST_FAIL_DAEMON_RELOAD:-0}" = 1 ] && exit 1
        exit 0
        ;;
    '--user is-active --quiet graphical-session.target'|\
    '--user is-active --quiet maho-observe.service'|\
    '--user is-active --quiet maho-security.service'|\
    '--user is-active --quiet maho-awww-daemon.service'|\
    '--user is-active --quiet maho-wallpaper.service'|\
    '--user is-active --quiet maho-shell.service'|\
    '--user is-active --quiet maho-notify.service')
        exit 0
        ;;
    *)
        exit 0
        ;;
esac
EOF_SYSTEMCTL
chmod +x "$TMP/fake-bin/systemctl"

cat >"$TMP/fake-bin/quickshell" <<'EOF_QUICKSHELL'
#!/usr/bin/env bash
exit 0
EOF_QUICKSHELL
chmod +x "$TMP/fake-bin/quickshell"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

COMMANDS=(
    mahoctl maho-theme maho-wallpaper maho-wallpaper-session maho-observe
    maho-adapt maho-provenance maho-security maho-security-monitor maho-guard
    maho-contain maho-shell maho-notify maho-link maho-launcher maho-session
    maho-setup
)

CORE_UNITS=(maho-observe.service maho-security.service)
SESSION_UNITS=(
    maho-awww-daemon.service
    maho-wallpaper.service
    maho-shell.service
    maho-notify.service
)
UNITS=("${CORE_UNITS[@]}" "${SESSION_UNITS[@]}" maho-hyprland-session.target)

RUNTIME_ROOT="$XDG_DATA_HOME/maho/runtime"
RELEASES="$RUNTIME_ROOT/releases"
CURRENT="$RUNTIME_ROOT/current"
PREVIOUS="$RUNTIME_ROOT/previous"
OLD_RELEASE="$RELEASES/known-good-live"
UNIT_DIR="$XDG_CONFIG_HOME/systemd/user"
HYPR_SESSION="$XDG_CONFIG_HOME/hypr/maho/core/session.lua"
SHELL_TARGET="$XDG_CONFIG_HOME/quickshell/maho-shell"
NOTIFY_TARGET="$XDG_CONFIG_HOME/quickshell/maho-notify"

mkdir -p \
    "$OLD_RELEASE/bin" \
    "$OLD_RELEASE/config/quickshell/maho-shell" \
    "$OLD_RELEASE/config/hypr/maho/core" \
    "$OLD_RELEASE/systemd/user" \
    "$UNIT_DIR/default.target.wants" \
    "$UNIT_DIR/graphical-session.target.wants" \
    "$(dirname "$SHELL_TARGET")" \
    "$(dirname "$HYPR_SESSION")"

ln -s "$OLD_RELEASE" "$CURRENT"

write_live_v2_wrapper() {
    local name="$1"
    cat >"$HOME/.local/bin/$name" <<EOF_WRAPPER
#!/usr/bin/env bash
# managed-by: maho-setup v2
MAHO_ROOT="\${XDG_DATA_HOME:-\$HOME/.local/share}/maho/runtime/current"
export MAHO_ROOT
exec bash "\$MAHO_ROOT/bin/$name" "\$@"
EOF_WRAPPER
    chmod +x "$HOME/.local/bin/$name"
}

for name in "${COMMANDS[@]}"; do
    case "$name" in
        maho-notify|maho-link|maho-launcher) continue ;;
    esac
    write_live_v2_wrapper "$name"
done

# Recovered production has the canonical Notify launcher installed directly
# instead of behind a v2 wrapper. Adoption is permitted only for this exact
# deployed content hash.
cp "$ROOT/bin/maho-notify" "$HOME/.local/bin/maho-notify"
chmod +x "$HOME/.local/bin/maho-notify"
[ "$(sha256sum "$HOME/.local/bin/maho-notify" | awk '{print $1}')" = \
  '77d1b10eefb368648ef762b3275b066b5a7c0f554dd543678488ff6686bc5ddf' ] ||
    fail "canonical Notify no longer matches recovered production hash"

# Recovered production Maho Link still routes through its dedicated Bluetooth
# runtime. This exact wrapper is a recognized migration source.
cat >"$HOME/.local/bin/maho-link" <<'EOF_LEGACY_LINK'
#!/usr/bin/env bash
set -euo pipefail

RUNTIME="${XDG_DATA_HOME:-$HOME/.local/share}/maho-link-bluetooth"

export MAHO_LINK_CONFIG="$RUNTIME/config/quickshell/maho-link/shell.qml"

exec bash "$RUNTIME/bin/maho-link" "$@"
EOF_LEGACY_LINK
chmod +x "$HOME/.local/bin/maho-link"
[ "$(sha256sum "$HOME/.local/bin/maho-link" | awk '{print $1}')" = \
  '0f366321f351059e9600591008c4bce22d194377e68bc6e4d149af10166729a3' ] ||
    fail "legacy Maho Link fixture no longer matches recovered production hash"

cat >"$HOME/.local/bin/maho-launcher" <<'EOF_PREVIEW'
#!/usr/bin/env bash
set -euo pipefail

RUNTIME="${XDG_DATA_HOME:-$HOME/.local/share}/maho-launcher-preview"

export MAHO_ROOT="$RUNTIME"
export MAHO_LAUNCHER_CONFIG_DIR="$RUNTIME/config/quickshell/maho-launcher"

exec bash "$RUNTIME/bin/maho-launcher" "$@"
EOF_PREVIEW
chmod +x "$HOME/.local/bin/maho-launcher"

for unit in "${UNITS[@]}"; do
    ln -s "$CURRENT/systemd/user/$unit" "$UNIT_DIR/$unit"
done

ln -s "$CURRENT/config/quickshell/maho-shell" "$SHELL_TARGET"

mkdir -p "$NOTIFY_TARGET"
printf '%s\n' 'live-notify-owner' >"$NOTIFY_TARGET/owner.txt"
printf '%s\n' '// live notification config stays untouched in M0.1' >"$NOTIFY_TARGET/shell.qml"

cat >"$HYPR_SESSION" <<'EOF_LEGACY_SESSION'
-- Own graphical Maho services only while this Hyprland session is alive.

hl.on("hyprland.start", function()
    hl.exec_cmd([["$HOME/.local/bin/maho-session" start]])
    hl.exec_cmd("waybar")
end)

hl.on("hyprland.shutdown", function()
    hl.exec_cmd([["$HOME/.local/bin/maho-session" stop]])
end)
EOF_LEGACY_SESSION

for unit in "${CORE_UNITS[@]}"; do
    ln -s "$UNIT_DIR/$unit" "$UNIT_DIR/default.target.wants/$unit"
done

for unit in "${SESSION_UNITS[@]}"; do
    ln -s "$UNIT_DIR/$unit" "$UNIT_DIR/graphical-session.target.wants/$unit"
done

describe_path() {
    local path="$1"

    if [ -L "$path" ]; then
        printf 'L\t%s\t%s\n' "$path" "$(readlink "$path")"
    elif [ -f "$path" ]; then
        printf 'F\t%s\t%s\n' "$path" "$(sha256sum "$path" | awk '{print $1}')"
    elif [ -d "$path" ]; then
        printf 'D\t%s\t%s\n' "$path" "$(
            find "$path" -type f -print0 2>/dev/null |
                sort -z |
                xargs -0 -r sha256sum |
                sha256sum |
                awk '{print $1}'
        )"
    else
        printf 'M\t%s\n' "$path"
    fi
}

capture_live_state() {
    local out="$1" name unit
    : >"$out"

    describe_path "$CURRENT" >>"$out"
    describe_path "$PREVIOUS" >>"$out"

    for name in "${COMMANDS[@]}"; do
        describe_path "$HOME/.local/bin/$name" >>"$out"
    done

    describe_path "$SHELL_TARGET" >>"$out"
    describe_path "$NOTIFY_TARGET" >>"$out"
    describe_path "$HYPR_SESSION" >>"$out"

    for unit in "${UNITS[@]}"; do
        describe_path "$UNIT_DIR/$unit" >>"$out"
    done

    for unit in "${CORE_UNITS[@]}" "${SESSION_UNITS[@]}"; do
        describe_path "$UNIT_DIR/default.target.wants/$unit" >>"$out"
        describe_path "$UNIT_DIR/graphical-session.target.wants/$unit" >>"$out"
    done
}

echo "=== preflight ==="
bash "$ROOT/bin/maho-setup" preflight >/dev/null
echo "PASS"

echo "=== validation failure is non-mutating ==="
cp "$HOME/.local/bin/maho-security" "$TMP/maho-security.v2"
printf '%s\n' '#!/usr/bin/env bash' 'echo external-security-owner' >"$HOME/.local/bin/maho-security"
chmod +x "$HOME/.local/bin/maho-security"

capture_live_state "$TMP/before-validation-failure"
if bash "$ROOT/bin/maho-setup" install >/dev/null 2>&1; then
    fail "installer accepted an unmanaged command"
fi
capture_live_state "$TMP/after-validation-failure"

cmp -s "$TMP/before-validation-failure" "$TMP/after-validation-failure" ||
    fail "validation failure mutated live wiring"

cp "$TMP/maho-security.v2" "$HOME/.local/bin/maho-security"
chmod +x "$HOME/.local/bin/maho-security"
echo "PASS"

echo "=== post-switch failure rolls back exact live wiring ==="
capture_live_state "$TMP/before-post-switch-failure"

export MAHO_TEST_FAIL_DAEMON_RELOAD=1
if bash "$ROOT/bin/maho-setup" install >/dev/null 2>&1; then
    fail "simulated daemon-reload failure unexpectedly succeeded"
fi
unset MAHO_TEST_FAIL_DAEMON_RELOAD

capture_live_state "$TMP/after-post-switch-failure"
cmp -s "$TMP/before-post-switch-failure" "$TMP/after-post-switch-failure" ||
    fail "post-switch failure did not restore exact pre-install wiring"
echo "PASS"

echo "=== successful durable install ==="
bash "$ROOT/bin/maho-setup" install >/dev/null

NEW_RELEASE="$(readlink -f "$CURRENT")"
[ -n "$NEW_RELEASE" ] || fail "runtime/current did not resolve"
[ "$NEW_RELEASE" != "$OLD_RELEASE" ] || fail "runtime/current did not switch"
[ -f "$NEW_RELEASE/manifest.json" ] || fail "immutable release manifest missing"
[ "$(readlink -f "$PREVIOUS")" = "$OLD_RELEASE" ] ||
    fail "previous runtime was not retained"

for name in "${COMMANDS[@]}"; do
    path="$HOME/.local/bin/$name"
    [ -x "$path" ] || fail "managed command missing: $name"
    grep -Fq '# managed-by: maho-setup v2' "$path" ||
        fail "managed command lost v2 ownership marker: $name"
    grep -Fq 'maho/runtime/current' "$path" ||
        fail "managed command does not route through runtime/current: $name"
done

grep -Fq 'bin/maho-launcher' "$HOME/.local/bin/maho-launcher" ||
    fail "launcher wrapper does not route to native launcher"
if grep -Fq 'maho-launcher-preview' "$HOME/.local/bin/maho-launcher"; then
    fail "launcher wrapper still references preview runtime"
fi
if grep -Fq 'maho-launcher-preview' "$NEW_RELEASE/bin/maho-launcher"; then
    fail "canonical native launcher references preview runtime"
fi

raw="$(readlink "$SHELL_TARGET")"
[ "$raw" = "$CURRENT/config/quickshell/maho-shell" ] ||
    fail "Maho Shell does not route through runtime/current"

[ -d "$NOTIFY_TARGET" ] && [ ! -L "$NOTIFY_TARGET" ] ||
    fail "live-owned Maho Notify directory was replaced"
grep -Fq 'live-notify-owner' "$NOTIFY_TARGET/owner.txt" ||
    fail "live-owned Maho Notify directory was modified"

[ -L "$HYPR_SESSION" ] ||
    fail "legacy Hyprland session hook was not migrated"
[ "$(readlink "$HYPR_SESSION")" = "$CURRENT/config/hypr/maho/core/session.lua" ] ||
    fail "Hyprland session hook does not route through runtime/current"
if grep -Fq 'waybar' "$HYPR_SESSION"; then
    fail "normal Hyprland startup still invokes Waybar"
fi

for unit in "${UNITS[@]}"; do
    target="$UNIT_DIR/$unit"
    [ -L "$target" ] || fail "unit is not runtime-managed: $unit"
    [ "$(readlink "$target")" = "$CURRENT/systemd/user/$unit" ] ||
        fail "unit does not route through runtime/current: $unit"
done

for unit in "${CORE_UNITS[@]}"; do
    [ -L "$UNIT_DIR/default.target.wants/$unit" ] ||
        fail "core unit not owned by default.target: $unit"
    [ ! -e "$UNIT_DIR/graphical-session.target.wants/$unit" ] &&
        [ ! -L "$UNIT_DIR/graphical-session.target.wants/$unit" ] ||
        fail "core unit incorrectly owned by graphical-session.target: $unit"
done

for unit in "${SESSION_UNITS[@]}"; do
    [ -L "$UNIT_DIR/graphical-session.target.wants/$unit" ] ||
        fail "graphical unit not owned by graphical-session.target: $unit"
    [ ! -e "$UNIT_DIR/default.target.wants/$unit" ] &&
        [ ! -L "$UNIT_DIR/default.target.wants/$unit" ] ||
        fail "graphical unit regressed to default.target: $unit"
done

if grep -Eq -- '--now|(^| )restart( |$)|(^| )try-restart( |$)' "$SYSTEMCTL_LOG"; then
    fail "durable install restarted live services"
fi

"$HOME/.local/bin/maho-setup" status >/dev/null
echo "PASS"

echo "=== unrelated Hyprland hook remains protected ==="
rm -f "$HYPR_SESSION"
printf '%s\n' '-- external Hyprland owner' >"$HYPR_SESSION"
capture_live_state "$TMP/before-unrelated-hypr"
if bash "$ROOT/bin/maho-setup" install >/dev/null 2>&1; then
    fail "installer overwrote an unrelated Hyprland session hook"
fi
capture_live_state "$TMP/after-unrelated-hypr"
cmp -s "$TMP/before-unrelated-hypr" "$TMP/after-unrelated-hypr" ||
    fail "failed Hyprland validation mutated live wiring"
grep -Fq -- '-- external Hyprland owner' "$HYPR_SESSION" ||
    fail "unrelated Hyprland hook content changed"
echo "PASS"

echo "=== session contracts ==="
bash "$ROOT/tests/session-contracts.sh" >/dev/null
echo "PASS"

echo "ALL DURABLE SETUP CONTRACTS PASS"
