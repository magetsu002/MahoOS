#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
cleanup_tmp() {
  chmod -R u+w "$TMP" 2>/dev/null || true
  rm -rf -- "$TMP"
}
trap cleanup_tmp EXIT

export HOME="$TMP/home"
export XDG_CONFIG_HOME="$TMP/config"
export XDG_DATA_HOME="$TMP/data"
export XDG_STATE_HOME="$TMP/state"
export XDG_CACHE_HOME="$TMP/cache"
export PATH="$TMP/fake-bin:/usr/bin:/bin"
mkdir -p "$HOME/.local/bin" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$TMP/fake-bin"

SYSTEMCTL_LOG="$TMP/systemctl.log"
export MAHO_TEST_SYSTEMCTL_LOG="$SYSTEMCTL_LOG"
cat >"$TMP/fake-bin/systemctl" <<'EOF_SYSTEMCTL'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$MAHO_TEST_SYSTEMCTL_LOG"
case "$*" in
  '--user show-environment') exit 0 ;;
  '--user show maho-notify.service --property=ExecStart --value')
    [ -z "${MAHO_TEST_NOTIFY_EXECSTART:-}" ] || printf '%s\n' "$MAHO_TEST_NOTIFY_EXECSTART"
    exit 0
    ;;
  '--user daemon-reload')
    if [ -n "${MAHO_TEST_DAEMON_RELOAD_COUNT_FILE:-}" ]; then
      count=0
      [ ! -r "$MAHO_TEST_DAEMON_RELOAD_COUNT_FILE" ] || count="$(cat "$MAHO_TEST_DAEMON_RELOAD_COUNT_FILE")"
      count=$((count + 1))
      printf '%s\n' "$count" >"$MAHO_TEST_DAEMON_RELOAD_COUNT_FILE"
      if [ "${MAHO_TEST_FAIL_DAEMON_RELOAD_AT:-0}" -gt 0 ] && [ "$count" -eq "$MAHO_TEST_FAIL_DAEMON_RELOAD_AT" ]; then
        exit 1
      fi
      if [ "${MAHO_TEST_FAIL_DAEMON_RELOAD_AFTER:-0}" -gt 0 ] && [ "$count" -gt "$MAHO_TEST_FAIL_DAEMON_RELOAD_AFTER" ]; then
        exit 1
      fi
    fi
    [ "${MAHO_TEST_FAIL_DAEMON_RELOAD:-0}" = 1 ] && exit 1
    exit 0
    ;;
  *) exit 0 ;;
esac
EOF_SYSTEMCTL
chmod +x "$TMP/fake-bin/systemctl"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$TMP/fake-bin/quickshell"
chmod +x "$TMP/fake-bin/quickshell"

fail() { echo "FAIL: $*" >&2; exit 1; }
COMMANDS=(
  mahoctl maho-theme maho-wallpaper maho-wallpaper-session maho-observe
  maho-adapt maho-adaptive maho-provenance maho-security maho-security-monitor maho-guard maho-guardian-watch
  maho-contain maho-shell maho-notify maho-session maho-launcher maho-dock
  maho-files maho-link maho-lock maho-power maho-update maho-clipboard maho-firewall maho-memory-certify
  maho-clipboard-history maho-lock-sddm-install maho-guardian-runtime-recovery-certify maho-setup
)
CORE_UNITS=(maho-observe.service maho-security.service maho-guardian.service)
PASSIVE_UNITS=()
GRAPHICAL_UNITS=(maho-awww-daemon.service maho-wallpaper.service maho-shell.service maho-dock.service maho-notify.service maho-clipboard-history.service maho-adaptive.service)
SESSION_TARGET_UNIT=maho-hyprland-session.target
UNITS=("${CORE_UNITS[@]}" "${GRAPHICAL_UNITS[@]}" "${PASSIVE_UNITS[@]}" "$SESSION_TARGET_UNIT")

RUNTIME_ROOT="$XDG_DATA_HOME/maho/runtime"
RELEASES="$RUNTIME_ROOT/releases"
CURRENT="$RUNTIME_ROOT/current"
PREVIOUS="$RUNTIME_ROOT/previous"
OLD_RELEASE="$RELEASES/maho-link-693943265af1e8bbfd6bf33db8fd8c1ab2459062"
OLDER_RELEASE="$RELEASES/6d73d9c8d25d0d491c1629572d6b36c1b670cd72a50bc9dd981635a5dc1bd3c1"
UNIT_DIR="$XDG_CONFIG_HOME/systemd/user"
HYPR_SESSION="$XDG_CONFIG_HOME/hypr/maho/core/session.lua"
HYPR_MANAGED_RELS=(
  config/hypr/hyprland.lua
  config/hypr/maho/core/windowing.lua
  config/hypr/maho/core/input.lua
  config/hypr/maho/core/binds.lua
  config/hypr/maho/core/session.lua
  config/hypr/maho/appearance/decorations.lua
  config/hypr/maho/appearance/animations.lua
  config/hypr/maho/theme/fallback.lua
  config/hypr/maho/theme/palette.lua
)
hypr_target_for_test() { printf '%s/hypr/%s\n' "$XDG_CONFIG_HOME" "${1#config/hypr/}"; }
HYPRLOCK_USER="$XDG_CONFIG_HOME/hypr/hyprlock.conf"
SHELL_TARGET="$XDG_CONFIG_HOME/quickshell/maho-shell"
NOTIFY_TARGET="$XDG_CONFIG_HOME/quickshell/maho-notify"
FILES_DESKTOP_TARGET="$XDG_DATA_HOME/applications/io.maho.Files.desktop"

mkdir -p "$OLD_RELEASE/config/quickshell/maho-shell" "$OLD_RELEASE/config/hypr/maho/core" "$OLD_RELEASE/systemd/user" "$OLDER_RELEASE" \
  "$UNIT_DIR/default.target.wants" "$UNIT_DIR/graphical-session.target.wants" "$UNIT_DIR/$SESSION_TARGET_UNIT.wants" \
  "$(dirname "$SHELL_TARGET")" "$(dirname "$HYPR_SESSION")" "$(dirname "$FILES_DESKTOP_TARGET")"
printf '%s\n' '// old shell' >"$OLD_RELEASE/config/quickshell/maho-shell/shell.qml"
printf '%s\n' '-- old session hook' >"$OLD_RELEASE/config/hypr/maho/core/session.lua"
printf '%s\n' '# unrelated user-owned hyprlock config' >"$HYPRLOCK_USER"
for unit in "${UNITS[@]}"; do cp "$ROOT/systemd/user/$unit" "$OLD_RELEASE/systemd/user/$unit"; done
cat >"$OLD_RELEASE/manifest.json" <<'EOF_OLD_MANIFEST'
{"content_sha256":"569b034d66cf37e75c94f4442630e2de21c10db6c006d2fa85d02571d1b37df1","source_revision":"eafcc986adaafbb1f36df09ea9f831af6a0c1a5b","version":1}
EOF_OLD_MANIFEST
ln -s "$OLD_RELEASE" "$CURRENT"
ln -s "$OLDER_RELEASE" "$PREVIOUS"

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
  case "$name" in maho-notify|maho-link|maho-launcher|maho-dock|maho-files|maho-lock|maho-power|maho-clipboard|maho-clipboard-history) continue ;; esac
  write_live_v2_wrapper "$name"
done

cp "$ROOT/bin/maho-notify" "$HOME/.local/bin/maho-notify"; chmod +x "$HOME/.local/bin/maho-notify"
cat >"$HOME/.local/bin/maho-link" <<'EOF_LINK'
#!/usr/bin/env bash
# managed-by: maho-link-final-motion
exec "$HOME/.local/share/maho-link/current/bin/maho-link" "$@"
EOF_LINK
chmod +x "$HOME/.local/bin/maho-link"
cat >"$HOME/.local/bin/maho-launcher" <<'EOF_LAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
RUNTIME="/home/magetsu/.local/share/maho-ux-cleanup-aafda5fd8843eb7bb06eeb51d25b8662dfd55252"
export MAHO_ROOT="$RUNTIME"
exec bash "$RUNTIME/bin/maho-launcher" "$@"
EOF_LAUNCHER
chmod +x "$HOME/.local/bin/maho-launcher"
cat >"$HOME/.local/bin/maho-dock" <<'EOF_DOCK'
#!/usr/bin/env bash
set -u
RUNTIME="${XDG_DATA_HOME:-$HOME/.local/share}/maho-dock"
REAL="$RUNTIME/bin/maho-dock"
export MAHO_ROOT="$RUNTIME"
export MAHO_DOCK_CONFIG="$RUNTIME/config/quickshell/maho-shell/dock-shell.qml"
export MAHO_APP_MODEL="$RUNTIME/lib/maho_app_model.py"
exec bash "$REAL" "$@"
EOF_DOCK
chmod +x "$HOME/.local/bin/maho-dock"
cat >"$HOME/.local/bin/maho-files" <<'EOF_FILES'
#!/usr/bin/env bash
set -euo pipefail
RUNTIME="$HOME/.local/share/maho-files"
SOURCE="$RUNTIME/source"
APP="$RUNTIME/bin/maho-files-app"
exec "$APP" "$@"
EOF_FILES
chmod +x "$HOME/.local/bin/maho-files"
cat >"$HOME/.local/bin/maho-lock" <<'EOF_LOCK'
#!/usr/bin/env bash
# managed-by: maho-lock-install v1
exec "/home/tester/.local/share/maho-lock/current/bin/maho-lock" "$@"
EOF_LOCK
chmod +x "$HOME/.local/bin/maho-lock"
cat >"$HOME/.local/bin/maho-power" <<'EOF_POWER'
#!/usr/bin/env bash
# managed-by: maho-power-install v1
export MAHO_ROOT="/home/tester/.local/share/maho-power/current"
exec "/home/tester/.local/share/maho-power/current/bin/maho-power" "$@"
EOF_POWER
chmod +x "$HOME/.local/bin/maho-power"
cat >"$HOME/.local/bin/maho-clipboard" <<'EOF_CLIPBOARD'
#!/usr/bin/env bash
set -euo pipefail
RUNTIME="/home/magetsu/.local/share/maho-ux-cleanup-aafda5fd8843eb7bb06eeb51d25b8662dfd55252"
exec bash "$RUNTIME/bin/maho-clipboard" "$@"
EOF_CLIPBOARD
chmod +x "$HOME/.local/bin/maho-clipboard"
cp "$ROOT/bin/maho-clipboard-history" "$HOME/.local/bin/maho-clipboard-history"; chmod +x "$HOME/.local/bin/maho-clipboard-history"

for unit in "${UNITS[@]}"; do
  case "$unit" in maho-dock.service|maho-clipboard-history.service) continue ;; esac
  ln -s "$CURRENT/systemd/user/$unit" "$UNIT_DIR/$unit"
done
cat >"$UNIT_DIR/maho-dock.service" <<'EOF_DOCK_UNIT'
[Unit]
Description=Maho Dock
Documentation=https://github.com/magetsu002/MahoOS
StartLimitIntervalSec=0
[Service]
Type=simple
ExecStart=%h/.local/bin/maho-dock run
Restart=always
RestartSec=2
KillMode=process
TimeoutStopSec=5
[Install]
WantedBy=default.target
EOF_DOCK_UNIT
cat >"$UNIT_DIR/maho-clipboard-history.service" <<'EOF_CLIP_UNIT'
[Unit]
Description=Maho Clipboard history capture
After=graphical-session.target
PartOf=graphical-session.target
[Service]
Type=simple
ExecStart=%h/.local/bin/maho-clipboard-history serve
Restart=on-failure
RestartSec=2
TimeoutStopSec=5
[Install]
WantedBy=default.target
EOF_CLIP_UNIT

ln -s "$CURRENT/config/quickshell/maho-shell" "$SHELL_TARGET"
ln -s "$CURRENT/config/hypr/maho/core/session.lua" "$HYPR_SESSION"
mkdir -p "$NOTIFY_TARGET"; printf '%s\n' live-notify-owner >"$NOTIFY_TARGET/owner.txt"; printf '%s\n' '// live Notify directory' >"$NOTIFY_TARGET/shell.qml"
cp "$ROOT/apps/maho-files/io.maho.Files.desktop" "$FILES_DESKTOP_TARGET"
for unit in maho-observe.service maho-security.service maho-guardian.service maho-dock.service maho-clipboard-history.service; do ln -s "$UNIT_DIR/$unit" "$UNIT_DIR/default.target.wants/$unit"; done
for unit in maho-awww-daemon.service maho-wallpaper.service maho-shell.service maho-notify.service; do ln -s "$UNIT_DIR/$unit" "$UNIT_DIR/graphical-session.target.wants/$unit"; done
printf '%s\n' '[Unit]' 'Description=Unrelated Waybar theme watcher' >"$UNIT_DIR/maho-waybar-theme.path"
ln -s "$UNIT_DIR/maho-waybar-theme.path" "$UNIT_DIR/default.target.wants/maho-waybar-theme.path"

describe_path() {
  local path="$1"
  if [ -L "$path" ]; then printf 'L\t%s\t%s\n' "$path" "$(readlink "$path")";
  elif [ -f "$path" ]; then printf 'F\t%s\t%s\n' "$path" "$(sha256sum "$path" | awk '{print $1}')";
  elif [ -d "$path" ]; then printf 'D\t%s\t%s\n' "$path" "$(find "$path" -type f -print0 2>/dev/null | sort -z | xargs -0 -r sha256sum | sha256sum | awk '{print $1}')";
  else printf 'M\t%s\n' "$path"; fi
}
capture_live_state() {
  local out="$1" name unit wants; : >"$out"
  describe_path "$CURRENT" >>"$out"; describe_path "$PREVIOUS" >>"$out"
  for name in "${COMMANDS[@]}"; do describe_path "$HOME/.local/bin/$name" >>"$out"; done
  describe_path "$SHELL_TARGET" >>"$out"; describe_path "$NOTIFY_TARGET" >>"$out"; describe_path "$HYPR_SESSION" >>"$out"; describe_path "$FILES_DESKTOP_TARGET" >>"$out"
  for unit in "${UNITS[@]}"; do describe_path "$UNIT_DIR/$unit" >>"$out"; for wants in default.target.wants graphical-session.target.wants "$SESSION_TARGET_UNIT.wants"; do describe_path "$UNIT_DIR/$wants/$unit" >>"$out"; done; done
  describe_path "$UNIT_DIR/default.target.wants/maho-waybar-theme.path" >>"$out"
}

echo '=== preflight ==='
bash "$ROOT/bin/maho-setup" preflight >/dev/null
echo PASS

echo '=== explicit SDDM integration ==='
cat >"$TMP/fake-bin/sudo" <<'EOF_SUDO'
#!/usr/bin/env bash
exec "$@"
EOF_SUDO
chmod +x "$TMP/fake-bin/sudo"
export MAHO_SDDM_ALLOW_UNPRIVILEGED=1
export MAHO_SDDM_THEME_ROOT="$TMP/sddm/themes"
export MAHO_SDDM_CONFIG_ROOT="$TMP/sddm/config"
export MAHO_SDDM_STATE_ROOT="$TMP/sddm/state"
export MAHO_SDDM_SESSION_ROOT="$TMP/sddm/wayland-sessions"
export MAHO_SDDM_SESSION_LAUNCH_ROOT="$TMP/sddm/lib"
LEGACY_NATIVE_BUILD="$XDG_CACHE_HOME/maho/files-release-build"
mkdir -p "$LEGACY_NATIVE_BUILD"
printf '%s\n' 'CMAKE_HOME_DIRECTORY:INTERNAL=/definitely/foreign/checkout/apps/maho-files' >"$LEGACY_NATIVE_BUILD/CMakeCache.txt"
bash "$ROOT/bin/maho-setup" install --development --with-sddm >/dev/null
[ -x "$HOME/.local/bin/maho-lock-sddm-install" ] || fail 'SDDM installer command was omitted from the managed runtime'
grep -Fxq 'Current=maho-lock' "$MAHO_SDDM_CONFIG_ROOT/90-maho-lock.conf" || \
  fail 'explicit setup did not persist the Maho Lock SDDM theme'
grep -Fxq 'Name=MahoOS' "$MAHO_SDDM_SESSION_ROOT/maho.desktop" || \
  fail 'explicit setup did not install the SDDM-owned MahoOS session'
[ -x "$MAHO_SDDM_SESSION_LAUNCH_ROOT/maho-session-launch" ] || \
  fail 'explicit setup did not install the compositor lifecycle wrapper'
[ -f "$LEGACY_NATIVE_BUILD/CMakeCache.txt" ] || fail 'setup unexpectedly consumed legacy global Maho Files CMake cache'
bash "$ROOT/bin/maho-lock-sddm-install" status >/dev/null || \
  fail 'explicit setup left SDDM integration unverifiable'
unset MAHO_SDDM_ALLOW_UNPRIVILEGED MAHO_SDDM_THEME_ROOT MAHO_SDDM_CONFIG_ROOT MAHO_SDDM_STATE_ROOT
unset MAHO_SDDM_SESSION_ROOT MAHO_SDDM_SESSION_LAUNCH_ROOT
rm -f "$TMP/fake-bin/sudo"
echo PASS

echo '=== validation failure is non-mutating ==='
cp "$HOME/.local/bin/maho-security" "$TMP/maho-security.v2"
printf '%s\n' '#!/usr/bin/env bash' 'echo external-security-owner' >"$HOME/.local/bin/maho-security"; chmod +x "$HOME/.local/bin/maho-security"
capture_live_state "$TMP/before-validation-failure"
if bash "$ROOT/bin/maho-setup" install --development >/dev/null 2>&1; then fail 'installer accepted an unmanaged command'; fi
capture_live_state "$TMP/after-validation-failure"
cmp -s "$TMP/before-validation-failure" "$TMP/after-validation-failure" || fail 'validation failure mutated live wiring'
cp "$TMP/maho-security.v2" "$HOME/.local/bin/maho-security"; chmod +x "$HOME/.local/bin/maho-security"
echo PASS

echo '=== post-switch failure rolls back exact live wiring ==='
capture_live_state "$TMP/before-post-switch-failure"
export MAHO_TEST_FAIL_DAEMON_RELOAD=1
if bash "$ROOT/bin/maho-setup" install --development >/dev/null 2>&1; then fail 'simulated daemon-reload failure unexpectedly succeeded'; fi
unset MAHO_TEST_FAIL_DAEMON_RELOAD
capture_live_state "$TMP/after-post-switch-failure"
cmp -s "$TMP/before-post-switch-failure" "$TMP/after-post-switch-failure" || fail 'post-switch failure did not restore exact pre-install wiring'
echo PASS

echo '=== rollback restore never exposes a present target as missing ==='
ATOMIC_TX="$TMP/atomic-restore"
ATOMIC_TARGET="$TMP/atomic-target/session.lua"
ATOMIC_GAP="$TMP/atomic-restore-gap"
ATOMIC_DONE="$TMP/atomic-restore-done"

mkdir -p "$ATOMIC_TX" "$(dirname "$ATOMIC_TARGET")"

printf '%s\n' old >"$ATOMIC_TX/001"
printf '%s\n' new >"$ATOMIC_TARGET"
printf 'p\t%s\t001\n' "$ATOMIC_TARGET" >"$ATOMIC_TX/manifest"

REAL_CP="$(command -v cp)"

cat >"$TMP/fake-bin/cp" <<EOF_CP
#!/usr/bin/env bash
sleep 0.25
exec "$REAL_CP" "\$@"
EOF_CP
chmod +x "$TMP/fake-bin/cp"

(
  while [ ! -e "$ATOMIC_DONE" ]; do
    if [ ! -e "$ATOMIC_TARGET" ] && [ ! -L "$ATOMIC_TARGET" ]; then
      : >"$ATOMIC_GAP"
      break
    fi
    sleep 0.005
  done
) &
WATCH_PID=$!

set +e
bash -c '
  set -euo pipefail
  script="$1"
  tx="$2"
  set -- __test_source__
  source "$script" >/dev/null
  restore_all "$tx"
' _ "$ROOT/bin/maho-setup" "$ATOMIC_TX"
RESTORE_RC=$?
set -e

: >"$ATOMIC_DONE"
wait "$WATCH_PID" 2>/dev/null || true
rm -f "$TMP/fake-bin/cp"

[ "$RESTORE_RC" -eq 0 ] ||
  fail 'atomic restore helper failed'

[ ! -e "$ATOMIC_GAP" ] ||
  fail 'rollback temporarily exposed a present target as missing'

grep -Fxq old "$ATOMIC_TARGET" ||
  fail 'atomic rollback did not restore original content'

echo PASS

echo '=== successful durable V1 migration ==='
: >"$SYSTEMCTL_LOG"
bash "$ROOT/bin/maho-setup" install --development >/dev/null
NEW_RELEASE="$(readlink -f "$CURRENT")"
[ -n "$NEW_RELEASE" ] || fail 'runtime/current did not resolve'
[ "$NEW_RELEASE" != "$OLD_RELEASE" ] || fail 'runtime/current did not switch'
[ -f "$NEW_RELEASE/manifest.json" ] || fail 'immutable release manifest missing'
[ "$(readlink -f "$PREVIOUS")" = "$OLD_RELEASE" ] || fail 'previous runtime was not retained'
[ -r "$NEW_RELEASE/share/maho/runtime-source-revision" ] ||
  fail 'runtime source provenance stamp missing'

python - "$NEW_RELEASE/manifest.json" "$NEW_RELEASE/share/maho/runtime-source-revision" "$NEW_RELEASE" <<'PY_RUNTIME_PROVENANCE'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text())
revision = pathlib.Path(sys.argv[2]).read_text().strip()
release = pathlib.Path(sys.argv[3])

assert manifest['version'] == 3
assert manifest['source_revision']
assert manifest['content_sha256']
assert revision == manifest['source_revision']
assert release.name == manifest['content_sha256']
PY_RUNTIME_PROVENANCE

FIRST_RELEASE="$NEW_RELEASE"

if find "$NEW_RELEASE" -perm /222 -print -quit | grep -q .; then
  fail 'immutable release contains writable paths'
fi

rm -rf "$NEW_RELEASE/lib/__pycache__" 2>/dev/null || true

python "$NEW_RELEASE/lib/security_boundary.py" doctor >/dev/null

MAHO_ROOT="$NEW_RELEASE" bash "$NEW_RELEASE/bin/maho-security-monitor" doctor >"$TMP/security-monitor-doctor.txt"

grep -Fq 'PASS  security probe' "$TMP/security-monitor-doctor.txt" ||
  fail 'security monitor doctor rejected probe in immutable release'

grep -Fq 'PASS  privilege/network boundary observer' "$TMP/security-monitor-doctor.txt" ||
  fail 'security monitor doctor rejected boundary observer in immutable release'

if find "$NEW_RELEASE" -type d -name __pycache__ -print -quit | grep -q .; then
  fail 'runtime security inspection created bytecode inside immutable release'
fi

bash "$ROOT/bin/maho-setup" install --development >/dev/null
[ "$(readlink -f "$CURRENT")" = "$FIRST_RELEASE" ] ||
  fail 'identical source revision did not reuse deterministic runtime release'
[ -r "$NEW_RELEASE/apps/maho-files/CMakeLists.txt" ] || fail 'native Maho Files source omitted from release'
[ -r "$NEW_RELEASE/apps/maho-files/io.maho.Files.desktop" ] || fail 'Maho Files desktop entry omitted from release'
for name in "${COMMANDS[@]}"; do
  path="$HOME/.local/bin/$name"; [ -x "$path" ] || fail "managed command missing: $name"
  grep -Fq '# managed-by: maho-setup v3' "$path" || fail "managed command lost v3 marker: $name"
  grep -Fq 'maho/runtime/current' "$path" || fail "managed command bypasses runtime/current: $name"
done
grep -Fq 'MAHO_NOTIFY_CONFIG_DIR="$MAHO_ROOT/config/quickshell/maho-notify"' "$HOME/.local/bin/maho-notify" || fail 'Notify wrapper does not force immutable config'
[ -d "$NOTIFY_TARGET" ] && [ ! -L "$NOTIFY_TARGET" ] || fail 'live-owned Notify directory was replaced'
grep -Fq live-notify-owner "$NOTIFY_TARGET/owner.txt" || fail 'live-owned Notify directory was modified'
[ -L "$SHELL_TARGET" ] && [ "$(readlink "$SHELL_TARGET")" = "$CURRENT/config/quickshell/maho-shell" ] || fail 'Shell does not route through runtime/current'
for rel in "${HYPR_MANAGED_RELS[@]}"; do
  target="$(hypr_target_for_test "$rel")"
  [ -L "$target" ] || fail "Maho Hyprland file is not runtime-managed: $rel"
  [ "$(readlink "$target")" = "$CURRENT/$rel" ] || fail "Maho Hyprland file bypasses runtime/current: $rel"
done
grep -Fqx '# unrelated user-owned hyprlock config' "$HYPRLOCK_USER" || fail 'setup touched unrelated hyprlock config'
[ -f "$FILES_DESKTOP_TARGET" ] && [ ! -L "$FILES_DESKTOP_TARGET" ] || fail 'Files desktop entry is not a portal-resolvable generated file'
grep -Fqx "Exec=$HOME/.local/bin/maho-files run %U" "$FILES_DESKTOP_TARGET" || fail 'Files desktop command is not absolute'
grep -Fq 'StartupWMClass=io.maho.Files' "$FILES_DESKTOP_TARGET" || fail 'Files desktop identity regressed'
for unit in "${UNITS[@]}"; do target="$UNIT_DIR/$unit"; [ -L "$target" ] || fail "unit not runtime-managed: $unit"; [ "$(readlink "$target")" = "$CURRENT/systemd/user/$unit" ] || fail "unit bypasses runtime/current: $unit"; done
for unit in "${CORE_UNITS[@]}"; do
  [ -L "$UNIT_DIR/default.target.wants/$unit" ] || fail "core unit not default-owned: $unit"
  [ ! -e "$UNIT_DIR/graphical-session.target.wants/$unit" ] && [ ! -L "$UNIT_DIR/graphical-session.target.wants/$unit" ] || fail "core unit graphically owned: $unit"
done
for unit in "${GRAPHICAL_UNITS[@]}"; do
  [ ! -e "$UNIT_DIR/default.target.wants/$unit" ] && [ ! -L "$UNIT_DIR/default.target.wants/$unit" ] || fail "graphical unit retained default ownership: $unit"
  [ ! -e "$UNIT_DIR/graphical-session.target.wants/$unit" ] && [ ! -L "$UNIT_DIR/graphical-session.target.wants/$unit" ] || fail "graphical unit retained graphical-session ownership: $unit"
done
for unit in "${PASSIVE_UNITS[@]}"; do
  for wants in default.target.wants graphical-session.target.wants "$SESSION_TARGET_UNIT.wants"; do
    [ ! -e "$UNIT_DIR/$wants/$unit" ] && [ ! -L "$UNIT_DIR/$wants/$unit" ] || fail "passive unit unexpectedly enabled: $unit via $wants"
  done
done
for wants in default.target.wants graphical-session.target.wants; do [ ! -e "$UNIT_DIR/$wants/$SESSION_TARGET_UNIT" ] && [ ! -L "$UNIT_DIR/$wants/$SESSION_TARGET_UNIT" ] || fail "session target independently enabled through $wants"; done
[ -L "$UNIT_DIR/default.target.wants/maho-waybar-theme.path" ] || fail 'unrelated Waybar watcher was touched'
if grep -Eq -- '--now|(^| )restart( |$)|(^| )try-restart( |$)' "$SYSTEMCTL_LOG"; then fail 'install restarted or directly activated live services'; fi
"$HOME/.local/bin/maho-setup" status >/dev/null

echo '=== effective Notify execution authority ==='
export MAHO_TEST_NOTIFY_EXECSTART="$HOME/.local/bin/maho-notify run"
"$HOME/.local/bin/maho-setup" status >/dev/null || fail 'canonical Notify wrapper was rejected'
export MAHO_TEST_NOTIFY_EXECSTART="$HOME/Projects/Maho-OS/bin/maho-notify run"
if "$HOME/.local/bin/maho-setup" status >/dev/null 2>&1; then
  fail 'setup status accepted repository-checkout Notify execution authority'
fi
unset MAHO_TEST_NOTIFY_EXECSTART
echo PASS

grep -Fq 'MAHO_ROOT="${MAHO_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/maho/runtime/current}"' "$HOME/.local/bin/maho-setup" || fail 'command wrapper does not honor explicit immutable runtime authority'

echo '=== runtime status verifies immutable payload identity ==='
RUNTIME_PROBE="$NEW_RELEASE/bin/maho-power"
cp -p -- "$RUNTIME_PROBE" "$TMP/maho-power.verified"
chmod u+w "$RUNTIME_PROBE"
printf '
# setup-status-corruption-probe
' >>"$RUNTIME_PROBE"
chmod a-w "$RUNTIME_PROBE"
if "$HOME/.local/bin/maho-setup" status >/dev/null 2>&1; then
  fail 'runtime status accepted payload drift'
fi
chmod u+w "$RUNTIME_PROBE"
cat "$TMP/maho-power.verified" >"$RUNTIME_PROBE"
chmod a-w "$RUNTIME_PROBE"
"$HOME/.local/bin/maho-setup" status >/dev/null || fail 'runtime status did not recover after exact payload restoration'
echo PASS

echo '=== G2 failed activation restores exact verified runtime ==='
make_g2_source() {
  local destination="$1" marker="$2"
  mkdir -p "$destination"
  for dir in bin lib adapters config theme systemd share apps; do
    [ ! -e "$ROOT/$dir" ] || cp -a "$ROOT/$dir" "$destination/"
  done
  mkdir -p "$destination/apps/maho-files/prebuilt" "$destination/share/maho"
  cp "$FIRST_RELEASE/apps/maho-files/prebuilt/maho-files" "$destination/apps/maho-files/prebuilt/maho-files"
  chmod +x "$destination/apps/maho-files/prebuilt/maho-files"
  printf '%s\n' "$marker" >"$destination/share/maho/g2-activation-fixture"
  printf '{"source_revision":"%s"}\n' "$marker" >"$destination/share/maho/release.json"
}

cat >"$TMP/fake-bin/update-desktop-database" <<'EOF_UPDATE_DB'
#!/usr/bin/env bash
if [ "${MAHO_TEST_CORRUPT_WIRING:-0}" = 1 ]; then
  rm -f -- "$MAHO_TEST_CORRUPT_TARGET"
  ln -s -- /nonexistent/maho-g2-health-failure "$MAHO_TEST_CORRUPT_TARGET"
fi
exit 0
EOF_UPDATE_DB
chmod +x "$TMP/fake-bin/update-desktop-database"

G2_SOURCE_ONE="$TMP/g2-source-one"
make_g2_source "$G2_SOURCE_ONE" first-failed-activation
export MAHO_TEST_CORRUPT_WIRING=1
export MAHO_TEST_CORRUPT_TARGET="$SHELL_TARGET"
if bash "$G2_SOURCE_ONE/bin/maho-setup" install --development >/dev/null 2>"$TMP/g2-first-failure.err"; then
  fail 'G2 simulated bad activation unexpectedly succeeded'
fi
unset MAHO_TEST_CORRUPT_WIRING
[ "$(readlink -f "$CURRENT")" = "$FIRST_RELEASE" ] || fail 'G2 did not restore exact pre-activation current runtime'
[ -L "$SHELL_TARGET" ] && [ "$(readlink "$SHELL_TARGET")" = "$CURRENT/config/quickshell/maho-shell" ] || fail 'G2 did not restore exact managed Shell wiring'
grep -Fq 'Guardian verified restoration of the pre-activation Maho runtime' "$TMP/g2-first-failure.err" || fail 'G2 did not report verified rollback'

G2_HISTORY="$XDG_STATE_HOME/maho/security/guardian/recovery-history"
python - "$G2_HISTORY" "$FIRST_RELEASE" <<'PY_G2_RECOVERED'
import json,pathlib,sys
rows=[json.loads(p.read_text()) for p in pathlib.Path(sys.argv[1]).glob('inc-runtime-*.json')]
assert len(rows)==1, rows
row=rows[0]
assert row['severity']==2
assert row['domain']=='maho-runtime'
assert row['provider']=='maho-runtime'
assert row['recovery_mode']=='transactional'
assert row['executor']=='maho-setup'
assert row['guardian_mutation'] is False
assert row['automatic'] is True
assert row['verified'] is True
assert row['status']=='recovered'
assert pathlib.Path(row['replacement_runtime']['path']).resolve()==pathlib.Path(sys.argv[2]).resolve()
assert row['failure_evidence']['healthy'] is False
assert row['failure_evidence']['managed_wiring_matches_current'] is False
assert [x['state'] for x in row['transitions']]==['detected','recovering','verifying','recovered']
assert row['postcondition']['observed']['current_equals_replacement'] is True
assert row['postcondition']['observed']['managed_wiring_matches_current'] is True
assert row['postcondition']['observed']['systemd_reload_accepted_if_available'] is True
PY_G2_RECOVERED
echo PASS

echo '=== G2 failed rollback verification stays unresolved ==='
G2_SOURCE_TWO="$TMP/g2-source-two"
make_g2_source "$G2_SOURCE_TWO" second-failed-activation
: >"$TMP/daemon-reload-count"
export MAHO_TEST_DAEMON_RELOAD_COUNT_FILE="$TMP/daemon-reload-count"
export MAHO_TEST_FAIL_DAEMON_RELOAD_AFTER=1
export MAHO_TEST_CORRUPT_WIRING=1
if bash "$G2_SOURCE_TWO/bin/maho-setup" install --development >/dev/null 2>"$TMP/g2-second-failure.err"; then
  fail 'G2 rollback-verification failure unexpectedly succeeded'
fi
unset MAHO_TEST_CORRUPT_WIRING MAHO_TEST_FAIL_DAEMON_RELOAD_AFTER MAHO_TEST_DAEMON_RELOAD_COUNT_FILE
[ "$(readlink -f "$CURRENT")" = "$FIRST_RELEASE" ] || fail 'G2 failed-verification case did not restore pre-activation current runtime'
grep -Fq 'Guardian could not verify the runtime rollback postcondition' "$TMP/g2-second-failure.err" || fail 'G2 failed-verification case did not remain unresolved'
python - "$G2_HISTORY" <<'PY_G2_UNRESOLVED'
import json,pathlib,sys
rows=[json.loads(p.read_text()) for p in pathlib.Path(sys.argv[1]).glob('inc-runtime-*.json')]
assert len(rows)==2, rows
bad=[r for r in rows if r.get('verified') is False]
assert len(bad)==1, bad
row=bad[0]
assert row['status']=='unresolved'
assert row['automatic'] is True
assert [x['state'] for x in row['transitions']]==['detected','recovering','verifying','verification-failed']
assert row['postcondition']['observed']['current_equals_replacement'] is True
assert row['postcondition']['observed']['managed_wiring_matches_current'] is True
assert row['postcondition']['observed']['systemd_reload_accepted_if_available'] is False
active=pathlib.Path(sys.argv[1]).parent/'active'/f"{row['incident_id']}.json"
assert active.exists()
PY_G2_UNRESOLVED
rm -f "$TMP/fake-bin/update-desktop-database"
echo PASS

echo '=== G2 activation daemon-reload failure is durably recovered ==='
G2_SOURCE_THREE="$TMP/g2-source-three"
make_g2_source "$G2_SOURCE_THREE" third-daemon-reload-failure
: >"$TMP/daemon-reload-count"
export MAHO_TEST_DAEMON_RELOAD_COUNT_FILE="$TMP/daemon-reload-count"
export MAHO_TEST_FAIL_DAEMON_RELOAD_AT=1
if bash "$G2_SOURCE_THREE/bin/maho-setup" install --development >/dev/null 2>"$TMP/g2-third-failure.err"; then
  fail 'G2 daemon-reload activation failure unexpectedly succeeded'
fi
unset MAHO_TEST_FAIL_DAEMON_RELOAD_AT MAHO_TEST_DAEMON_RELOAD_COUNT_FILE
[ "$(readlink -f "$CURRENT")" = "$FIRST_RELEASE" ] || fail 'G2 daemon-reload failure did not restore exact pre-activation runtime'
grep -Fq 'Guardian verified restoration of the pre-activation Maho runtime' "$TMP/g2-third-failure.err" || fail 'G2 daemon-reload failure lacked verified rollback report'
python - "$G2_HISTORY" <<'PY_G2_DAEMON_RELOAD'
import json,pathlib,sys
rows=[json.loads(p.read_text()) for p in pathlib.Path(sys.argv[1]).glob('inc-runtime-*.json')]
matched=[r for r in rows if r.get('failure_evidence',{}).get('stage')=='wire-ownership']
assert len(matched)==1, matched
row=matched[0]
assert row['status']=='recovered'
assert row['verified'] is True
assert row['executor']=='maho-setup'
assert row['guardian_mutation'] is False
assert row['postcondition']['observed']['systemd_reload_accepted_if_available'] is True
PY_G2_DAEMON_RELOAD
echo PASS

echo '=== G2 later healthy activation supersedes stale unresolved incident ==='
G2_SOURCE_FOUR="$TMP/g2-source-four"
make_g2_source "$G2_SOURCE_FOUR" later-healthy-activation
bash "$G2_SOURCE_FOUR/bin/maho-setup" install --development >"$TMP/g2-fourth-success.out" 2>"$TMP/g2-fourth-success.err" || fail 'G2 later healthy activation unexpectedly failed'
grep -Fq 'Guardian archived 1 superseded runtime incident(s)' "$TMP/g2-fourth-success.out" || fail 'G2 later healthy activation did not report stale incident supersession'
python - "$G2_HISTORY" <<'PY_G2_SUPERSEDED'
import json,pathlib,sys
root=pathlib.Path(sys.argv[1])
rows=[json.loads(p.read_text()) for p in root.glob('inc-runtime-*.json')]
superseded=[r for r in rows if r.get('status')=='superseded']
assert len(superseded)==1, superseded
row=superseded[0]
assert row['verified'] is False
assert row['superseded_by_runtime']['verified'] is True
assert [x['state'] for x in row['transitions']][-1]=='superseded'
active=root.parent/'active'/f"{row['incident_id']}.json"
assert not active.exists()
archive=root.parent/'archive'/f"{row['incident_id']}.json"
archived=json.loads(archive.read_text())
assert archived['resolution']['kind']=='superseded-by-verified-runtime'
PY_G2_SUPERSEDED
echo PASS

echo '=== unmanaged Hyprland hook remains protected ==='
rm -f "$HYPR_SESSION"; printf '%s\n' '-- external Hyprland owner' >"$HYPR_SESSION"
capture_live_state "$TMP/before-unmanaged-hypr"
if bash "$ROOT/bin/maho-setup" install --development >/dev/null 2>&1; then fail 'installer overwrote unrelated Hyprland hook'; fi
capture_live_state "$TMP/after-unmanaged-hypr"
cmp -s "$TMP/before-unmanaged-hypr" "$TMP/after-unmanaged-hypr" || fail 'failed Hyprland validation mutated wiring'
rm -f "$HYPR_SESSION"; ln -s "$CURRENT/config/hypr/maho/core/session.lua" "$HYPR_SESSION"
echo PASS

echo '=== unmanaged Maho Files desktop entry remains protected ==='
rm -f "$FILES_DESKTOP_TARGET"; printf '%s\n' '[Desktop Entry]' 'Name=External Files' >"$FILES_DESKTOP_TARGET"
capture_live_state "$TMP/before-unmanaged-files"
if bash "$ROOT/bin/maho-setup" install --development >/dev/null 2>&1; then fail 'installer overwrote unrelated Files desktop entry'; fi
capture_live_state "$TMP/after-unmanaged-files"
cmp -s "$TMP/before-unmanaged-files" "$TMP/after-unmanaged-files" || fail 'failed Files validation mutated wiring'
rm -f "$FILES_DESKTOP_TARGET"
awk -v command="$HOME/.local/bin/maho-files" '
  /^Exec=/ { print "Exec=" command " run %U"; next }
  { print }
' "$ROOT/apps/maho-files/io.maho.Files.desktop" >"$FILES_DESKTOP_TARGET"
echo PASS

echo '=== recovery overlay contracts ==='
bash "$ROOT/tests/recovery-overlay.sh" >/dev/null
echo PASS

echo '=== static session contracts ==='
bash "$ROOT/tests/session-contracts.sh" >/dev/null
echo PASS

echo '=== uninstall ownership ==='
: >"$SYSTEMCTL_LOG"
"$HOME/.local/bin/maho-setup" uninstall >/dev/null
grep -q -- "--user stop $SESSION_TARGET_UNIT" "$SYSTEMCTL_LOG" || fail 'uninstall did not stop Maho graphical target'
for unit in "${CORE_UNITS[@]}"; do grep -q -- "--user disable --now $unit" "$SYSTEMCTL_LOG" || fail "uninstall did not disable core service: $unit"; done
for unit in "${GRAPHICAL_UNITS[@]}"; do if grep -q -- "--user disable --now $unit" "$SYSTEMCTL_LOG"; then fail "uninstall individually disabled graphical service: $unit"; fi; done
for unit in "${PASSIVE_UNITS[@]}"; do grep -q -- "--user stop $unit" "$SYSTEMCTL_LOG" || fail "uninstall did not stop passive service: $unit"; done
for name in "${COMMANDS[@]}"; do [ ! -e "$HOME/.local/bin/$name" ] && [ ! -L "$HOME/.local/bin/$name" ] || fail "managed command survived uninstall: $name"; done
for unit in "${UNITS[@]}"; do [ ! -e "$UNIT_DIR/$unit" ] && [ ! -L "$UNIT_DIR/$unit" ] || fail "managed unit survived uninstall: $unit"; done
[ ! -e "$SHELL_TARGET" ] && [ ! -L "$SHELL_TARGET" ] || fail 'managed Shell mapping survived uninstall'
for rel in "${HYPR_MANAGED_RELS[@]}"; do
  target="$(hypr_target_for_test "$rel")"
  [ ! -e "$target" ] && [ ! -L "$target" ] || fail "managed Maho Hyprland file survived uninstall: $rel"
done
grep -Fqx '# unrelated user-owned hyprlock config' "$HYPRLOCK_USER" || fail 'uninstall touched unrelated hyprlock config'
[ ! -e "$FILES_DESKTOP_TARGET" ] && [ ! -L "$FILES_DESKTOP_TARGET" ] || fail 'managed Files desktop entry survived uninstall'
[ -d "$NOTIFY_TARGET" ] && [ ! -L "$NOTIFY_TARGET" ] || fail 'live-owned Notify directory was removed'
grep -Fq live-notify-owner "$NOTIFY_TARGET/owner.txt" || fail 'live-owned Notify directory changed during uninstall'
[ -L "$CURRENT" ] && [ -d "$CURRENT" ] || fail 'uninstall destroyed immutable runtime history'
[ -L "$UNIT_DIR/default.target.wants/maho-waybar-theme.path" ] || fail 'uninstall touched unrelated Waybar watcher'
echo PASS

echo
printf '%s\n' 'ALL DURABLE V1 SETUP CONTRACTS PASS'
