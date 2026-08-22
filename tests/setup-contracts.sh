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
    *) exit 0 ;;
esac
EOF_SYSTEMCTL
chmod +x "$TMP/fake-bin/systemctl"

fail() { echo "FAIL: $*" >&2; exit 1; }

COMMANDS=(mahoctl maho-theme maho-wallpaper maho-wallpaper-session maho-observe maho-adapt maho-provenance maho-security maho-setup)
UNITS=(maho-wallpaper.service maho-observe.service maho-security.service)

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
for unit in "${UNITS[@]}"; do
    target="$XDG_CONFIG_HOME/systemd/user/$unit"
    [ -L "$target" ] || fail "user service is not a symlink: $unit"
    [ "$(readlink -f "$target")" = "$ROOT/systemd/user/$unit" ] || fail "user service targets wrong checkout: $unit"
    grep -q -- "--user enable --now $unit" "$SYSTEMCTL_LOG" || fail "service was not enabled: $unit"
done
"$HOME/.local/bin/maho-adapt" validate-registry | grep -q '^PASS$'
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

echo "=== uninstall ==="
"$HOME/.local/bin/maho-setup" uninstall >/dev/null
for name in "${COMMANDS[@]}"; do
    [ ! -e "$HOME/.local/bin/$name" ] || fail "managed launcher survived uninstall: $name"
done
for unit in "${UNITS[@]}"; do
    [ ! -e "$XDG_CONFIG_HOME/systemd/user/$unit" ] || fail "managed unit survived uninstall: $unit"
    grep -q -- "--user disable --now $unit" "$SYSTEMCTL_LOG" || fail "service was not disabled: $unit"
done
echo "PASS"

echo "ALL V1 SETUP CONTRACTS PASS"
