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
    is-active:--quiet:chronyd.service|is-active:--quiet:ntpd.service|is-active:--quiet:ntp.service|is-active:--quiet:openntpd.service) exit 3 ;;
    is-enabled:--quiet:chronyd.service|is-enabled:--quiet:ntpd.service|is-enabled:--quiet:ntp.service|is-enabled:--quiet:openntpd.service) exit 1 ;;
    is-active:--quiet:systemd-timesyncd.service|is-active:--quiet:rtkit-daemon.service|is-active:--quiet:systemd-oomd.service|is-active:--quiet:maho-btrfs-scrub-root.timer|is-active:--quiet:systemd-zram-setup@zram0.service) exit 0 ;;
    is-enabled:--quiet:systemd-timesyncd.service|is-enabled:--quiet:systemd-oomd.service|is-enabled:--quiet:maho-btrfs-scrub-root.timer) exit 0 ;;
    is-enabled:*) printf 'disabled\n'; exit 1 ;;
esac
exit 0
EOF_SYSTEMCTL
chmod +x "$TMP/bin/systemctl"

export PATH="$TMP/bin:$PATH"
export MAHO_TEST_SYSTEMCTL_LOG="$TMP/systemctl.log"
export MAHO_PLATFORM_ALLOW_UNPRIVILEGED=1
export MAHO_PLATFORM_PORTAL_ROOT="$TMP/portal"
export MAHO_PLATFORM_TIMESYNC_ROOT="$TMP/timesync"
export MAHO_PLATFORM_PACMAN_ROOT="$TMP/maho"
export MAHO_PLATFORM_DBUS_ROOT="$TMP/dbus"
export MAHO_PLATFORM_ZRAM_ROOT="$TMP/zram"
export MAHO_PLATFORM_SYSTEMD_ROOT="$TMP/systemd-system"
export MAHO_PLATFORM_USER_SYSTEMD_ROOT="$TMP/systemd-user"
export MAHO_PLATFORM_STATE_ROOT="$TMP/state"
export MAHO_PLATFORM_LOCK_FILE="$TMP/maho-platform.lock"
export MAHO_PLATFORM_SYSTEM_UNIT_DIRS="$TMP/deps/system"
export MAHO_PLATFORM_USER_UNIT_DIRS="$TMP/deps/user"
export MAHO_PLATFORM_PORTAL_DATA_ROOT="$TMP/deps/portals"
export MAHO_PLATFORM_ZRAM_GENERATOR="$TMP/deps/zram-generator"
export MAHO_PLATFORM_GNOME_KEYRING="$TMP/deps/gnome-keyring-daemon"
export MAHO_PLATFORM_BTRFS="$TMP/deps/btrfs"
mkdir -p "$TMP/deps/system" "$TMP/deps/user" "$TMP/deps/portals"
for unit in systemd-timesyncd.service systemd-oomd.service rtkit-daemon.service; do printf '[Unit]\nDescription=fixture\n' > "$TMP/deps/system/$unit"; done
printf '[Unit]\nDescription=fixture\n' > "$TMP/deps/user/gnome-keyring-daemon.service"
for portal in gtk.portal hyprland.portal gnome-keyring.portal; do printf '[portal]\nDBusName=fixture\n' > "$TMP/deps/portals/$portal"; done
for dep in "$MAHO_PLATFORM_ZRAM_GENERATOR" "$MAHO_PLATFORM_GNOME_KEYRING" "$MAHO_PLATFORM_BTRFS"; do printf '#!/usr/bin/env bash\nexit 0\n' > "$dep"; chmod +x "$dep"; done

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
grep -Fxq 'enable --now systemd-oomd.service' "$MAHO_TEST_SYSTEMCTL_LOG" \
    || fail "systemd-oomd was not enabled"
grep -Fxq 'start systemd-zram-setup@zram0.service' "$MAHO_TEST_SYSTEMCTL_LOG" \
    || fail "zram was not started"
grep -Fxq 'enable --now maho-btrfs-scrub-root.timer' "$MAHO_TEST_SYSTEMCTL_LOG" \
    || fail "Btrfs scrub schedule was not enabled"
grep -Fxq 'ManagedOOMMemoryPressureLimit=85%' "$TMP/systemd-system/user-.slice.d/60-maho-memory-pressure.conf" \
    || fail "memory-pressure threshold is not conservative and explicit"
grep -Fxq 'ManagedOOMPreference=avoid' "$TMP/systemd-user/maho-shell.service.d/60-maho-memory-pressure.conf" \
    || fail "Maho shell is not protected from first-choice pressure killing"
grep -Fxq 'ConditionPathExists=!/etc/maho/signed-boot-production' "$TMP/systemd-system/limine-snapper-sync.service.d/60-maho-signed-boot.conf" \
    || fail "legacy boot writer is not gated by Signed Boot authority"
grep -Fxq 'OnCalendar=monthly' "$TMP/systemd-system/maho-btrfs-scrub-root.timer" \
    || fail "Btrfs scrub interval is undefined"
grep -Fxq '[cachyos]' "$TMP/maho/pacman.conf" \
    || fail "canonical Maho Pacman authority omits CachyOS"
grep -Fxq 'Include = /etc/pacman.d/cachyos-mirrorlist' "$TMP/maho/pacman.conf" \
    || fail "canonical Maho Pacman authority omits CachyOS mirror authority"
grep -Fxq 'Usage = Sync Search Install Upgrade' "$TMP/maho/pacman.conf" \
    || fail "canonical Maho Pacman authority disables CachyOS upgrades"
[ ! -e "$TMP/sysctl" ] || fail "uncertified sysctl candidate was installed"
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
for package in zram-generator btrfs-progs nvme-cli smartmontools; do
    grep -Eq "^[[:space:]]*'$package'" "$ROOT/packaging/arch/PKGBUILD.in" \
        || fail "$package is not a package dependency"
done
grep -Fq -- '--with-platform' "$ROOT/packaging/arch/maho-install" \
    || fail "release installer cannot request platform policy"
bash -n "$INSTALLER"
echo PASS

echo "ALL PLATFORM HARDENING CONTRACTS PASS"
