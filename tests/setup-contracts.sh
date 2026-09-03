#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_CONFIG_HOME="$TMP/config"
export XDG_STATE_HOME="$TMP/state"
export XDG_CACHE_HOME="$TMP/cache"
export PATH="$TMP/fake-bin:/usr/bin:/bin"
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$TMP/fake-bin"

SYSTEMCTL_LOG="$TMP/systemctl.log"
export MAHO_TEST_SYSTEMCTL_LOG="$SYSTEMCTL_LOG"
cat > "$TMP/fake-bin/systemctl" <<'EOF_SYSTEMCTL'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MAHO_TEST_SYSTEMCTL_LOG"
case "$*" in
    '--user show-environment') exit 0 ;;
    '--user is-active --quiet maho-wallpaper.service') exit 0 ;;
    '--user is-active --quiet maho-observe.service') exit 0 ;;
    '--user is-active --quiet maho-security.service') exit 0 ;;
    '--user is-active --quiet maho-shell.service') exit 0 ;;
    '--user is-active --quiet maho-notify.service') exit 1 ;;
    '--user is-active --quiet maho-hyprland-session.target') exit 0 ;;
    *) exit 0 ;;
esac
EOF_SYSTEMCTL
chmod +x "$TMP/fake-bin/systemctl"

cat > "$TMP/fake-bin/quickshell" <<'EOF_QUICKSHELL'
#!/usr/bin/env bash
exit 0
EOF_QUICKSHELL
chmod +x "$TMP/fake-bin/quickshell"

fail() { echo "FAIL: $*" >&2; exit 1; }

COMMANDS=(mahoctl maho-theme maho-wallpaper maho-wallpaper-session maho-observe maho-adapt maho-provenance maho-security maho-security-monitor maho-guard maho-contain maho-shell maho-notify maho-launcher maho-session maho-setup)
UNITS=(maho-wallpaper.service maho-observe.service maho-security.service maho-shell.service maho-notify.service maho-hyprland-session.target)

echo "=== preflight ==="
bash "$ROOT/bin/maho-setup" preflight >/dev/null
echo "PASS"

echo "=== legacy Hyprland session migration ==="
HYPR_SESSION_TARGET="$XDG_CONFIG_HOME/hypr/maho/core/session.lua"
mkdir -p "$(dirname "$HYPR_SESSION_TARGET")"
cat > "$HYPR_SESSION_TARGET" <<'EOF_LEGACY_SESSION'
-- Own graphical Maho services only while this Hyprland session is alive.
hl.on("hyprland.start", function()
    hl.exec_cmd([["$HOME/.local/bin/maho-session" start]])
    hl.exec_cmd("waybar")
end)
hl.on("hyprland.shutdown", function()
    hl.exec_cmd([["$HOME/.local/bin/maho-session" stop]])
end)
EOF_LEGACY_SESSION

echo "=== install ==="
bash "$ROOT/bin/maho-setup" install >/dev/null
for name in "${COMMANDS[@]}"; do
    path="$HOME/.local/bin/$name"
    [ -x "$path" ] || fail "launcher not executable: $name"
    grep -Fq '# managed-by: maho-setup v1' "$path" || fail "launcher missing ownership marker: $name"
done

LAUNCHER="$HOME/.local/bin/maho-launcher"
grep -Fq 'bin/maho-launcher' "$LAUNCHER" || fail "managed launcher does not route to the native launcher wrapper"
if grep -Fq 'maho-launcher-preview' "$LAUNCHER"; then
    fail "managed launcher still routes to maho-launcher-preview"
fi
if grep -Fq 'maho-launcher-preview' "$ROOT/bin/maho-launcher"; then
    fail "canonical launcher wrapper references maho-launcher-preview"
fi

SHELL_TARGET="$XDG_CONFIG_HOME/quickshell/maho-shell"
[ -L "$SHELL_TARGET" ] || fail "Maho Shell configuration is not a symlink"
[ "$(readlink -f "$SHELL_TARGET")" = "$ROOT/config/quickshell/maho-shell" ] || fail "Maho Shell targets wrong runtime"
[ -r "$SHELL_TARGET/shell.qml" ] || fail "Maho Shell entrypoint missing after install"

NOTIFY_TARGET="$XDG_CONFIG_HOME/quickshell/maho-notify"
[ -L "$NOTIFY_TARGET" ] || fail "Maho Notify configuration is not a symlink"
[ "$(readlink -f "$NOTIFY_TARGET")" = "$ROOT/config/quickshell/maho-notify" ] || fail "Maho Notify targets wrong runtime"
[ -r "$NOTIFY_TARGET/shell.qml" ] || fail "Maho Notify entrypoint missing after install"

[ -L "$HYPR_SESSION_TARGET" ] || fail "Maho Hyprland session hook is not managed after migration"
[ "$(readlink -f "$HYPR_SESSION_TARGET")" = "$ROOT/config/hypr/maho/core/session.lua" ] || fail "Maho Hyprland session hook targets wrong runtime"
if grep -Fq 'waybar' "$HYPR_SESSION_TARGET"; then
    fail "migrated normal startup hook still invokes Waybar"
fi

for unit in "${UNITS[@]}"; do
    target="$XDG_CONFIG_HOME/systemd/user/$unit"
    [ -L "$target" ] || fail "user unit is not a symlink: $unit"
    [ "$(readlink -f "$target")" = "$ROOT/systemd/user/$unit" ] || fail "user unit targets wrong runtime: $unit"
    if [ "$unit" = "maho-notify.service" ]; then
        if grep -q -- "--user enable --now $unit" "$SYSTEMCTL_LOG"; then
            fail "Maho Notify activation policy changed during setup"
        fi
    elif [ "$unit" = "maho-hyprland-session.target" ]; then
        if grep -q -- "--user enable --now $unit" "$SYSTEMCTL_LOG"; then
            fail "Hyprland session target was globally enabled instead of session-owned"
        fi
    else
        grep -q -- "--user enable --now $unit" "$SYSTEMCTL_LOG" || fail "service was not enabled: $unit"
    fi
done

grep -q 'maho-security-monitor watch' "$ROOT/systemd/user/maho-security.service" || fail "security service does not use stateful monitor"
grep -q 'maho-shell run' "$ROOT/systemd/user/maho-shell.service" || fail "shell service does not use managed runtime"
grep -q 'maho-notify run' "$ROOT/systemd/user/maho-notify.service" || fail "notify service does not use managed runtime"
"$HOME/.local/bin/maho-adapt" validate-registry | grep -q '^PASS$'
"$HOME/.local/bin/maho-guard" doctor | grep -q 'automatic system mutation: none'
echo "PASS"

echo "=== status ==="
"$HOME/.local/bin/maho-setup" status >/dev/null
echo "PASS"

echo "=== unmanaged command protected ==="
printf '%s\n' '#!/usr/bin/env bash' 'echo external' > "$HOME/.local/bin/maho-security"
chmod +x "$HOME/.local/bin/maho-security"
if bash "$ROOT/bin/maho-setup" install >/dev/null 2>&1; then
    fail "setup overwrote an unmanaged command"
fi
grep -q '^echo external$' "$HOME/.local/bin/maho-security" || fail "unmanaged command was modified"
rm -f "$HOME/.local/bin/maho-security"
bash "$ROOT/bin/maho-setup" install >/dev/null
echo "PASS"

echo "=== unmanaged unit protected ==="
TARGET="$XDG_CONFIG_HOME/systemd/user/maho-observe.service"
rm -f "$TARGET"
printf '%s\n' '[Unit]' 'Description=External observer' > "$TARGET"
if bash "$ROOT/bin/maho-setup" install >/dev/null 2>&1; then
    fail "setup overwrote an unmanaged user unit"
fi
grep -q 'External observer' "$TARGET" || fail "unmanaged unit was modified"
rm -f "$TARGET"
bash "$ROOT/bin/maho-setup" install >/dev/null
echo "PASS"

echo "=== unmanaged Hyprland hook protected ==="
rm -f "$HYPR_SESSION_TARGET"
printf '%s\n' '-- external Hyprland owner' > "$HYPR_SESSION_TARGET"
if bash "$ROOT/bin/maho-setup" install >/dev/null 2>&1; then
    fail "setup overwrote an unrelated Hyprland session hook"
fi
grep -q '^-- external Hyprland owner$' "$HYPR_SESSION_TARGET" || fail "unmanaged Hyprland session hook was modified"
rm -f "$HYPR_SESSION_TARGET"
bash "$ROOT/bin/maho-setup" install >/dev/null
[ -L "$HYPR_SESSION_TARGET" ] || fail "managed Hyprland session hook was not restored"
echo "PASS"

echo "=== unmanaged shell protected ==="
rm -f "$SHELL_TARGET"
mkdir -p "$SHELL_TARGET"
printf '%s\n' 'external-shell' > "$SHELL_TARGET/owner.txt"
if bash "$ROOT/bin/maho-setup" install >/dev/null 2>&1; then
    fail "setup overwrote unmanaged Quickshell configuration"
fi
grep -q '^external-shell$' "$SHELL_TARGET/owner.txt" || fail "unmanaged Quickshell configuration was modified"
rm -rf "$SHELL_TARGET"
bash "$ROOT/bin/maho-setup" install >/dev/null
[ -L "$SHELL_TARGET" ] || fail "managed shell was not restored after unmanaged protection test"
echo "PASS"

echo "=== unmanaged notify protected ==="
rm -f "$NOTIFY_TARGET"
mkdir -p "$NOTIFY_TARGET"
printf '%s\n' 'external-notify' > "$NOTIFY_TARGET/owner.txt"
if bash "$ROOT/bin/maho-setup" install >/dev/null 2>&1; then
    fail "setup overwrote unmanaged Maho Notify configuration"
fi
grep -q '^external-notify$' "$NOTIFY_TARGET/owner.txt" || fail "unmanaged Maho Notify configuration was modified"
rm -rf "$NOTIFY_TARGET"
bash "$ROOT/bin/maho-setup" install >/dev/null
[ -L "$NOTIFY_TARGET" ] || fail "managed Maho Notify was not restored after unmanaged protection test"
echo "PASS"

echo "=== uninstall ==="
"$HOME/.local/bin/maho-setup" uninstall >/dev/null
for name in "${COMMANDS[@]}"; do
    [ ! -e "$HOME/.local/bin/$name" ] || fail "managed launcher survived uninstall: $name"
done
for unit in "${UNITS[@]}"; do
    [ ! -e "$XDG_CONFIG_HOME/systemd/user/$unit" ] || fail "managed unit survived uninstall: $unit"
    if [ "$unit" != "maho-hyprland-session.target" ]; then
        grep -q -- "--user disable --now $unit" "$SYSTEMCTL_LOG" || fail "service was not disabled: $unit"
    fi
done
[ ! -e "$HYPR_SESSION_TARGET" ] && [ ! -L "$HYPR_SESSION_TARGET" ] || fail "managed Hyprland session hook survived uninstall"
[ ! -e "$SHELL_TARGET" ] && [ ! -L "$SHELL_TARGET" ] || fail "managed shell configuration survived uninstall"
[ ! -e "$NOTIFY_TARGET" ] && [ ! -L "$NOTIFY_TARGET" ] || fail "managed Maho Notify configuration survived uninstall"
echo "PASS"

echo "=== Maho Notify packaging contracts ==="
bash "$ROOT/tests/notify-contracts.sh" >/dev/null
echo "PASS"

echo "=== graphical session contracts ==="
bash "$ROOT/tests/session-contracts.sh" >/dev/null
echo "PASS"

echo "ALL V1 SETUP CONTRACTS PASS"
