#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT/bin/maho-platform-install"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT
fail(){ echo "FAIL: $*" >&2; exit 1; }

mkdir -p "$TMP/bin" "$TMP/boot/loader" "$TMP/state"
cat > "$TMP/bin/findmnt" <<'EOF_FINDMNT'
#!/usr/bin/env bash
printf '%s\n' "${MAHO_TEST_FSTYPE:-vfat}"
EOF_FINDMNT
cat > "$TMP/bin/bootctl" <<'EOF_BOOTCTL'
#!/usr/bin/env bash
cmd="${@: -1}"
case "$cmd" in
  is-installed)
    [ "${MAHO_TEST_SYSTEMD_BOOT:-0}" = 1 ] && exit 0 || exit 1
    ;;
  status)
    printf '%s\n' 'Current Boot Loader:'
    printf '        Product: %s\n' "${MAHO_TEST_BOOTLOADER:-Limine 12.8.0}"
    if [ "${MAHO_TEST_SEED_SUPPORT:-0}" = 1 ]; then
      printf '%s\n' '                 ✓ Support for passing random seed to OS'
    else
      printf '%s\n' '                 ✗ Support for passing random seed to OS'
    fi
    exit 0
    ;;
esac
exit 2
EOF_BOOTCTL
chmod +x "$TMP/bin/findmnt" "$TMP/bin/bootctl"

export MAHO_PLATFORM_ALLOW_UNPRIVILEGED=1
export MAHO_PLATFORM_BOOT_ROOT="$TMP/boot"
export MAHO_PLATFORM_STATE_ROOT="$TMP/state"
export MAHO_PLATFORM_BOOTCTL="$TMP/bin/bootctl"
export MAHO_PLATFORM_FINDMNT="$TMP/bin/findmnt"

make_seed(){ python3 - "$TMP/boot/loader/random-seed" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).parent.mkdir(parents=True,exist_ok=True)
Path(sys.argv[1]).write_bytes(bytes(range(32)))
PY
}

make_seed
echo '=== exposed seed is reported, not normalized silently ==='
if "$INSTALLER" esp-seed-status >"$TMP/status.before" 2>&1; then fail 'status accepted exposed seed'; fi
grep -Fq 'FAIL  exposed unused ESP random seed exists' "$TMP/status.before" || fail 'status did not identify exposed seed'
echo PASS

echo '=== Limine-only retirement is private, exact, and idempotent ==='
SEED_SHA="$(sha256sum "$TMP/boot/loader/random-seed" | awk '{print $1}')"
"$INSTALLER" esp-seed-harden >"$TMP/harden.out"
[ ! -e "$TMP/boot/loader/random-seed" ] || fail 'seed survived hardening'
ARCHIVE="$(find "$TMP/state/esp-random-seed" -maxdepth 1 -type f -name '*.bin' -print -quit)"
RECEIPT="$(find "$TMP/state/esp-random-seed" -maxdepth 1 -type f -name '*.json' -print -quit)"
[ -n "$ARCHIVE" ] && [ -n "$RECEIPT" ] || fail 'rollback archive or receipt missing'
[ "$(stat -c '%a' "$ARCHIVE")" = 600 ] || fail 'rollback archive is not private'
[ "$(stat -c '%a' "$RECEIPT")" = 600 ] || fail 'receipt is not private'
[ "$(sha256sum "$ARCHIVE" | awk '{print $1}')" = "$SEED_SHA" ] || fail 'rollback archive does not preserve exact seed'
python3 - "$RECEIPT" "$SEED_SHA" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
assert r['kind']=='maho-esp-random-seed-retirement',r
assert r['status']=='committed',r
assert r['prepared_at'] and r['completed_at'],r
assert r['seed_sha256']==sys.argv[2],r
assert r['seed_bytes']==32,r
assert r['policy']['fstype']=='vfat',r
assert r['policy']['bootloader'].startswith('Limine '),r
assert '✗' in r['policy']['random_seed_feature'],r
assert r['firmware_variables_modified'] is False,r
assert r['mount_policy_modified'] is False,r
PY
"$INSTALLER" esp-seed-status >/dev/null
before_count="$(find "$TMP/state/esp-random-seed" -maxdepth 1 -type f | wc -l)"
"$INSTALLER" esp-seed-harden >/dev/null
after_count="$(find "$TMP/state/esp-random-seed" -maxdepth 1 -type f | wc -l)"
[ "$before_count" = "$after_count" ] || fail 'idempotent hardening created extra evidence'
echo PASS

echo '=== systemd-boot ownership fails closed ==='
make_seed
export MAHO_TEST_SYSTEMD_BOOT=1
if "$INSTALLER" esp-seed-harden >/dev/null 2>&1; then fail 'systemd-boot seed was removed'; fi
[ -e "$TMP/boot/loader/random-seed" ] || fail 'systemd-boot refusal still removed seed'
unset MAHO_TEST_SYSTEMD_BOOT
echo PASS

echo '=== seed-capable or ambiguous bootloader fails closed ==='
export MAHO_TEST_SEED_SUPPORT=1
if "$INSTALLER" esp-seed-harden >/dev/null 2>&1; then fail 'seed-capable Limine state was mutated'; fi
[ -e "$TMP/boot/loader/random-seed" ] || fail 'capability refusal still removed seed'
unset MAHO_TEST_SEED_SUPPORT
export MAHO_TEST_BOOTLOADER='GRUB 2.14'
if "$INSTALLER" esp-seed-harden >/dev/null 2>&1; then fail 'non-Limine bootloader was mutated'; fi
[ -e "$TMP/boot/loader/random-seed" ] || fail 'bootloader refusal still removed seed'
unset MAHO_TEST_BOOTLOADER
echo PASS

echo '=== non-VFAT layouts fail closed ==='
export MAHO_TEST_FSTYPE=ext4
if "$INSTALLER" esp-seed-harden >/dev/null 2>&1; then fail 'non-VFAT boot layout was mutated'; fi
[ -e "$TMP/boot/loader/random-seed" ] || fail 'filesystem refusal still removed seed'
unset MAHO_TEST_FSTYPE
echo PASS

echo '=== certified recovery readability is not traded away ==='
grep -Fq '[ "$(id -u)" -ne 0 ] || fail "build as normal user"' "$ROOT/bin/maho-guardian-recovery-r3-build" || fail 'R3 normal-user build contract regressed'
grep -Fq 'cp /boot/vmlinuz-linux-cachyos-lts' "$ROOT/bin/maho-guardian-recovery-r3-build" || fail 'R3 no longer consumes normal-user-readable ESP kernel evidence'
if grep -Fq '/etc/fstab' "$ROOT/lib/maho_platform_install.py"; then fail 'ESP seed fix edits fstab'; fi
if grep -Eq 'mount[^A-Za-z_].*(/boot|boot_root)|remount' "$ROOT/lib/maho_platform_install.py"; then fail 'ESP seed fix remounts the boot filesystem'; fi
echo PASS

echo 'ALL ESP RANDOM-SEED SECURITY CONTRACTS PASS'
