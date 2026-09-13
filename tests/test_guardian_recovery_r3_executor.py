#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from guardian_recovery_r3 import R3RecoveryIntent, intent_envelope
from guardian_recovery_r3_executor import R3ExecutionContext, execute_r3
from maho_trust_identity import GenerationID, KernelGenerationID

def check(name: str, value: bool) -> None:
    if not value:
        raise AssertionError(name)
    print("PASS", name)

def gid(ch: str) -> GenerationID:
    return GenerationID("gen-" + ch * 64)

def kid(ch: str) -> KernelGenerationID:
    return KernelGenerationID("kgen-" + ch * 64)

FULL_OPS = (
    "preserve-incident-evidence", "verify-selected-generation-again",
    "create-read-only-emergency-backup", "restore-exact-selected-btrfs-generation",
    "stage-exact-selected-kernel-artifacts", "verify-restored-root-and-boot-artifacts",
    "request-reboot", "verify-postboot-generation-and-home-identity",
)
KERNEL_OPS = (
    "preserve-incident-evidence", "verify-selected-generation-again",
    "stage-exact-selected-kernel-artifacts", "verify-boot-artifacts-and-current-root-identity",
    "request-reboot", "verify-postboot-kernel-and-home-identity",
)

def full_intent() -> R3RecoveryIntent:
    return R3RecoveryIntent(
        mode="FULL_GENERATION", incident_id="inc-r3-exec",
        r2_campaign_id="r2-20260913T110506Z-60c7b34d",
        current_system_generation_id=gid("2"), current_kernel_generation_id=kid("2"),
        target_system_generation_id=gid("1"), target_kernel_generation_id=kid("1"),
        target_snapshot_identity="btrfs:@snapshots/377/snapshot", target_snapshot_id=377,
        operations=FULL_OPS,
    )

def kernel_intent() -> R3RecoveryIntent:
    return R3RecoveryIntent(
        mode="KERNEL_ONLY", incident_id="inc-r3-kernel",
        r2_campaign_id="r2-20260913T110506Z-60c7b34d",
        current_system_generation_id=gid("1"), current_kernel_generation_id=kid("2"),
        target_system_generation_id=gid("1"), target_kernel_generation_id=kid("1"),
        target_snapshot_identity="btrfs:@snapshots/377/snapshot", target_snapshot_id=377,
        operations=KERNEL_OPS,
    )
class FakeOps:
    production_safe = True
    def __init__(self, intent: R3RecoveryIntent, fail: str | None = None, home: str = "home-1"):
        self.intent, self.fail, self.home = intent, fail, home
        self.calls: list[str] = []
    def _result(self, name: str, **extra):
        self.calls.append(name)
        if self.fail == name:
            return {"ok": False}
        return {"ok": True, **extra}
    def preserve_incident_evidence(self, intent):
        return self._result("preserve", incident_id=intent.incident_id)
    def verify_selected_generation(self, intent):
        return self._result("verify", system_generation_id=str(intent.target_system_generation_id),
                            kernel_generation_id=str(intent.target_kernel_generation_id))
    def create_emergency_backup(self, intent):
        return self._result("backup", snapshot_id=999, read_only=True)
    def restore_full_generation(self, intent):
        return self._result("restore", system_generation_id=str(intent.target_system_generation_id))
    def stage_selected_kernel(self, intent):
        return self._result("stage", kernel_generation_id=str(intent.target_kernel_generation_id), artifacts_verified=True)
    def verify_staged_state(self, intent):
        return self._result("verify-staged", system_generation_id=str(intent.target_system_generation_id),
                            kernel_generation_id=str(intent.target_kernel_generation_id), boot_artifacts_verified=True)
    def home_identity_after(self):
        self.calls.append("home")
        return self.home

def context(**overrides):
    data = dict(recovery_environment_verified=True, running_from_independent_kernel=True,
                production_root_read_only=True, explicit_authorization=True,
                home_identity_before="home-1")
    data.update(overrides)
    return R3ExecutionContext(**data)

def main() -> int:
    full = full_intent(); ops = FakeOps(full)
    result = execute_r3(intent_envelope(full), context(), ops)
    check("R3 full execution reaches reboot gate", result.phase == "AWAITING_REBOOT" and result.mutation_started)
    check("R3 full execution preserves strict order",
          ops.calls == ["preserve", "verify", "backup", "restore", "stage", "verify-staged", "home"])
    check("R3 full execution records immutable emergency backup",
          result.evidence["emergency_backup"]["read_only"] is True)
    kern = kernel_intent(); kop = FakeOps(kern)
    result = execute_r3(intent_envelope(kern), context(), kop)
    check("R3 kernel-only reaches reboot gate", result.phase == "AWAITING_REBOOT")
    check("R3 kernel-only does not touch root generation",
          "backup" not in kop.calls and "restore" not in kop.calls and kop.calls == ["preserve", "verify", "stage", "verify-staged", "home"])
    denied = FakeOps(full)
    result = execute_r3(intent_envelope(full), context(explicit_authorization=False), denied)
    check("R3 refuses without explicit authorization",
          result.phase == "BLOCKED" and not result.mutation_started and denied.calls == [])
    badops = FakeOps(full)
    tampered = R3RecoveryIntent(**(full.__dict__ | {"operations": tuple(reversed(full.operations))}))
    result = execute_r3(intent_envelope(tampered), context(), badops)
    check("R3 refuses reordered authority operations", result.phase == "BLOCKED" and badops.calls == [])
    pre = FakeOps(full, fail="verify")
    result = execute_r3(intent_envelope(full), context(), pre)
    check("R3 pre-mutation verification failure stays non-mutating",
          result.phase == "BLOCKED" and not result.mutation_started and "backup" not in pre.calls)
    post = FakeOps(full, fail="stage")
    result = execute_r3(intent_envelope(full), context(), post)
    check("R3 post-restore stage failure is recorded as mutation failure",
          result.phase == "MUTATION_FAILED" and result.mutation_started and "restore" in post.calls)
    drift = FakeOps(full, home="home-changed")
    result = execute_r3(intent_envelope(full), context(), drift)
    check("R3 refuses reboot gate when home identity drifts",
          result.phase == "VERIFY_FAILED" and "home_identity_changed" in result.blockers)
    unsafe = FakeOps(full); unsafe.production_safe = False
    result = execute_r3(intent_envelope(full), context(), unsafe)
    check("R3 refuses non-production executor", result.phase == "BLOCKED" and unsafe.calls == [])
    print("ALL GUARDIAN RECOVERY R3 EXECUTOR TESTS PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
