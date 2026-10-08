#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export XDG_CONFIG_HOME="$TMP/config"
export MAHO_ROOT="$ROOT"

mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME"

# shellcheck source=../lib/authority.sh
source "$ROOT/lib/authority.sh"
# shellcheck source=../lib/state.sh
source "$ROOT/lib/state.sh"
# shellcheck source=../lib/events.sh
source "$ROOT/lib/events.sh"
# shellcheck source=../lib/intent.sh
source "$ROOT/lib/intent.sh"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_eq() {
    local expected="$1"
    local actual="$2"
    local label="$3"

    [ "$expected" = "$actual" ] ||
        fail "$label: expected '$expected', got '$actual'"
}

echo "=== authority ==="
assert_eq user "$(maho_owner_get test.unknown)" "unknown ownership safety default"
maho_owner_set test.resource maho >/dev/null
assert_eq maho "$(maho_owner_get test.resource)" "user ownership override"
maho_owner_set test.resource integration >/dev/null
assert_eq integration "$(maho_owner_get test.resource)" "integration ownership"
maho_owner_unset test.resource
assert_eq user "$(maho_owner_get test.resource)" "ownership unset safety default"
echo "PASS"

echo "=== intent ==="
assert_eq true "$(maho_intent_get appearance.wallpaper.dynamic_theme)" "default dynamic theme intent"
assert_eq '"dark"' "$(maho_intent_get appearance.theme.mode)" "default theme mode"
maho_intent_set appearance.wallpaper.dynamic_theme false >/dev/null
assert_eq false "$(maho_intent_get appearance.wallpaper.dynamic_theme)" "user intent override"
if maho_intent_bool appearance.wallpaper.dynamic_theme; then
    fail "false boolean intent evaluated true"
fi
maho_intent_unset appearance.wallpaper.dynamic_theme
assert_eq true "$(maho_intent_get appearance.wallpaper.dynamic_theme)" "intent unset restores default"
maho_intent_bool appearance.wallpaper.dynamic_theme || fail "true boolean intent evaluated false"
echo "PASS"

echo "=== normalized state ==="
maho_state_publish wallpaper test-provider '{"kind":"image","path":"/tmp/example.jpg"}' >/dev/null
maho_state_get wallpaper | python -c '
import json, sys
state = json.load(sys.stdin)
assert state["version"] == 1
assert state["domain"] == "wallpaper"
assert state["provider"] == "test-provider"
assert state["data"]["kind"] == "image"
assert state["data"]["path"] == "/tmp/example.jpg"
assert state["observed_at"].endswith("Z")
'
echo "PASS"

echo "=== event history ==="
FIRST="$(
    maho_event_emit \
        appearance \
        wallpaper.changed \
        observed \
        info \
        'Wallpaper changed' \
        appearance.hyprland.borders \
        test-provider \
        '{"kind":"image"}'
)"

SECOND="$(
    maho_event_emit \
        appearance \
        theme.applied \
        verified \
        low \
        'Theme adaptation verified' \
        appearance.hyprland.borders \
        hyprland \
        '{"adapter":"hyprland-borders"}'
)"

[ "$FIRST" != "$SECOND" ] || fail "event ids must be unique"

maho_event_last appearance | python -c '
import json, sys
event = json.load(sys.stdin)
assert event["version"] == 1
assert event["domain"] == "appearance"
assert event["kind"] == "theme.applied"
assert event["status"] == "verified"
assert event["details"]["adapter"] == "hyprland-borders"
'

maho_event_show "$FIRST" | python -c '
import json, sys
event = json.load(sys.stdin)
assert event["kind"] == "wallpaper.changed"
assert event["status"] == "observed"
'

if maho_event_emit appearance bad observed impossible 'bad risk' '' '' '{}' >/dev/null 2>&1; then
    fail "invalid risk accepted"
fi

assert_eq 600 "$(stat -c '%a' "$MAHO_EVENT_LOG")" "event log permissions"
assert_eq 700 "$(stat -c '%a' "$(dirname "$MAHO_EVENT_LOG")")" "event history directory permissions"

echo "PASS"

echo "=== event history tolerates partial records ==="
printf '%s' '{"version":1,"id":"partial"' >> "$MAHO_EVENT_LOG"
TAIL_OUTPUT="$(maho_event_tail 10)" || fail "event history failed on a partial JSONL record"
printf '%s\n' "$TAIL_OUTPUT" | grep -q 'theme.applied' || fail "valid history disappeared after partial record"
maho_event_last appearance | python -c '
import json, sys
event = json.load(sys.stdin)
assert event["kind"] == "theme.applied"
assert event["status"] == "verified"
'
echo "PASS"

echo "=== registry validation ==="
maho_owner_validate_file "$ROOT/config/ownership.json"
maho_intent_validate_file "$ROOT/config/intent.json"
python -m json.tool "$ROOT/config/ownership.json" >/dev/null
python -m json.tool "$ROOT/config/intent.json" >/dev/null
echo "PASS"

echo "=== Palette V2 behavior and compatibility ==="
python "$ROOT/tests/palette-v2.py"
bash "$ROOT/tests/terminal-polish-contracts.sh"

echo "=== Maho Update authority ==="
python "$ROOT/tests/test_maho_update_state.py"
python "$ROOT/tests/test_maho_update_discovery.py"
python "$ROOT/tests/test_maho_update_subset.py"
python "$ROOT/tests/test_maho_update_subset_profile.py"
python "$ROOT/tests/test_maho_update_subset_solver_integration.py"
python "$ROOT/tests/test_maho_aur_discovery.py"
python "$ROOT/tests/test_maho_aur_source.py"
python "$ROOT/tests/test_maho_aur_artifact.py"
bash "$ROOT/tests/security-aur-build.sh"
bash "$ROOT/tests/security-service-sandbox.sh"
python "$ROOT/tests/test_maho_update_effects.py"
python "$ROOT/tests/test_maho_update_staging.py"
python "$ROOT/tests/test_maho_update_normal.py"
python "$ROOT/tests/test_maho_update_normal_host.py"
python "$ROOT/tests/test_maho_update_normal_pacman_integration.py"
python "$ROOT/tests/test_maho_update_normal_authority.py"
python "$ROOT/tests/test_maho_update_external.py"
python "$ROOT/tests/test_maho_update_preparation.py"
python "$ROOT/tests/test_maho_update_maintenance.py"
python "$ROOT/tests/test_maho_update_coordinator.py"
python "$ROOT/tests/test_adaptive_session_evidence.py"
python "$ROOT/tests/test_maho_update_execution_authority.py"
python "$ROOT/tests/test_maho_update_automatic_execution.py"
python "$ROOT/tests/test_maho_update_bad_recovery.py"
python "$ROOT/tests/test_maho_update_candidate_generation.py"
python "$ROOT/tests/test_maho_update_transaction.py"
python "$ROOT/tests/test_maho_update_receipts.py"
python "$ROOT/tests/test_maho_persistence_transition.py"
python "$ROOT/tests/test_maho_update_cli.py"
bash "$ROOT/tests/maho-update-product-contracts.sh"
python "$ROOT/tests/test_guardian_update.py"
python "$ROOT/tests/test_maho_update_adversarial.py"
python "$ROOT/tests/test_maho_update_native.py"
python "$ROOT/tests/test_maho_update_admission.py"
python "$ROOT/tests/test_signed_boot_authority.py"
python "$ROOT/tests/test_maho_secure_boot_environment.py"
python "$ROOT/tests/test_release_manifest.py"
python "$ROOT/tests/test_boot_publication.py"
python "$ROOT/tests/test_kernel_security.py"
python "$ROOT/tests/test_qemu_certification_contract.py"

echo "=== Trust, generations, admission, and independent recovery ==="
python "$ROOT/tests/test_trust_identity.py"
python "$ROOT/tests/test_generation_v2.py"
python "$ROOT/tests/test_kernel_generation.py"
python "$ROOT/tests/test_maho_live_generation.py"
python "$ROOT/tests/test_guardian_offline_recovery.py"
bash "$ROOT/tests/guardian-recovery-r1.sh"
python "$ROOT/tests/guardian-recovery-r2.py"
python "$ROOT/tests/test_guardian_recovery_r3.py"
python "$ROOT/tests/test_guardian_recovery_r3_executor.py"
python "$ROOT/tests/test_guardian_recovery_r3_postboot.py"
python "$ROOT/tests/test_guardian_r3_native_campaign.py"
python "$ROOT/tests/test_guardian_recovery_initrd_closure.py"
python "$ROOT/tests/test_guardian_recovery_r3_native.py"
python "$ROOT/tests/test_guardian_recovery_tui.py"
python "$ROOT/tests/test_guardian_admission.py"
python "$ROOT/tests/test_guardian_native_admission.py"
python "$ROOT/tests/test_guardian_revocation.py"
python "$ROOT/tests/test_guardian_revocation_recovery.py"
python "$ROOT/tests/test_guardian_trust_status.py"

echo "=== Guardian live evidence and world state ==="
python "$ROOT/tests/test_guardian_evidence.py"
python "$ROOT/tests/test_guardian_intent.py"
python "$ROOT/tests/test_guardian_world_state.py"
python "$ROOT/tests/test_guardian_provider_state.py"
python "$ROOT/tests/test_guardian_journal_stream.py"
python "$ROOT/tests/test_guardian_live_state.py"
python "$ROOT/tests/test_guardian_live_collector.py"
python "$ROOT/tests/test_guardian_live_authority.py"
python "$ROOT/tests/test_guardian_live_intent_boundary.py"
python "$ROOT/tests/test_guardian_live_status.py"
python "$ROOT/tests/test_guardian_live_status_render.py"
python "$ROOT/tests/test_guardian_signed_boot_provider.py"
python "$ROOT/tests/test_guardian_live_signed_boot.py"
python "$ROOT/tests/test_maho_runtime_release.py"
python "$ROOT/tests/test_maho_runtime_deployment.py"

echo "=== Firewall authority and receipt ==="
python "$ROOT/tests/test_maho_firewall_receipt.py"
bash "$ROOT/tests/firewall-certification-contracts.sh"
bash "$ROOT/tests/firewall-observer-contracts.sh"
bash "$ROOT/tests/firewall-transaction-netns.sh"

echo "=== Core prevention boundary ==="
python "$ROOT/tests/test_maho_prevention_policy.py"
python "$ROOT/tests/test_maho_mutation_authority.py"
python "$ROOT/tests/test_maho_prevention_kernel.py"
python "$ROOT/tests/test_maho_process_control.py"
python "$ROOT/tests/test_maho_intent_guard.py"
python "$ROOT/tests/test_maho_break_glass.py"
python "$ROOT/tests/test_guardian_prevention.py"
bash "$ROOT/tests/prevention-boundary-contracts.sh"

echo "=== Guardian causal, containment, recovery, and reliability completion ==="
python "$ROOT/tests/test_guardian_causality.py"
python "$ROOT/tests/test_guardian_causal_projection.py"
python "$ROOT/tests/test_guardian_causal_status.py"
python "$ROOT/tests/test_guardian_containment.py"
python "$ROOT/tests/test_guardian_live_response.py"
python "$ROOT/tests/test_guardian_live_response_real.py"
python "$ROOT/tests/test_guardian_live_recovery.py"
python "$ROOT/tests/test_guardian_runtime_integrity_incident.py"
python "$ROOT/tests/test_guardian_runtime_recovery_campaign.py"
python "$ROOT/tests/test_guardian_security_recovery.py"
python "$ROOT/tests/test_guardian_reliability.py"
python "$ROOT/tests/test_guardian_completion_status.py"
bash "$ROOT/tests/platform-hardening-contracts.sh"
bash "$ROOT/tests/platform-transaction-contracts.sh"

echo "=== Final VM contract matrix wiring ==="
bash "$ROOT/tests/vm-final-contracts.sh"

echo "=== Maho Files desktop UX closure ==="
bash "$ROOT/tests/maho-files-qml-contracts.sh"
bash "$ROOT/tests/maho-files-dnd-search-contracts.sh"
bash "$ROOT/tests/maho-files-ux-closure-contracts.sh"
bash "$ROOT/tests/maho-files-icon-contracts.sh"
bash "$ROOT/tests/maho-files-model-ops.sh"

echo "=== Vesktop session reliability ==="
bash "$ROOT/tests/vesktop-session-reliability.sh"
bash "$ROOT/tests/vesktop-install-contracts.sh"

echo "=== Disposable full-system VM certification harness ==="
bash "$ROOT/tests/vm-certification-contracts.sh"

echo "=== Adaptive policy A1-A16 ==="
python "$ROOT/tests/test_behavior_preferences.py"
python "$ROOT/tests/test_maho_system_status.py"
python "$ROOT/tests/test_maho_login_diagnostic.py"
python "$ROOT/tests/test_boot_reliability_campaign.py"
python "$ROOT/tests/test_maho_system_tui.py"
python "$ROOT/tests/test_maho_system_cli.py"
for test in "$ROOT"/tests/test_adaptive_*.py; do
  python "$test"
done

PYTHONPATH="$ROOT/lib" python "$ROOT/tests/test_generation_gc.py"
PYTHONPATH="$ROOT/lib" python "$ROOT/tests/test_maho_update_preparation.py"
PYTHONPATH="$ROOT/lib" python "$ROOT/tests/test_maho_update_normal.py"

echo "ALL CORE CONTRACTS PASS"
