#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$ROOT/tools/maho-vm-certify"
GUEST="$ROOT/tools/vm/guest-certify.sh"
HOOK="$ROOT/tools/vm/initcpio/hooks/maho_vm_overlay"
INSTALL_HOOK="$ROOT/tools/vm/initcpio/install/maho_vm_overlay"
CONFIG="$ROOT/tools/vm/mkinitcpio.conf"
TORTURE="$ROOT/tools/maho-vm-torture"
TORTURE_GUEST="$ROOT/tools/vm/guest-torture.sh"
TORTURE_LIB="$ROOT/tools/vm/torture-lib.sh"
TORTURE_REPORT="$ROOT/tools/vm/torture-report.py"
ROOT_DESTRUCTION_VERIFIER="$ROOT/tools/vm/root-destruction-verifier.c"

fail() { echo "FAIL: $*" >&2; exit 1; }
require() { grep -Fq -- "$2" "$1" || fail "$3"; }
reject() { if grep -Fq -- "$2" "$1"; then fail "$3"; fi; }

for f in "$RUNNER" "$GUEST" "$HOOK" "$INSTALL_HOOK" "$CONFIG" "$TORTURE" "$TORTURE_GUEST" "$TORTURE_LIB" "$TORTURE_REPORT" "$ROOT_DESTRUCTION_VERIFIER"; do
  [ -r "$f" ] || fail "missing VM certification source: $f"
done

bash -n "$RUNNER" "$GUEST" "$HOOK" "$INSTALL_HOOK" "$TORTURE" "$TORTURE_GUEST" "$TORTURE_LIB"
python3 -m py_compile "$TORTURE_REPORT"
gcc -std=c11 -Wall -Wextra -Werror -fsyntax-only "$ROOT_DESTRUCTION_VERIFIER"

require "$RUNNER" '-nic none' 'VM runner gained an external NIC'
require "$RUNNER" 'mount_tag=hostroot,security_model=none,readonly=on' 'host root is not read-only'
require "$RUNNER" 'mount_tag=maho_repo,security_model=none,readonly=on' 'source checkout is not read-only'
require "$RUNNER" 'maho.vm.source_revision=$REV' 'guest evidence is not bound to exact Git revision'
require "$RUNNER" 'refusing dirty checkout' 'runner can certify uncommitted source under an unrelated SHA'
require "$RUNNER" 'maho.vm.diskhome=1' 'graphical VM does not use isolated disk-backed home'
require "$RUNNER" '-device bochs-display' 'graphical VM lacks isolated virtual display'
require "$RUNNER" 'performance-4g' '4 GiB certification profile missing'
require "$RUNNER" 'performance-8g' '8 GiB certification profile missing'
require "$HOOK" 'mount -t overlay overlay' 'guest root is not disposable OverlayFS'
require "$HOOK" 'mount -t 9p' 'guest source transport missing'
require "$HOOK" ': > "$newroot/etc/fstab"' 'physical host fstab can leak into VM boot'
require "$HOOK" ': > "$newroot/etc/crypttab"' 'physical host crypttab can leak into VM boot'
require "$GUEST" '! touch /mnt/maho-src/.vm-write-probe' 'guest does not prove source write rejection'
require "$GUEST" 'rm -rf "$SRC/.git"' 'guest source preparation cannot remove both primary and worktree Git metadata'
require "$GUEST" 'ten SDDM logout/relogin cycles' 'session campaign lost repeated logout/login gate'
require "$GUEST" 'maho-memory-certify" run "$short"' 'performance profiles bypass canonical memory certifier'
require "$GUEST" 'corrupt immutable release was overwritten' 'runtime corruption fail-closed assertion missing'
require "$GUEST" 'firewall-policy-netns.sh' 'resilience profile omits firewall namespace traffic certification'
require "$GUEST" 'firewall-transaction-netns.sh' 'resilience profile omits firewall transaction certification'
require "$GUEST" 'gpu_rendered_idle_pss_authority' 'performance evidence overclaims virtual GPU memory'
require "$GUEST" 'external NIC present' 'disconnected resilience assertion missing'
require "$RUNNER" 'maho.vm.torture=1' 'destructive profiles lack explicit kernel command-line intent'
require "$RUNNER" 'maho.vm.allowed_writable_block=vda' 'destructive profiles lack an exact virtual block allowlist'
require "$TORTURE_LIB" 'torture_destructive_gate' 'destructive helpers bypass the reusable safety predicate'
require "$TORTURE_LIB" 'unexpected writable host share' 'torture safety does not reject writable host shares'
require "$TORTURE_LIB" 'unexpected writable block device exposed' 'torture safety does not reject writable physical block exposure'
require "$TORTURE_GUEST" 'RECOVERED_AUTOMATICALLY' 'automatic recovery outcome is not represented'
require "$TORTURE_GUEST" 'RECOVERED_WITH_AUTHORITY' 'authorized recovery outcome is not represented'
require "$TORTURE_GUEST" 'DETECTED_ONLY' 'detected-only outcome is not represented'
require "$TORTURE_GUEST" 'NOT_COVERED' 'unsupported V1 outcome cannot be reported truthfully'
require "$TORTURE" 'torture-session' 'top-level torture session profile missing'
require "$TORTURE" 'torture-guardian' 'top-level torture Guardian profile missing'
require "$TORTURE" 'torture-runtime' 'top-level torture runtime profile missing'
require "$TORTURE" 'torture-runtime-executor' 'runtime executor interruption profile missing'
require "$TORTURE" 'torture-runtime-executor-after' 'post-mutation executor interruption profile missing'
require "$TORTURE" 'torture-runtime-guardian-verifying' 'Guardian-during-VERIFYING profile missing'
require "$TORTURE" 'torture-reboot-awaiting' 'same-disk awaiting-authority power-cycle profile missing'
require "$TORTURE" 'torture-reboot-recovering' 'same-disk recovering power-cycle profile missing'
require "$TORTURE" 'torture-reboot-verifying' 'same-disk verifying power-cycle profile missing'
require "$RUNNER" 'reboot-stage1-ready' 'same-disk power-cycle orchestration missing'
require "$TORTURE" 'torture-postconditions' 'bad-postcondition profile missing'
sed -n '/^scenario_runtime_bad_postcondition()/,/^}/p' "$TORTURE_GUEST" | grep -Fq -- 'runtime_stage_campaign "$tag" "$directory" yes' \
  || fail 'bad runtime postcondition injector can race the always-on Guardian coordinator'
sed -n '/^scenario_recovery_loop_prevention()/,/^}/p' "$TORTURE_GUEST" | grep -Fq -- 'runtime_stage_campaign "$tag" "$directory" yes' \
  || fail 'recovery-loop injector can race the always-on Guardian coordinator'
require "$TORTURE" 'torture-network' 'isolated network-loss profile missing'
require "$TORTURE" 'torture-update' 'top-level torture update profile missing'
require "$TORTURE" 'torture-update-compound' 'update plus Guardian profile missing'
require "$TORTURE" 'torture-reboot-update-phases' 'same-disk update phase reboot profile missing'
require "$TORTURE" 'torture-prevention' 'top-level torture prevention profile missing'
require "$TORTURE" 'torture-storage' 'top-level torture storage profile missing'
require "$TORTURE" 'torture-compound' 'top-level compound profile missing'
require "$TORTURE" 'torture-root-destruction' 'full disposable-root destruction profile missing'
require "$RUNNER" 'lsm=landlock,lockdown,yama,integrity,bpf' 'root destruction profile does not activate BPF LSM'
require "$TORTURE_GUEST" '  /usr/bin/rm -rf --one-file-system --no-preserve-root / \' 'full root profile no longer executes the real rm-style root attack'
reject "$TORTURE_GUEST" '/usr/bin/timeout 30 /usr/bin/rm' 'root destruction attack is still truncated by disposable guest userspace'
require "$TORTURE_GUEST" 'work="$E/root-destruction-control"' 'root destruction control plane is not staged on the durable evidence mount'
require "$TORTURE_GUEST" '-O2 -static' 'root destruction verifier is not statically linked for post-attack execution'
require "$ROOT_DESTRUCTION_VERIFIER" 'maho_evidence_9p' 'root destruction result does not identify its out-of-root durable sink'
require "$ROOT_DESTRUCTION_VERIFIER" 'protected_bytes_unchanged' 'root destruction verifier lost protected-state byte comparison'
require "$RUNNER" 'independent host verification for full disposable-root destruction' 'host-side root destruction evidence verification missing'
reject "$RUNNER" '-net user' 'VM runner unexpectedly enables user-mode networking'
reject "$RUNNER" '-netdev' 'VM runner unexpectedly enables a network backend'
reject "$RUNNER" '/dev/nvme' 'VM runner reaches physical NVMe devices'

echo "ALL VM CERTIFICATION CONTRACTS PASS"
