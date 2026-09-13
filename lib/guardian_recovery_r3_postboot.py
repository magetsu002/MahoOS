#!/usr/bin/env python3
"""Durable handoff and post-boot proof contract for Guardian Recovery R3."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from typing import Any, Mapping
from guardian_recovery_r3 import R3RecoveryIntent
from guardian_recovery_r3_executor import R3ExecutionContext, R3ExecutionResult, parse_envelope
from maho_trust_identity import canonical_json

@dataclass(frozen=True)
class R3PostBootEvidence:
    recovery_environment_active: bool
    normal_root_active: bool
    system_generation_id: str
    kernel_generation_id: str
    root_generation_verified: bool
    boot_artifacts_verified: bool
    home_identity: str
    emergency_backup_present: bool
    emergency_backup_read_only: bool

@dataclass(frozen=True)
class R3PostBootResult:
    verified: bool
    phase: str
    blockers: tuple[str, ...]
    evidence_sha256: str

def execution_receipt(
    envelope: Mapping[str, Any], result: R3ExecutionResult, context: R3ExecutionContext,
) -> dict[str, Any]:
    intent = parse_envelope(envelope)
    if result.phase != "AWAITING_REBOOT" or not result.mutation_started or result.blockers:
        raise ValueError("r3_execution_not_ready_for_postboot")
    if result.mode != intent.mode:
        raise ValueError("r3_execution_mode_mismatch")
    evidence_json = canonical_json(dict(result.evidence))
    return {
        "schema_version": 1,
        "phase": "AWAITING_REBOOT",
        "intent_sha256": intent.intent_sha256,
        "mode": intent.mode,
        "target_system_generation_id": str(intent.target_system_generation_id),
        "target_kernel_generation_id": str(intent.target_kernel_generation_id),
        "home_identity_before": context.home_identity_before,
        "execution_evidence_sha256": hashlib.sha256(evidence_json.encode()).hexdigest(),
        "emergency_backup_required": intent.mode == "FULL_GENERATION",
    }

def verify_r3_postboot(
    envelope: Mapping[str, Any], receipt: Mapping[str, Any], evidence: R3PostBootEvidence,
) -> R3PostBootResult:
    intent = parse_envelope(envelope)
    blockers: list[str] = []
    if receipt.get("schema_version") != 1 or receipt.get("phase") != "AWAITING_REBOOT":
        blockers.append("r3_receipt_invalid")
    if receipt.get("intent_sha256") != intent.intent_sha256:
        blockers.append("r3_receipt_intent_mismatch")
    if receipt.get("mode") != intent.mode:
        blockers.append("r3_receipt_mode_mismatch")
    if receipt.get("target_system_generation_id") != str(intent.target_system_generation_id):
        blockers.append("postboot_system_generation_mismatch")
    if receipt.get("target_kernel_generation_id") != str(intent.target_kernel_generation_id):
        blockers.append("postboot_kernel_generation_mismatch")
    if evidence.recovery_environment_active:
        blockers.append("recovery_environment_still_active")
    if not evidence.normal_root_active:
        blockers.append("normal_root_not_active")
    if evidence.system_generation_id != str(intent.target_system_generation_id):
        blockers.append("postboot_system_generation_mismatch")
    if evidence.kernel_generation_id != str(intent.target_kernel_generation_id):
        blockers.append("postboot_kernel_generation_mismatch")
    if not evidence.root_generation_verified:
        blockers.append("postboot_root_generation_unverified")
    if not evidence.boot_artifacts_verified:
        blockers.append("postboot_boot_artifacts_unverified")
    if evidence.home_identity != receipt.get("home_identity_before"):
        blockers.append("postboot_home_identity_changed")
    if receipt.get("emergency_backup_required") is True:
        if not evidence.emergency_backup_present:
            blockers.append("postboot_emergency_backup_missing")
        if not evidence.emergency_backup_read_only:
            blockers.append("postboot_emergency_backup_not_read_only")
    payload = {
        "system_generation_id": evidence.system_generation_id,
        "kernel_generation_id": evidence.kernel_generation_id,
        "home_identity": evidence.home_identity,
        "root_generation_verified": evidence.root_generation_verified,
        "boot_artifacts_verified": evidence.boot_artifacts_verified,
    }
    digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    return R3PostBootResult(not blockers, "VERIFIED" if not blockers else "VERIFY_FAILED", tuple(dict.fromkeys(blockers)), digest)
