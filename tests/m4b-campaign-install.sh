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
pass "installer trusts exact Git objects"
grep -Fq 'unset PYTHONPATH PYTHONHOME' "$WRAPPER" || fail "Python injection variables retained"
grep -Fq 'MAHO_UPDATE_CAMPAIGN_ROOT' "$WRAPPER" || fail "installed root is not explicit"
pass "wrapper executes installed immutable authority"
grep -Fq 'Path("/var/cache/maho/update-m4b")' "$CAMPAIGN" || fail "campaign staging is not root-controlled"
grep -Fq 'seed_campaign(' "$CAMPAIGN" || fail "M3B target seed missing"
grep -Fq 'prepare_l3_campaign(' "$CAMPAIGN" || fail "M3B emergency preparation missing"
grep -Fq 'publish_transaction(candidate_state_root' "$CAMPAIGN" || fail "candidate authority is not durably copied"
grep -Fq 'M4B certification requires a real Primary kernel update generation' "$CAMPAIGN" || fail "real kernel-update proof gate missing"
grep -Fq 'certify_normal_update' "$CAMPAIGN" || fail "normal production certification entrypoint missing from root campaign"
grep -Fq 'config/platform/maho-pacman.conf' "$INSTALLER" || fail "canonical Pacman authority missing from root campaign payload"
grep -Fq 'lib/maho_update_normal_campaign.py' "$INSTALLER" || fail "normal campaign module missing from root campaign payload"
pass "campaign binds native update to M3B and normal certification to root-owned authority"
python - "$PLATFORM" "$CAMPAIGN" <<'PY'
import json,sys
from pathlib import Path
p=json.load(open(sys.argv[1]))
assert p['boot']['kernel_update_snapshot_restore_certified'] is True
assert p['update']['native_execution_certified'] is False
assert p['update']['normal_execution_certified'] is False
assert p['update']['automatic_reboot'] is False
assert p['update']['pacman_config'] == '/etc/maho/pacman.conf'
assert p['update']['required_repositories'] == ['core','extra','multilib','cachyos']
s=Path(sys.argv[2]).read_text()
start=s.index('def prepare_native_campaign')
assert s.index('stage_transaction(', start) < s.index('seed_campaign(', start)
execute=s.index('def execute_native_campaign')
approve=s.index('def approve_native_admission')
activate=s.index('def arm_native_activation')
verify=s.index('def verify_native_activation')
assert s.index('evaluate_production_candidate(', execute) < approve
assert s.index('verify_activation_authority(', activate) < s.index('btrfs.arm_activation(', activate)
assert s.index('cleanup_admission_base(', verify) > verify
assert 'admission-review' in s and 'admission-rejected' in s
assert 'package_repo_set_mismatch' in s
assert '"phase": "blocked"' in s
PY
pass "production M4B certification remains false and package authority is pinned before hardware proof"
if grep -En '(^|[[:space:];|&])(reboot|shutdown|poweroff|efibootmgr)([[:space:];|&]|$)' "$INSTALLER" "$WRAPPER" "$CAMPAIGN" >/dev/null; then fail "M4B campaign contains reboot or firmware mutation command"; fi
pass "campaign cannot reboot or mutate firmware"
echo 'ALL M4B CAMPAIGN INSTALL CONTRACTS PASS'
