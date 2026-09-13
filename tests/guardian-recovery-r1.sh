#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HELPER="$ROOT/lib/maho-guardian-recovery-r1"
BUILDER="$ROOT/bin/maho-guardian-recovery-r1-build"
STAGER="$ROOT/bin/maho-guardian-recovery-r1-stage"
HOOK="$ROOT/config/mkinitcpio/install/sd-maho-guardian-recovery-r1"
UNIT="$ROOT/config/systemd/initrd/maho-guardian-recovery-r1.service"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS $*"; }

bash -n "$HELPER" "$BUILDER" "$STAGER" "$HOOK"
grep -Fxq 'ConditionKernelCommandLine=maho.guardian_recovery=r1' "$UNIT" || fail "R1 unit is not explicitly gated"
grep -Fq 'suspected_kernel_cannot_certify_itself' "$HELPER" || fail "self-certification refusal is missing"
grep -Fq 'root_not_read_only' "$HELPER" || fail "read-only-root enforcement is missing"
grep -Fq 'add_module vfat' "$HOOK" || fail "R1 initramfs cannot mount the FAT ESP for durable evidence"
grep -Fq 'report_persistence_failed' "$HELPER" || fail "report persistence is not fail-closed"
grep -Fq 'default_entry: MahoOS/Primary' "$STAGER" || fail "stager does not preserve normal default authority"
! grep -Eq 'efibootmgr|BootOrder|BootNext|/dev/nvme' "$HELPER" "$BUILDER" "$STAGER" || fail "R1 contains forbidden firmware/device authority"
pass "static R1 safety contract"

mkdir -p "$TMP/bin" "$TMP/sysroot" "$TMP/state" "$TMP/contracts"
mkdir -p "$TMP/esp/MahoOS/guardian-recovery-r1"
cp "$HELPER" "$TMP/self"
for name in maho_trust_identity.py maho_generation_v2.py maho_kernel_generation.py guardian_offline_recovery.py; do
    cp "$ROOT/lib/$name" "$TMP/contracts/$name"
done
cat > "$TMP/bin/findmnt" <<'EOF'
#!/usr/bin/env bash
args=" $* "
case "$args" in
  *" -no FSTYPE "*) echo btrfs ;;
  *" -no UUID "*) echo test-root-uuid ;;
  *" -no FSROOT "*) echo /@ ;;
  *" -no OPTIONS "*) echo "${FAKE_ROOT_OPTS:-ro,relatime,subvol=/@}" ;;
  *) exit 1 ;;
esac
EOF
cat > "$TMP/bin/blkid" <<'EOF'
#!/usr/bin/env bash
echo /dev/fake-esp
EOF
cat > "$TMP/bin/uname" <<'EOF'
#!/usr/bin/env bash
[ "${1:-}" = -r ] && { echo 6.18-test; exit 0; }
exec /usr/bin/uname "$@"
EOF
chmod +x "$TMP/bin/findmnt" "$TMP/bin/blkid" "$TMP/bin/uname"

cat > "$TMP/bin/mount" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
target="${@: -1}"
[ "${FAKE_MOUNT_FAIL:-0}" != 1 ] || exit 32
mkdir -p "$target"
cp -a "${FAKE_ESP_SOURCE:?}/." "$target/"
printf '%s\n' "mount $*" >> "${FAKE_MOUNT_LOG:?}"
EOF
cat > "$TMP/bin/umount" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
target="${@: -1}"
report="$target/MahoOS/guardian-recovery-r1/report.json"
if [ -f "$report" ]; then
  mkdir -p "${FAKE_ESP_SOURCE:?}/MahoOS/guardian-recovery-r1"
  cp "$report" "${FAKE_ESP_SOURCE}/MahoOS/guardian-recovery-r1/report.json"
fi
exit 0
EOF
chmod +x "$TMP/bin/mount" "$TMP/bin/umount"
printf 'kernel-payload\n' > "$TMP/esp/MahoOS/guardian-recovery-r1/vmlinuz"
printf 'initramfs-payload\n' > "$TMP/esp/MahoOS/guardian-recovery-r1/initramfs.img"
printf 'microcode-payload\n' > "$TMP/esp/MahoOS/guardian-recovery-r1/intel-ucode.img"

make_manifest() {
    local suspected="$1"
    ROOT="$ROOT" TMP="$TMP" SUSPECTED="$suspected" python3 - <<'PY'
import hashlib, json, os
from pathlib import Path
repo=Path(os.environ['ROOT']); tmp=Path(os.environ['TMP'])
esp=tmp/'esp/MahoOS/guardian-recovery-r1'
def h(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
contracts={name:h(tmp/'contracts'/name) for name in (
    'maho_trust_identity.py','maho_generation_v2.py','maho_kernel_generation.py','guardian_offline_recovery.py')}
m={
 'schema_version':1,'campaign_id':'r1-test-00000000','source_revision':'test-source',
 'certification_scope':'native-r1-independent-kernel-read-only-root',
 'trust_claim':'mechanics-only-not-secure-boot-certified',
 'root':{'uuid':'test-root-uuid','fsroot':'/@'},
 'esp':{'partuuid':'12345678-abcd-1234-abcd-1234567890ab'},
 'suspected_running_kernel':{'release':os.environ['SUSPECTED']},
 'recovery_kernel':{'release':'6.18-test'},
 'payload':{
   'kernel':{'path':'/MahoOS/guardian-recovery-r1/vmlinuz','sha256':h(esp/'vmlinuz')},
   'initramfs':{'path':'/MahoOS/guardian-recovery-r1/initramfs.img','sha256':h(esp/'initramfs.img')},
   'microcode':{'path':'/MahoOS/guardian-recovery-r1/intel-ucode.img','sha256':h(esp/'intel-ucode.img')}},
 'verifier':{'sha256':h(tmp/'self')},'contracts':contracts}
text=json.dumps(m,sort_keys=True,separators=(',',':'))+'\n'
(esp/'manifest.json').write_text(text)
print(hashlib.sha256(text.encode()).hexdigest())
PY
}
run_helper() {
    local digest="$1" root_opts="${2:-ro,relatime,subvol=/@}" mount_fail="${3:-0}"
    printf '%s\n' "root=UUID=test-root-uuid ro rootflags=subvol=@,ro maho.guardian_recovery=r1 maho.guardian_manifest_sha256=$digest maho.guardian_esp_partuuid=12345678-abcd-1234-abcd-1234567890ab maho.guardian_campaign=r1-test-00000000" > "$TMP/cmdline"
    rm -rf "$TMP/state" && mkdir -p "$TMP/state"
    PATH="$TMP/bin:/usr/bin:/usr/sbin" \
    MAHO_R1_ROOT="$TMP/sysroot" \
    MAHO_R1_STATE="$TMP/state" \
    MAHO_R1_CMDLINE_FILE="$TMP/cmdline" \
    MAHO_R1_MOUNT_BIN="$TMP/bin/mount" \
    MAHO_R1_UMOUNT_BIN="$TMP/bin/umount" \
    MAHO_R1_SELF_PATH="$TMP/self" \
    MAHO_R1_CONTRACT_ROOT="$TMP/contracts" \
    MAHO_R1_NO_REBOOT=1 \
    FAKE_ROOT_OPTS="$root_opts" \
    FAKE_ESP_SOURCE="$TMP/esp" \
    FAKE_MOUNT_LOG="$TMP/mount.log" \
    FAKE_MOUNT_FAIL="$mount_fail" \
    "$HELPER"
}

digest="$(make_manifest 7.1-test)"
run_helper "$digest"
[ "$(jq -r .outcome "$TMP/esp/MahoOS/guardian-recovery-r1/report.json")" = PASS ] || fail "valid R1 fixture did not pass"
[ "$(jq -r .reason "$TMP/esp/MahoOS/guardian-recovery-r1/report.json")" = independent_recovery_kernel_and_read_only_root_verified ] || fail "unexpected PASS reason"
pass "independent-kernel read-only-root fixture passes"

digest="$(make_manifest 6.18-test)"
if run_helper "$digest" >/dev/null 2>&1; then
    fail "suspected kernel self-certification was accepted"
fi
[ "$(jq -r .reason "$TMP/esp/MahoOS/guardian-recovery-r1/report.json")" = suspected_kernel_cannot_certify_itself ] || fail "wrong self-certification refusal reason"
pass "suspected kernel cannot certify itself"

digest="$(make_manifest 7.1-test)"
if run_helper "$digest" 'rw,relatime,subvol=/@' >/dev/null 2>&1; then
    fail "writable system root was accepted"
fi
[ "$(jq -r .reason "$TMP/esp/MahoOS/guardian-recovery-r1/report.json")" = root_not_read_only ] || fail "wrong writable-root refusal reason"
pass "writable root fails closed"
digest="$(make_manifest 7.1-test)"
printf 'tampered\n' >> "$TMP/esp/MahoOS/guardian-recovery-r1/vmlinuz"
if run_helper "$digest" >/dev/null 2>&1; then
    fail "tampered recovery kernel payload was accepted"
fi
[ "$(jq -r .reason "$TMP/esp/MahoOS/guardian-recovery-r1/report.json")" = payload_kernel_digest_mismatch ] || fail "wrong payload-integrity refusal reason"
pass "tampered recovery payload fails closed"

digest="$(make_manifest 7.1-test)"
if run_helper "$digest" 'ro,relatime,subvol=/@' 1 >/dev/null 2>&1; then
    fail "R1 accepted a PASS when durable report persistence failed"
fi
[ "$(cat "$TMP/state/reason")" = report_persistence_failed ] || fail "report persistence failure was not surfaced"
pass "report persistence failure blocks certification"

echo 'ALL GUARDIAN RECOVERY R1 CONTRACTS PASS'
