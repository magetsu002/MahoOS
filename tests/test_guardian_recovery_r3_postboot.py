#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from guardian_recovery_r3 import intent_envelope
from guardian_recovery_r3_executor import execute_r3
from guardian_recovery_r3_postboot import R3PostBootEvidence, execution_receipt, verify_r3_postboot
from test_guardian_recovery_r3_executor import FakeOps, context, full_intent, kernel_intent

def check(name: str, value: bool) -> None:
    if not value:
        raise AssertionError(name)
    print("PASS", name)

def evidence(intent, **overrides):
    data = dict(
        recovery_environment_active=False, normal_root_active=True,
        system_generation_id=str(intent.target_system_generation_id),
        kernel_generation_id=str(intent.target_kernel_generation_id),
        root_generation_verified=True, boot_artifacts_verified=True,
        home_identity="home-1", emergency_backup_present=True,
        emergency_backup_read_only=True,
    )
    data.update(overrides)
    return R3PostBootEvidence(**data)

def main() -> int:
    full = full_intent(); env = intent_envelope(full); ctx = context()
    executed = execute_r3(env, ctx, FakeOps(full))
    receipt = execution_receipt(env, executed, ctx)
    result = verify_r3_postboot(env, receipt, evidence(full))
    check("R3 full postboot proof verifies exact generation pair", result.verified and result.phase == "VERIFIED")
    check("R3 postboot proof emits deterministic evidence digest", len(result.evidence_sha256) == 64)
    tampered = dict(receipt); tampered["intent_sha256"] = "0" * 64
    result = verify_r3_postboot(env, tampered, evidence(full))
    check("R3 rejects tampered durable receipt", not result.verified and "r3_receipt_intent_mismatch" in result.blockers)
    result = verify_r3_postboot(env, receipt, evidence(full, home_identity="home-changed"))
    check("R3 rejects changed home identity postboot", not result.verified and "postboot_home_identity_changed" in result.blockers)
    result = verify_r3_postboot(env, receipt, evidence(full, emergency_backup_present=False))
    check("R3 full restore requires emergency backup after reboot", not result.verified and "postboot_emergency_backup_missing" in result.blockers)
    kern = kernel_intent(); kenv = intent_envelope(kern); kctx = context()
    kexec = execute_r3(kenv, kctx, FakeOps(kern))
    kreceipt = execution_receipt(kenv, kexec, kctx)
    kres = verify_r3_postboot(kenv, kreceipt, evidence(
        kern, emergency_backup_present=False, emergency_backup_read_only=False))
    check("R3 kernel-only postboot does not require emergency backup", kres.verified)
    bad = verify_r3_postboot(kenv, kreceipt, evidence(
        kern, kernel_generation_id="kgen-" + "9" * 64,
        emergency_backup_present=False, emergency_backup_read_only=False))
    check("R3 rejects wrong kernel generation after reboot",
          not bad.verified and "postboot_kernel_generation_mismatch" in bad.blockers)
    print("ALL GUARDIAN RECOVERY R3 POSTBOOT TESTS PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
