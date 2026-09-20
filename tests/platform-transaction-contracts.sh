#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT/bin/maho-platform-install"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

export MAHO_PLATFORM_ALLOW_UNPRIVILEGED=1
export MAHO_PLATFORM_PORTAL_ROOT="$TMP/live/portal"
export MAHO_PLATFORM_TIMESYNC_ROOT="$TMP/live/timesync"
export MAHO_PLATFORM_PACMAN_ROOT="$TMP/live/maho"
export MAHO_PLATFORM_DBUS_ROOT="$TMP/live/dbus"
export MAHO_PLATFORM_ZRAM_ROOT="$TMP/live/zram"
export MAHO_PLATFORM_SYSTEMD_ROOT="$TMP/live/systemd-system"
export MAHO_PLATFORM_USER_SYSTEMD_ROOT="$TMP/live/systemd-user"
export MAHO_PLATFORM_STATE_ROOT="$TMP/platform-state"
export MAHO_PLATFORM_LOCK_FILE="$TMP/run/maho-platform.lock"
export MAHO_PLATFORM_SYSTEM_UNIT_DIRS="$TMP/deps/system"
export MAHO_PLATFORM_USER_UNIT_DIRS="$TMP/deps/user"
export MAHO_PLATFORM_PORTAL_DATA_ROOT="$TMP/deps/portals"
export MAHO_PLATFORM_ZRAM_GENERATOR="$TMP/deps/zram-generator"
export MAHO_PLATFORM_GNOME_KEYRING="$TMP/deps/gnome-keyring-daemon"
export MAHO_PLATFORM_BTRFS="$TMP/deps/btrfs"
export MAHO_TEST_SYSTEMCTL_STATE="$TMP/systemctl-state"
export MAHO_TEST_SYSTEMCTL_LOG="$TMP/systemctl.log"
export PATH="$TMP/bin:/usr/bin:/bin"

mkdir -p "$TMP/bin"
cat > "$TMP/bin/systemctl" <<'EOF_SYSTEMCTL'
#!/usr/bin/env bash
set -u
state="$MAHO_TEST_SYSTEMCTL_STATE"
mkdir -p "$state/enabled" "$state/active"
printf '%s\n' "$*" >> "$MAHO_TEST_SYSTEMCTL_LOG"
read_state() { local kind="$1" unit="$2" default="$3" file; file="$state/$kind/$unit"; [ -f "$file" ] && cat "$file" || printf '%s\n' "$default"; }
write_state() { printf '%s\n' "$3" > "$state/$1/$2"; }
cmd="${1:-}"; shift || true
case "$cmd" in
  daemon-reload) exit 0 ;;
  is-active)
    [ "${1:-}" = --quiet ] && shift
    unit="${1:-}"; value="$(read_state active "$unit" inactive)"
    [ "$value" = active ] && exit 0
    [ "${1:-}" != --quiet ] && printf '%s\n' "$value"
    exit 3 ;;
  is-enabled)
    quiet=0; [ "${1:-}" = --quiet ] && { quiet=1; shift; }
    unit="${1:-}"; value="$(read_state enabled "$unit" disabled)"
    [ "$quiet" -eq 1 ] || printf '%s\n' "$value"
    case "$value" in enabled|enabled-runtime|static|indirect|alias|generated) exit 0 ;; *) exit 1 ;; esac ;;
  enable)
    now=0; runtime=0
    while [ "${1:-}" = --now ] || [ "${1:-}" = --runtime ]; do
      [ "$1" = --now ] && now=1 || runtime=1
      shift
    done
    unit="${1:-}"; [ "$runtime" -eq 1 ] && value=enabled-runtime || value=enabled
    write_state enabled "$unit" "$value"; [ "$now" -eq 0 ] || write_state active "$unit" active; exit 0 ;;
  disable)
    [ "${1:-}" = --now ] && shift
    unit="${1:-}"; write_state enabled "$unit" disabled; [ "${1:-}" = --now ] && write_state active "$unit" inactive; exit 0 ;;
  start) unit="${1:-}"; write_state active "$unit" active; exit 0 ;;
  stop) unit="${1:-}"; write_state active "$unit" inactive; exit 0 ;;
esac
exit 0
EOF_SYSTEMCTL
cat > "$TMP/bin/swapon" <<'EOF_SWAPON'
#!/usr/bin/env bash
exit 0
EOF_SWAPON
chmod +x "$TMP/bin/systemctl" "$TMP/bin/swapon"

units=(systemd-timesyncd.service systemd-oomd.service rtkit-daemon.service)
providers=(systemd-timesyncd.service systemd-oomd.service systemd-zram-setup@zram0.service rtkit-daemon.service maho-btrfs-scrub-root.timer)
conflicts=(chronyd.service ntpd.service ntp.service openntpd.service)

reset_case() {
  rm -rf "$TMP/live" "$TMP/platform-state" "$TMP/run" "$TMP/deps" "$TMP/systemctl-state" "$TMP/systemctl.log"
  mkdir -p "$MAHO_PLATFORM_PORTAL_ROOT" "$MAHO_PLATFORM_TIMESYNC_ROOT" "$MAHO_PLATFORM_DBUS_ROOT" \
    "$MAHO_PLATFORM_ZRAM_ROOT" "$MAHO_PLATFORM_PACMAN_ROOT" "$MAHO_PLATFORM_SYSTEMD_ROOT" "$MAHO_PLATFORM_USER_SYSTEMD_ROOT" \
    "$TMP/deps/system" "$TMP/deps/user" "$TMP/deps/portals" "$TMP/systemctl-state/enabled" "$TMP/systemctl-state/active"
  : > "$TMP/systemctl.log"
  for unit in "${units[@]}"; do printf '[Unit]\nDescription=fixture\n' > "$TMP/deps/system/$unit"; done
  printf '[Unit]\nDescription=fixture\n' > "$TMP/deps/user/gnome-keyring-daemon.service"
  for portal in gtk.portal hyprland.portal gnome-keyring.portal; do printf '[portal]\nDBusName=fixture\n' > "$TMP/deps/portals/$portal"; done
  for dep in "$MAHO_PLATFORM_ZRAM_GENERATOR" "$MAHO_PLATFORM_GNOME_KEYRING" "$MAHO_PLATFORM_BTRFS"; do printf '#!/usr/bin/env bash\nexit 0\n' > "$dep"; chmod +x "$dep"; done
  for unit in "${providers[@]}" "${conflicts[@]}"; do printf 'disabled\n' > "$TMP/systemctl-state/enabled/$unit"; printf 'inactive\n' > "$TMP/systemctl-state/active/$unit"; done
  cat > "$MAHO_PLATFORM_PORTAL_ROOT/maho-portals.conf" <<'EOF_OLD'
# managed-by: maho-platform v1
[preferred]
default=old-fixture
EOF_OLD
  unset MAHO_PLATFORM_TEST_FAIL || true
}

target_fingerprint() {
  python - "$TMP/live" <<'PY_FP'
import hashlib,sys
from pathlib import Path
root=Path(sys.argv[1]); h=hashlib.sha256()
if root.exists():
    for path in sorted(p for p in root.rglob('*') if p.is_file() or p.is_symlink()):
        h.update(str(path.relative_to(root)).encode()+b'\0')
        if path.is_symlink(): h.update(b'L'+str(path.readlink()).encode())
        else: h.update(b'F'+path.read_bytes())
print(h.hexdigest())
PY_FP
}

latest_receipt() {
  local dir
  dir="$(find "$MAHO_PLATFORM_STATE_ROOT/transactions" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)"
  [ -n "$dir" ] || return 1
  printf '%s/receipt.json\n' "$dir"
}

assert_failed_receipt() {
  local receipt="$1"
  python - "$receipt" <<'PY_RECEIPT'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d['kind']=='maho-platform-transaction'
assert d['status']=='failed'
assert d['source_revision'] and len(d['source_revision'])==40
assert d['previous_state_identity']
assert d['resulting_state_identity']
rb=d['rollback']
assert rb['ok'] is True, rb
assert isinstance(d.get('failure'),str) and d['failure']
PY_RECEIPT
}

assert_no_temp_debris() {
  if find "$TMP/live" -name '.maho-platform.*' -print -quit | grep -q .; then fail "temporary target debris remained"; fi
  if find "$MAHO_PLATFORM_STATE_ROOT/transactions" -type d -name stage -print -quit 2>/dev/null | grep -q .; then fail "transaction stage debris remained"; fi
}

run_failure() {
  local label="$1" setup="$2" point="${3:-}"
  reset_case
  eval "$setup"
  local before after rc receipt
  before="$(target_fingerprint)"
  [ -z "$point" ] || export MAHO_PLATFORM_TEST_FAIL="$point"
  set +e
  "$INSTALLER" install >"$TMP/out" 2>"$TMP/err"
  rc=$?
  set -e
  unset MAHO_PLATFORM_TEST_FAIL || true
  [ "$rc" -ne 0 ] || fail "$label unexpectedly succeeded"
  after="$(target_fingerprint)"
  [ "$before" = "$after" ] || { echo "--- stderr ---" >&2; cat "$TMP/err" >&2; fail "$label did not restore previous managed file state"; }
  if "$INSTALLER" status >/dev/null 2>&1; then fail "$label left a false PASS status"; fi
  receipt="$(latest_receipt)" || fail "$label did not persist a transaction receipt"
  assert_failed_receipt "$receipt"
  assert_no_temp_debris
  echo "PASS  $label"
}

echo '=== transactional preflight and rollback failures ==='
run_failure 'unmanaged target conflict' 'printf "unmanaged\n" > "$MAHO_PLATFORM_TIMESYNC_ROOT/60-maho.conf"'
run_failure 'missing dependency' 'rm -f "$MAHO_PLATFORM_BTRFS"'
run_failure 'unwritable destination' 'chmod 0555 "$MAHO_PLATFORM_TIMESYNC_ROOT"'
run_failure 'masked service' 'printf "masked\n" > "$TMP/systemctl-state/enabled/systemd-oomd.service"'
run_failure 'enabled competing NTP provider' 'printf "enabled\n" > "$TMP/systemctl-state/enabled/chronyd.service"'
run_failure 'D-Bus activation conflict' 'printf "unmanaged\n" > "$MAHO_PLATFORM_DBUS_ROOT/org.freedesktop.secrets.service"'
run_failure 'stage write failure' ':' 'stage:portal'
run_failure 'commit failure' ':' 'commit:timesync'
run_failure 'timesyncd activation failure' ':' 'activate:timesyncd'
run_failure 'oomd activation failure' ':' 'activate:oomd'
run_failure 'zram activation failure' ':' 'activate:zram'
run_failure 'RTKit activation failure' ':' 'activate:rtkit'
run_failure 'scrub timer activation failure' ':' 'activate:scrub'

echo '=== concurrent transaction lock fails closed ==='
reset_case
mkdir -p "$(dirname "$MAHO_PLATFORM_LOCK_FILE")"
exec 8>"$MAHO_PLATFORM_LOCK_FILE"
flock -n 8 || fail 'could not acquire fixture platform lock'
if "$INSTALLER" preflight >/dev/null 2>&1; then fail 'preflight ignored a competing platform transaction'; fi
flock -u 8
exec 8>&-
echo PASS

echo '=== partial activation restores prior provider state ==='
reset_case
export MAHO_PLATFORM_TEST_FAIL='activate:oomd'
set +e
"$INSTALLER" install >/dev/null 2>&1
rc=$?
set -e
unset MAHO_PLATFORM_TEST_FAIL
[ "$rc" -ne 0 ] || fail 'partial activation fixture unexpectedly succeeded'
[ "$(cat "$TMP/systemctl-state/enabled/systemd-timesyncd.service")" = disabled ] || { cat "$TMP/systemctl.log" >&2; cat "$(latest_receipt)" >&2; fail 'timesyncd enable state was not rolled back'; }
[ "$(cat "$TMP/systemctl-state/active/systemd-timesyncd.service")" = inactive ] || fail 'timesyncd active state was not rolled back'
assert_failed_receipt "$(latest_receipt)"
assert_no_temp_debris
echo PASS

echo '=== runtime-only enabled state is restored exactly ==='
reset_case
printf 'enabled-runtime\n' > "$TMP/systemctl-state/enabled/systemd-timesyncd.service"
export MAHO_PLATFORM_TEST_FAIL='activate:oomd'
set +e
"$INSTALLER" install >/dev/null 2>&1
rc=$?
set -e
unset MAHO_PLATFORM_TEST_FAIL
[ "$rc" -ne 0 ] || fail 'runtime-enabled rollback fixture unexpectedly succeeded'
[ "$(cat "$TMP/systemctl-state/enabled/systemd-timesyncd.service")" = enabled-runtime ] || fail 'runtime-only enabled state was not restored'
[ "$(cat "$TMP/systemctl-state/active/systemd-timesyncd.service")" = inactive ] || fail 'runtime-enabled active state was not restored'
assert_failed_receipt "$(latest_receipt)"
echo PASS

echo '=== successful install and idempotent reinstall ==='
reset_case
"$INSTALLER" preflight >/dev/null
"$INSTALLER" install > "$TMP/success-1"
"$INSTALLER" status >/dev/null
first="$(target_fingerprint)"
"$INSTALLER" install > "$TMP/success-2"
"$INSTALLER" status >/dev/null
second="$(target_fingerprint)"
[ "$first" = "$second" ] || fail 'idempotent reinstall changed candidate file identity'
receipt="$(latest_receipt)"
python - "$receipt" <<'PY_SUCCESS'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
assert d['status']=='committed'
assert d['verification']['ok'] is True
assert d['previous_state_identity']
assert d['resulting_state_identity']
assert len(d['files'])==12
assert len(d['service_changes'])==5
PY_SUCCESS
assert_no_temp_debris
for unit in systemd-timesyncd.service systemd-oomd.service maho-btrfs-scrub-root.timer; do
  [ "$(cat "$TMP/systemctl-state/enabled/$unit")" = enabled ] || fail "$unit not enabled"
  [ "$(cat "$TMP/systemctl-state/active/$unit")" = active ] || fail "$unit not active"
done
for unit in systemd-zram-setup@zram0.service rtkit-daemon.service; do
  [ "$(cat "$TMP/systemctl-state/active/$unit")" = active ] || fail "$unit not active"
done
echo PASS

echo 'ALL PLATFORM TRANSACTION CONTRACTS PASS'
