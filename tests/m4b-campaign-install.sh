#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
INSTALLER="$ROOT/bin/maho-update-campaign-install"
WRAPPER="$ROOT/bin/maho-update-campaign"
CAMPAIGN="$ROOT/lib/maho_update_campaign.py"
PLATFORM="$ROOT/config/platform.json"
pass(){ printf 'PASS %s\n' "$1"; }
fail(){ printf 'FAIL %s\n' "$1" >&2; exit 1; }
bash -n "$INSTALLER" "$WRAPPER"; python -m py_compile "$CAMPAIGN" "$ROOT/lib/maho_update_native.py"; pass "M4B campaign entrypoints parse"
set +e; out="$(bash "$WRAPPER" --help 2>&1)"; rc=$?; set -e
(( rc != 0 )) || fail "source-tree wrapper unexpectedly executed"
grep -Fq 'refusing non-root-owned campaign payload' <<<"$out" || fail "source-tree refusal missing"
pass "source-tree wrapper cannot become privileged authority"
REV="$(git -C "$ROOT" rev-parse HEAD)"
set +e; out="$(bash "$INSTALLER" install --repo "$ROOT" --revision "$REV" 2>&1)"; rc=$?; set -e
if (( EUID != 0 )); then (( rc != 0 )) || fail "non-root installer succeeded"; grep -Fq 'root privileges are required' <<<"$out" || fail "root boundary missing"; fi
pass "installer has explicit root boundary"
grep -Fq 'rev-parse --show-toplevel' "$INSTALLER" || fail "linked worktree validation missing"
grep -Fq 'git_cmd show "$rev:$file"' "$INSTALLER" || fail "exact committed blob install missing"
grep -Fq 'git_cmd cat-file -e "$EXPECTED_REV:$file"' "$INSTALLER" || fail "exact committed blob preflight missing"
for unit in maho-update-coordinator.service maho-update-coordinator.timer maho-update-activate-on-reboot.service; do
  grep -Fq "$unit" "$INSTALLER" || fail "$unit installation missing"
done
grep -Fq 'installed $name does not match campaign revision' "$INSTALLER" || fail "systemd integration source binding missing"
grep -Fq 'systemctl enable maho-update-coordinator.timer maho-update-activate-on-reboot.service' "$INSTALLER" || fail "automatic coordinator enablement missing"
grep -Fq 'systemctl start maho-update-coordinator.timer' "$INSTALLER" || fail "automatic coordinator timer activation missing"
grep -Fq 'systemctl is-enabled --quiet maho-update-coordinator.timer' "$INSTALLER" || fail "automatic coordinator enablement proof missing"
grep -Fq 'systemctl is-active --quiet maho-update-coordinator.timer' "$INSTALLER" || fail "automatic coordinator active-state proof missing"
grep -Fq 'systemctl start maho-update-activate-on-reboot.service' "$INSTALLER" || fail "activation sentinel is not armed at campaign install"
grep -Fq 'systemctl is-active --quiet maho-update-activate-on-reboot.service' "$INSTALLER" || fail "activation sentinel active-state proof missing"
python - "$ROOT" "$INSTALLER" <<'PY_IMPORT_CLOSURE'
import ast,re,sys
from pathlib import Path
root=Path(sys.argv[1]); installer=Path(sys.argv[2]).read_text()
block=installer.split('FILES=(',1)[1].split(')\n',1)[0]
files={line.strip() for line in block.splitlines() if line.strip() and not line.lstrip().startswith('#')}
local={p.stem:p for p in (root/'lib').glob('*.py')}
queue=[root/f for f in files if f.endswith('.py')]; seen=set(); missing=set()
while queue:
    path=queue.pop()
    if path in seen: continue
    seen.add(path); tree=ast.parse(path.read_text())
    for node in ast.walk(tree):
        names=[]
        if isinstance(node,ast.Import): names=[a.name.split('.')[0] for a in node.names]
        elif isinstance(node,ast.ImportFrom) and node.module: names=[node.module.split('.')[0]]
        for name in names:
            dep=local.get(name)
            if dep is None: continue
            rel=str(dep.relative_to(root))
            if rel not in files: missing.add((str(path.relative_to(root)),rel))
assert not missing, 'campaign local import closure incomplete: '+repr(sorted(missing))
PY_IMPORT_CLOSURE
pass "installer payload closes every local Python import"
pass "installer trusts exact Git objects"
grep -Fq 'unset PYTHONPATH PYTHONHOME' "$WRAPPER" || fail "Python injection variables retained"
grep -Fq 'MAHO_UPDATE_CAMPAIGN_ROOT' "$WRAPPER" || fail "installed root is not explicit"
pass "wrapper executes installed immutable authority"
if "$ROOT/bin/maho-update-cache-install" plan --filesystem-uuid 11111111-1111-1111-1111-111111111111 >/dev/null 2>&1; then
  fail "source-tree cache installer became privileged authority"
fi
grep -Fq 'unset PYTHONPATH PYTHONHOME' "$ROOT/bin/maho-update-cache-install" || fail "cache installer retains Python injection"
pass "cache installer requires immutable root-owned campaign payload"
grep -Fq 'staging_root("m4b")' "$CAMPAIGN" || fail "campaign staging does not require the exact isolated cache"
grep -Fq 'seed_campaign(' "$CAMPAIGN" || fail "M3B target seed missing"
grep -Fq 'prepare_l3_campaign(' "$CAMPAIGN" || fail "M3B emergency preparation missing"
grep -Fq 'publish_transaction(candidate_state_root' "$CAMPAIGN" || fail "candidate authority is not durably copied"
grep -Fq 'M4B certification requires a real Primary kernel update generation' "$CAMPAIGN" || fail "real kernel-update proof gate missing"
grep -Fq 'certify_normal_update' "$CAMPAIGN" || fail "normal production certification entrypoint missing from root campaign"
grep -Fq 'certify_native_execution' "$CAMPAIGN" || fail "physical M4B certification entrypoint missing from root campaign"
grep -Fq -- '--preflight-only' "$CAMPAIGN" || fail "normal production preflight CLI missing from root campaign"
grep -Fq 'preflight_only' "$ROOT/lib/maho_update_normal_campaign.py" || fail "normal production preflight implementation missing"
grep -Fq 'config/platform/maho-pacman.conf' "$INSTALLER" || fail "canonical Pacman authority missing from root campaign payload"
grep -Fq 'lib/maho_update_normal_campaign.py' "$INSTALLER" || fail "normal campaign module missing from root campaign payload"
pass "campaign binds native update to M3B and normal certification to root-owned authority"
grep -Fq 'probe_native_readiness' "$CAMPAIGN" || fail "isolated M4B readiness probe missing"
grep -Fq 'm4b_primary_generation_unavailable' "$CAMPAIGN" || fail "M4B readiness primary generation gate missing"
pass "M4B readiness can prove exact repository payloads before recovery state exists"
python - "$PLATFORM" "$CAMPAIGN" <<'PY'
import json,sys
from pathlib import Path
p=json.load(open(sys.argv[1]))
assert p['boot']['kernel_update_snapshot_restore_certified'] is True
assert p['update']['native_execution_certified'] is True
assert p['update']['normal_execution_certified'] is False
assert p['update']['automatic_reboot'] is False
assert p['update']['pacman_config'] == '/etc/maho/pacman.conf'
assert p['update']['required_repositories'] == ['core','extra','multilib','cachyos']
s=Path(sys.argv[2]).read_text()
probe=s.index('def probe_native_readiness')
start=s.index('def prepare_native_campaign')
probe_block=s[probe:start]
assert 'IsolatedPacmanDiscovery(' in probe_block
assert 'stage_transaction(' in probe_block
assert 'seed_campaign(' not in probe_block
assert 'prepare_l3_campaign(' not in probe_block
assert 'publish_transaction(' not in probe_block
assert 'NativeBtrfsOps(' not in probe_block
assert '_write_json_atomic(' not in probe_block
assert 'shutil.rmtree(work, ignore_errors=True)' in probe_block
assert '"mutation_started": False' in probe_block
assert '"transaction_published": False' in probe_block
assert '"recovery_state_created": False' in probe_block
assert '"activation_authority_issued": False' in probe_block
assert 'sub.add_parser("probe-m4b")' in s
assert s.index('stage_transaction(', start) < s.index('seed_campaign(', start)
execute=s.index('def execute_native_campaign')
approve=s.index('def approve_native_admission')
activate=s.index('def arm_native_activation')
verify=s.index('def verify_native_activation')
execute_block=s[execute:approve]
private_boot_seed=execute_block.index('btrfs.seed_private_boot(plan.boot_artifacts)')
runtime_mount=execute_block.index('btrfs.mount_normal_candidate_runtime()')
package_execution=execute_block.index('execute_update(')
runtime_unmount=execute_block.index('btrfs.unmount_normal_candidate_runtime()')
assert private_boot_seed < runtime_mount < package_execution < runtime_unmount
assert s.index('evaluate_production_candidate(', execute) < approve
approve_block=s[approve:activate]
activate_block=s[activate:verify]
assert 'evaluate_production_candidate(' not in approve_block
assert 'inspect_candidate(' not in approve_block
assert 'verify_frozen_activation_authority(' in activate_block
assert 'inspect_candidate(' not in activate_block
assert 'home_identity() != journal["home_identity"]' in activate_block
assert '_runtime_identity_matches(' in activate_block
assert 'read_l3_journal(' in activate_block and '["phase"] != "prepared"' in activate_block
assert s.index('verify_frozen_activation_authority(', activate) < s.index('btrfs.arm_activation(', activate)
assert s.index('cleanup_admission_base(', verify) > verify
assert 'admission-review' in s and 'admission-rejected' in s
assert 'package_repo_set_mismatch' in s
assert '"phase": "blocked"' in s
assert 'with lock_context:' in s and '_campaign_mutex()' in s
PY
pass "production M4B certification is explicit and package authority remains pinned"
if grep -En '(^|[[:space:];|&])(reboot|shutdown|poweroff|efibootmgr)([[:space:];|&]|$)' "$INSTALLER" "$WRAPPER" "$CAMPAIGN" >/dev/null; then fail "M4B campaign contains reboot or firmware mutation command"; fi
pass "campaign cannot reboot or mutate firmware"
echo 'ALL M4B CAMPAIGN INSTALL CONTRACTS PASS'
