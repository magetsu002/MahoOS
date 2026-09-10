#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HELPER="$ROOT/lib/maho-recovery-overlay"
INSTALLER="$ROOT/bin/maho-recovery-overlay-install"
HOOK="$ROOT/config/mkinitcpio/install/sd-maho-recovery-overlay"
UNIT="$ROOT/config/systemd/initrd/maho-recovery-overlay.service"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BIN="$TMP/bin"
mkdir -p "$BIN" "$TMP/sysroot"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS $*"; }

bash -n "$HELPER" "$INSTALLER"
grep -Fq 'ConditionKernelCommandLine=maho.recovery_snapshot=1' "$UNIT" || fail "unit lacks explicit recovery flag"
grep -Fq 'After=initrd-root-fs.target' "$UNIT" || fail "unit may run before root mount"
grep -Fq 'Before=initrd-switch-root.target' "$UNIT" || fail "unit may run after switch-root"
grep -Fq 'initrd-switch-root.target.requires/maho-recovery-overlay.service' "$HOOK" || fail "initrd does not require overlay setup"
grep -Fq 'add_module overlay' "$HOOK" || fail "overlay kernel module missing"
grep -Fq 'SNAPSHOT_WRITABLE", "no"' "$INSTALLER" || fail "installer can make snapshots writable"
! grep -Eq '/dev/nvme|efibootmgr|bootorder|BootOrder' "$INSTALLER" || fail "installer contains device/UEFI mutation authority"
pass "static recovery overlay safety contract"
cat > "$BIN/findmnt" <<'EOF'
#!/usr/bin/env bash
set -u
args=" $* "
if [[ "$args" == *" -no FSTYPE "* ]]; then
    if [ -e "${FAKE_OVERLAY_ACTIVE:-/nonexistent}" ]; then
        if [ "${FAKE_STACKED_AFTER_OVERLAY:-0}" = 1 ]; then echo "${FAKE_FSTYPE:-btrfs}"; fi
        echo overlay
    else
        echo "${FAKE_FSTYPE:-btrfs}"
    fi
    exit 0
fi
if [[ "$args" == *" -no FSROOT "* ]]; then
    echo "${FAKE_FSROOT:-/@snapshots/42/snapshot}"
    exit 0
fi
if [[ "$args" == *" ${MAHO_RECOVERY_RUN:-/run/maho-recovery-overlay} "* ]]; then
    [ -e "${FAKE_STATE_MOUNTED:-/nonexistent}" ] && exit 0 || exit 1
fi
exit 1
EOF
chmod +x "$BIN/findmnt"

cat > "$BIN/btrfs" <<'EOF'
#!/usr/bin/env bash
echo "ro=${FAKE_RO:-true}"
EOF
chmod +x "$BIN/btrfs"

cat > "$BIN/logger" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$BIN/logger"
cat > "$BIN/mount" <<'EOF'
#!/usr/bin/env bash
set -u
printf '%s\n' "mount $*" >> "${FAKE_MOUNT_LOG:?}"
args=" $* "
if [[ "$args" == *" -t tmpfs "* ]]; then
    touch "${FAKE_STATE_MOUNTED:?}"
fi
if [[ "$args" == *" -t overlay overlay "* ]]; then
    touch "${FAKE_OVERLAY_ACTIVE:?}"
fi
exit 0
EOF
chmod +x "$BIN/mount"

cat > "$BIN/umount" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$BIN/umount"

run_helper() {
    local case_dir="$1"
    mkdir -p "$case_dir/run"
    PATH="$BIN:/usr/bin:/usr/sbin" \
    MAHO_RECOVERY_ROOT="$TMP/sysroot" \
    MAHO_RECOVERY_RUN="$case_dir/run" \
    MAHO_RECOVERY_CMDLINE_FILE="$case_dir/cmdline" \
    FAKE_MOUNT_LOG="$case_dir/mount.log" \
    FAKE_STATE_MOUNTED="$case_dir/state-mounted" \
    FAKE_OVERLAY_ACTIVE="$case_dir/overlay-active" \
    "$HELPER"
}
# No explicit recovery flag: normal boot must be a no-op.
CASE="$TMP/no-flag"
mkdir -p "$CASE"
printf '%s\n' 'root=UUID=test rw rootflags=subvol=@' > "$CASE/cmdline"
run_helper "$CASE"
[ ! -e "$CASE/overlay-active" ] || fail "normal boot activated recovery overlay"
[ ! -e "$CASE/mount.log" ] || fail "normal boot performed mounts"
pass "normal boot is untouched"

# Explicit flag on a non-snapshot root must fail closed.
CASE="$TMP/wrong-root"
mkdir -p "$CASE"
printf '%s\n' 'root=UUID=test rw rootflags=subvol=@ maho.recovery_snapshot=1' > "$CASE/cmdline"
if FAKE_FSROOT='/@' run_helper "$CASE" >/dev/null 2>&1; then
    fail "flagged normal root was accepted"
fi
[ ! -e "$CASE/overlay-active" ] || fail "wrong root activated recovery overlay"
pass "flagged non-snapshot root is rejected"

# A writable snapshot is not an immutable recovery source.
CASE="$TMP/writable"
mkdir -p "$CASE"
printf '%s\n' 'root=UUID=test rw rootflags=subvol=/@snapshots/42/snapshot maho.recovery_snapshot=1' > "$CASE/cmdline"
if FAKE_RO=false run_helper "$CASE" >/dev/null 2>&1; then
    fail "writable snapshot was accepted"
fi
[ ! -e "$CASE/overlay-active" ] || fail "writable snapshot activated recovery overlay"
pass "writable snapshot is rejected"
# Exact read-only Snapper root with the Maho flag gets only an ephemeral overlay.
CASE="$TMP/read-only"
mkdir -p "$CASE"
printf '%s\n' 'root=UUID=test rw rootflags=subvol=/@snapshots/42/snapshot maho.recovery_snapshot=1' > "$CASE/cmdline"
FAKE_STACKED_AFTER_OVERLAY=1 run_helper "$CASE"
[ -e "$CASE/overlay-active" ] || fail "read-only recovery snapshot did not activate overlay"
grep -Fq 'mount -t tmpfs' "$CASE/mount.log" || fail "temporary writable layer was not RAM-backed"
grep -Fq 'mount --bind' "$CASE/mount.log" || fail "immutable lower layer was not bound"
grep -Fq 'mount -o remount,bind,ro' "$CASE/mount.log" || fail "lower layer was not enforced read-only"
grep -Fq 'mount -t overlay overlay' "$CASE/mount.log" || fail "overlay root was not mounted"
[ "$(cat "$CASE/run/source-snapshot")" = '/@snapshots/42/snapshot' ] || fail "source snapshot identity was not recorded"
[ "$(cat "$CASE/run/state")" = active ] || fail "overlay state was not recorded active"
pass "stacked recovery root verifies the topmost overlay mount"

# Product source must never contain authority to flip a snapshot writable.
! grep -Eq 'btrfs[[:space:]]+property[[:space:]]+set.*ro[[:space:]]+false|SNAPSHOT_WRITABLE=yes' \
    "$HELPER" "$INSTALLER" "$HOOK" "$UNIT" || fail "recovery path can mutate snapshot immutability"
pass "snapshot immutability remains authoritative"

echo 'ALL RECOVERY OVERLAY CONTRACTS PASS'
