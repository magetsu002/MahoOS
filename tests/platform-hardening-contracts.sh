#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT/bin/maho-platform-install"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

mkdir -p "$TMP/bin"
cat >"$TMP/bin/systemctl" <<'EOF_SYSTEMCTL'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$MAHO_TEST_SYSTEMCTL_LOG"
case "${1:-}:${2:-}:${3:-}" in
    is-active:--quiet:chronyd.service|is-active:--quiet:ntpd.service|is-active:--quiet:openntpd.service) exit 3 ;;
    is-active:--quiet:systemd-timesyncd.service|is-active:--quiet:rtkit-daemon.service) exit 0 ;;
    is-enabled:--quiet:systemd-timesyncd.service) exit 0 ;;
esac
exit 0
EOF_SYSTEMCTL
chmod +x "$TMP/bin/systemctl"

export PATH="$TMP/bin:$PATH"
export MAHO_TEST_SYSTEMCTL_LOG="$TMP/systemctl.log"
export MAHO_PLATFORM_ALLOW_UNPRIVILEGED=1
export MAHO_PLATFORM_PORTAL_ROOT="$TMP/portal"
export MAHO_PLATFORM_TIMESYNC_ROOT="$TMP/timesync"
export MAHO_PLATFORM_DBUS_ROOT="$TMP/dbus"
export MAHO_PLATFORM_STATE_ROOT="$TMP/state"

echo "=== deliberate platform authorities ==="
"$INSTALLER" preflight >/dev/null
"$INSTALLER" install >/dev/null
"$INSTALLER" status >/dev/null
grep -Fxq 'default=gtk' "$TMP/portal/maho-portals.conf" \
    || fail "GTK fallback is not explicit"
grep -Fxq 'org.freedesktop.impl.portal.ScreenCast=hyprland' "$TMP/portal/maho-portals.conf" \
    || fail "Hyprland is not the explicit screencast backend"
grep -Fxq 'org.freedesktop.impl.portal.FileChooser=gtk' "$TMP/portal/maho-portals.conf" \
    || fail "GTK is not the explicit file chooser backend"
grep -Fxq 'SystemdService=gnome-keyring-daemon.service' "$TMP/dbus/org.freedesktop.secrets.service" \
    || fail "Secret Service D-Bus activation bypasses singleton systemd authority"
grep -Fxq 'FallbackNTP=0.arch.pool.ntp.org 1.arch.pool.ntp.org 2.arch.pool.ntp.org 3.arch.pool.ntp.org' \
    "$TMP/timesync/60-maho.conf" || fail "clock fallback authority is undefined"
grep -Fxq 'enable --now systemd-timesyncd.service' "$MAHO_TEST_SYSTEMCTL_LOG" \
    || fail "timesyncd was not enabled as the clock authority"
grep -Fxq 'start rtkit-daemon.service' "$MAHO_TEST_SYSTEMCTL_LOG" \
    || fail "RTKit was not activated"
if grep -Eq '(restart|try-restart).*(xdg-desktop-portal|gnome-keyring)' "$MAHO_TEST_SYSTEMCTL_LOG"; then
    fail "platform install disrupted the current graphical session"
fi
echo PASS

echo "=== existing clock authority is protected ==="
cat >"$TMP/bin/systemctl" <<'EOF_CONFLICT'
#!/usr/bin/env bash
if [ "${1:-}" = is-active ] && [ "${3:-}" = chronyd.service ]; then exit 0; fi
exit 3
EOF_CONFLICT
chmod +x "$TMP/bin/systemctl"
if "$INSTALLER" install >/dev/null 2>&1; then
    fail "installer accepted a competing active clock authority"
fi
echo PASS

echo "=== package and ownership contracts ==="
grep -Eq "^[[:space:]]*'rtkit'" "$ROOT/packaging/arch/PKGBUILD.in" \
    || fail "RTKit is not a package dependency"
grep -Eq "^[[:space:]]*'xdg-desktop-portal-hyprland'" "$ROOT/packaging/arch/PKGBUILD.in" \
    || fail "Hyprland portal is not a package dependency"
grep -Fq -- '--with-platform' "$ROOT/packaging/arch/maho-install" \
    || fail "release installer cannot request platform policy"
bash -n "$INSTALLER"
echo PASS

echo "ALL PLATFORM HARDENING CONTRACTS PASS"
