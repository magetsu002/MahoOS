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
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$TMP/fake-bin"

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

COMMANDS=(
    mahoctl
    maho-theme
    maho-wallpaper
    maho-wallpaper-session
    maho-observe
    maho-adapt
    maho-provenance
    maho-security
    maho-security-monitor
    maho-guard
    maho-contain
    maho-shell
    maho-notify
    maho-session
    maho-launcher
    maho-dock
    maho-files
    maho-link
    maho-lock
    maho-power
    maho-clipboard
    maho-clipboard-history
    maho-setup
)
CORE_UNITS=(maho-observe.service maho-security.service)
GRAPHICAL_UNITS=(
    maho-awww-daemon.service
    maho-wallpaper.service
    maho-shell.service
    maho-dock.service
    maho-notify.service
    maho-clipboard-history.service
)
SESSION_TARGET_UNIT=maho-hyprland-session.target
UNITS=("${CORE_UNITS[@]}" "${GRAPHICAL_UNITS[@]}" "$SESSION_TARGET_UNIT")

UNIT_DIR="$XDG_CONFIG_HOME/systemd/user"

# Seed historical enablement links so setup proves that it removes obsolete
# graphical ownership without touching unrelated targets.
mkdir -p "$UNIT_DIR/default.target.wants" "$UNIT_DIR/graphical-session.target.wants"
ln -s ../maho-wallpaper.service "$UNIT_DIR/default.target.wants/maho-wallpaper.service"
ln -s ../maho-shell.service "$UNIT_DIR/graphical-session.target.wants/maho-shell.service"
ln -s ../maho-hyprland-session.target "$UNIT_DIR/default.target.wants/$SESSION_TARGET_UNIT"

echo "=== preflight ==="
bash "$ROOT/bin/maho-setup" preflight >/dev/null
echo "PASS"

echo "=== install ==="
bash "$ROOT/bin/maho-setup" install >/dev/null
for name in "${COMMANDS[@]}"; do
    path="$HOME/.local/bin/$name"
    [ -x "$path" ] || fail "launcher not executable: $name"
    grep -Fq '# managed-by: maho-setup v1' "$path" || fail "launcher missing ownership marker: $name"
done

SHELL_TARGET="$XDG_CONFIG_HOME/quickshell/maho-shell"
[ -L "$SHELL_TARGET" ] || fail "Maho Shell configuration is not a symlink"
[ "$(readlink -f "$SHELL_TARGET")" = "$ROOT/config/quickshell/maho-shell" ] || fail "Maho Shell targets wrong checkout"
[ -r "$SHELL_TARGET/shell.qml" ] || fail "Maho Shell entrypoint missing after install"

NOTIFY_TARGET="$XDG_CONFIG_HOME/quickshell/maho-notify"
[ -L "$NOTIFY_TARGET" ] || fail "Maho Notify configuration is not a symlink"
[ "$(readlink -f "$NOTIFY_TARGET")" = "$ROOT/config/quickshell/maho-notify" ] || fail "Maho Notify targets wrong checkout"
[ -r "$NOTIFY_TARGET/shell.qml" ] || fail "Maho Notify entrypoint missing after install"

HYPR_SESSION_TARGET="$XDG_CONFIG_HOME/hypr/maho/core/session.lua"
[ -L "$HYPR_SESSION_TARGET" ] || fail "Maho Hyprland session hook is not a symlink"
[ "$(readlink -f "$HYPR_SESSION_TARGET")" = "$ROOT/config/hypr/maho/core/session.lua" ] ||
    fail "Maho Hyprland session hook targets wrong checkout"

FILES_DESKTOP_TARGET="$XDG_DATA_HOME/applications/io.maho.Files.desktop"
[ -L "$FILES_DESKTOP_TARGET" ] || fail "Maho Files desktop entry is not a symlink"
[ "$(readlink -f "$FILES_DESKTOP_TARGET")" = "$ROOT/apps/maho-files/io.maho.Files.desktop" ] ||
    fail "Maho Files desktop entry targets wrong checkout"
grep -Fq 'Exec=maho-files run %U' "$FILES_DESKTOP_TARGET" ||
    fail "Maho Files desktop entry lost canonical launch command"
grep -Fq 'StartupWMClass=io.maho.Files' "$FILES_DESKTOP_TARGET" ||
    fail "Maho Files desktop identity regressed"

for unit in "${UNITS[@]}"; do
    target="$UNIT_DIR/$unit"
    [ -L "$target" ] || fail "user unit is not a symlink: $unit"
    [ "$(readlink -f "$target")" = "$ROOT/systemd/user/$unit" ] ||
        fail "user unit targets wrong checkout: $unit"
done

# Core observers intentionally follow the user manager.
for unit in "${CORE_UNITS[@]}"; do
    grep -q -- "--user enable --now $unit" "$SYSTEMCTL_LOG" ||
        fail "core service was not enabled: $unit"
    grep -Fq 'WantedBy=default.target' "$ROOT/systemd/user/$unit" ||
        fail "core service lost default.target ownership: $unit"
done

# Graphical Maho surfaces are owned only by maho-session through the single
# maho-hyprland-session.target.
for unit in "${GRAPHICAL_UNITS[@]}"; do
    if grep -q -- "--user enable --now $unit" "$SYSTEMCTL_LOG"; then
        fail "graphical service was independently enabled: $unit"
    fi
    if grep -q -- "--user start $unit" "$SYSTEMCTL_LOG"; then
        fail "graphical service was independently started: $unit"
    fi
    grep -Fq 'WantedBy=maho-hyprland-session.target' "$ROOT/systemd/user/$unit" ||
        fail "graphical service is not mapped to the Maho session target: $unit"
    if grep -Fq 'WantedBy=default.target' "$ROOT/systemd/user/$unit"; then
        fail "graphical service regressed to default.target ownership: $unit"
    fi
done

if grep -q -- "--user enable --now $SESSION_TARGET_UNIT" "$SYSTEMCTL_LOG" ||
   grep -q -- "--user start $SESSION_TARGET_UNIT" "$SYSTEMCTL_LOG"; then
    fail "setup independently activated the Maho graphical session target"
fi

[ ! -e "$UNIT_DIR/default.target.wants/maho-wallpaper.service" ] ||
    fail "stale default.target wallpaper ownership survived install"
[ ! -e "$UNIT_DIR/graphical-session.target.wants/maho-shell.service" ] ||
    fail "stale graphical-session.target shell ownership survived install"
[ ! -e "$UNIT_DIR/default.target.wants/$SESSION_TARGET_UNIT" ] ||
    fail "stale default.target session-target ownership survived install"

grep -q 'maho-security-monitor watch' "$ROOT/systemd/user/maho-security.service" ||
    fail "security service does not use stateful monitor"
grep -q 'maho-shell run' "$ROOT/systemd/user/maho-shell.service" ||
    fail "shell service does not use managed runtime"
grep -q 'maho-notify run' "$ROOT/systemd/user/maho-notify.service" ||
    fail "notify service does not use managed runtime"
grep -q 'maho-clipboard-history serve' "$ROOT/systemd/user/maho-clipboard-history.service" ||
    fail "clipboard history service bypasses managed runtime"
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
TARGET="$UNIT_DIR/maho-observe.service"
rm -f "$TARGET"
printf '%s\n' '[Unit]' 'Description=External observer' > "$TARGET"
if bash "$ROOT/bin/maho-setup" install >/dev/null 2>&1; then
    fail "setup overwrote an unmanaged user unit"
fi
grep -q 'External observer' "$TARGET" || fail "unmanaged unit was modified"
rm -f "$TARGET"
bash "$ROOT/bin/maho-setup" install >/dev/null
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

echo "=== unmanaged Hyprland session hook protected ==="
rm -f "$HYPR_SESSION_TARGET"
mkdir -p "$(dirname "$HYPR_SESSION_TARGET")"
printf '%s\n' '-- external-session-hook' > "$HYPR_SESSION_TARGET"
if bash "$ROOT/bin/maho-setup" install >/dev/null 2>&1; then
    fail "setup overwrote unmanaged Hyprland session hook"
fi
grep -q '^-- external-session-hook$' "$HYPR_SESSION_TARGET" ||
    fail "unmanaged Hyprland session hook was modified"
rm -f "$HYPR_SESSION_TARGET"
bash "$ROOT/bin/maho-setup" install >/dev/null
[ -L "$HYPR_SESSION_TARGET" ] ||
    fail "managed Hyprland session hook was not restored"
echo "PASS"

echo "=== unmanaged Maho Files desktop entry protected ==="
rm -f "$FILES_DESKTOP_TARGET"
mkdir -p "$(dirname "$FILES_DESKTOP_TARGET")"
printf '%s\n' '[Desktop Entry]' 'Name=External Files' > "$FILES_DESKTOP_TARGET"
if bash "$ROOT/bin/maho-setup" install >/dev/null 2>&1; then
    fail "setup overwrote unmanaged Maho Files desktop entry"
fi
grep -q '^Name=External Files$' "$FILES_DESKTOP_TARGET" ||
    fail "unmanaged Maho Files desktop entry was modified"
rm -f "$FILES_DESKTOP_TARGET"
bash "$ROOT/bin/maho-setup" install >/dev/null
[ -L "$FILES_DESKTOP_TARGET" ] ||
    fail "managed Maho Files desktop entry was not restored"
echo "PASS"

echo "=== uninstall ==="
"$HOME/.local/bin/maho-setup" uninstall >/dev/null
for name in "${COMMANDS[@]}"; do
    [ ! -e "$HOME/.local/bin/$name" ] || fail "managed launcher survived uninstall: $name"
done
for unit in "${UNITS[@]}"; do
    [ ! -e "$UNIT_DIR/$unit" ] || fail "managed unit survived uninstall: $unit"
done
grep -q -- "--user stop $SESSION_TARGET_UNIT" "$SYSTEMCTL_LOG" ||
    fail "session target was not stopped during uninstall"
for unit in "${CORE_UNITS[@]}"; do
    grep -q -- "--user disable --now $unit" "$SYSTEMCTL_LOG" ||
        fail "core service was not disabled: $unit"
done
for unit in "${GRAPHICAL_UNITS[@]}"; do
    if grep -q -- "--user disable --now $unit" "$SYSTEMCTL_LOG"; then
        fail "graphical service was individually disabled during uninstall: $unit"
    fi
done
[ ! -e "$SHELL_TARGET" ] && [ ! -L "$SHELL_TARGET" ] ||
    fail "managed shell configuration survived uninstall"
[ ! -e "$NOTIFY_TARGET" ] && [ ! -L "$NOTIFY_TARGET" ] ||
    fail "managed Maho Notify configuration survived uninstall"
[ ! -e "$HYPR_SESSION_TARGET" ] && [ ! -L "$HYPR_SESSION_TARGET" ] ||
    fail "managed Hyprland session hook survived uninstall"
[ ! -e "$FILES_DESKTOP_TARGET" ] && [ ! -L "$FILES_DESKTOP_TARGET" ] ||
    fail "managed Maho Files desktop entry survived uninstall"
echo "PASS"

echo "=== Maho Notify packaging contracts ==="
bash "$ROOT/tests/notify-contracts.sh" >/dev/null
echo "PASS"

echo "ALL V1 SETUP CONTRACTS PASS"
