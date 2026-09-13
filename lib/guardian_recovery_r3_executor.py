#!/usr/bin/env python3
"""Bounded source contract for executing one R3 recovery intent."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping, Protocol

from guardian_recovery_r3 import R3RecoveryIntent
from maho_trust_identity import GenerationID, KernelGenerationID, canonical_json


@dataclass(frozen=True)
class R3ExecutionContext:
    recovery_environment_verified: bool
    running_from_independent_kernel: bool
    production_root_read_only: bool
    explicit_authorization: bool
    home_identity_before: str


@dataclass(frozen=True)
class R3ExecutionResult:
    phase: str
    mode: str
    mutation_started: bool
    blockers: tuple[str, ...]
    evidence: Mapping[str, Any]


class R3RecoveryOps(Protocol):
    production_safe: bool
    def preserve_incident_evidence(self, intent: R3RecoveryIntent) -> Mapping[str, Any]: ...
    def verify_selected_generation(self, intent: R3RecoveryIntent) -> Mapping[str, Any]: ...
    def create_emergency_backup(self, intent: R3RecoveryIntent) -> Mapping[str, Any]: ...
    def restore_full_generation(self, intent: R3RecoveryIntent) -> Mapping[str, Any]: ...
    def stage_selected_kernel(self, intent: R3RecoveryIntent) -> Mapping[str, Any]: ...
    def verify_staged_state(self, intent: R3RecoveryIntent) -> Mapping[str, Any]: ...
    def home_identity_after(self) -> str: ...


def _parse_intent(payload: Mapping[str, Any]) -> R3RecoveryIntent:
    required = {
        "mode", "incident_id", "r2_campaign_id", "current_system_generation_id",
        "current_kernel_generation_id", "target_system_generation_id", "target_kernel_generation_id",
        "target_snapshot_identity", "target_snapshot_id", "operations", "requires_offline_recovery",
        "mutates_live_root", "preserves_home", "requires_user_reboot",
    }
    if set(payload) != required:
        raise ValueError("r3_intent_fields_invalid")
    return R3RecoveryIntent(
        mode=str(payload["mode"]),
        incident_id=str(payload["incident_id"]),
        r2_campaign_id=str(payload["r2_campaign_id"]),
        current_system_generation_id=GenerationID(str(payload["current_system_generation_id"])),
        current_kernel_generation_id=KernelGenerationID(str(payload["current_kernel_generation_id"])),
        target_system_generation_id=GenerationID(str(payload["target_system_generation_id"])),
        target_kernel_generation_id=KernelGenerationID(str(payload["target_kernel_generation_id"])),
        target_snapshot_identity=str(payload["target_snapshot_identity"]),
        target_snapshot_id=payload["target_snapshot_id"],
        operations=tuple(payload["operations"]),
        requires_offline_recovery=payload["requires_offline_recovery"],
        mutates_live_root=payload["mutates_live_root"],
        preserves_home=payload["preserves_home"],
        requires_user_reboot=payload["requires_user_reboot"],
    )

def parse_envelope(envelope: Mapping[str, Any]) -> R3RecoveryIntent:
    if envelope.get("schema_version") != 1:
        raise ValueError("r3_envelope_schema_invalid")
    if envelope.get("authority_scope") != "guardian-r3-bounded-generation-recovery":
        raise ValueError("r3_authority_scope_invalid")
    if envelope.get("automatic") is not False:
        raise ValueError("r3_automatic_authority_forbidden")
    if envelope.get("requires_explicit_user_authorization") is not True:
        raise ValueError("r3_authorization_contract_invalid")
    raw = envelope.get("intent")
    if not isinstance(raw, Mapping):
        raise ValueError("r3_intent_missing")
    observed = hashlib.sha256(canonical_json(dict(raw)).encode("utf-8")).hexdigest()
    if envelope.get("intent_sha256") != observed:
        raise ValueError("r3_intent_digest_mismatch")
    intent = _parse_intent(raw)
    if intent.intent_sha256 != observed:
        raise ValueError("r3_intent_roundtrip_mismatch")
    if intent.mode not in {"KERNEL_ONLY", "FULL_GENERATION"}:
        raise ValueError("r3_mode_invalid")
    if not intent.requires_offline_recovery or intent.mutates_live_root or not intent.preserves_home:
        raise ValueError("r3_safety_contract_invalid")
    if not intent.requires_user_reboot:
        raise ValueError("r3_reboot_contract_invalid")
    return intent


def _blocked(intent: R3RecoveryIntent, *blockers: str) -> R3ExecutionResult:
    return R3ExecutionResult("BLOCKED", intent.mode, False, tuple(blockers), {})

def authorize_context(intent: R3RecoveryIntent, context: R3ExecutionContext) -> tuple[str, ...]:
    blockers: list[str] = []
    if not context.recovery_environment_verified:
        blockers.append("recovery_environment_unverified")
    if not context.running_from_independent_kernel:
        blockers.append("recovery_kernel_not_independent")
    if not context.production_root_read_only:
        blockers.append("production_root_not_read_only")
    if not context.explicit_authorization:
        blockers.append("explicit_authorization_missing")
    if not context.home_identity_before:
        blockers.append("home_identity_missing")
    if intent.mode == "FULL_GENERATION" and intent.target_snapshot_id is None:
        blockers.append("full_generation_snapshot_missing")
    if intent.mode == "KERNEL_ONLY" and intent.target_system_generation_id != intent.current_system_generation_id:
        blockers.append("kernel_only_root_identity_changed")
    return tuple(dict.fromkeys(blockers))


def _op_ok(result: Mapping[str, Any]) -> bool:
    return result.get("ok") is True


_EXPECTED_FULL = (
    "preserve-incident-evidence",
    "verify-selected-generation-again",
    "create-read-only-emergency-backup",
    "restore-exact-selected-btrfs-generation",
    "stage-exact-selected-kernel-artifacts",
    "verify-restored-root-and-boot-artifacts",
    "request-reboot",
    "verify-postboot-generation-and-home-identity",
)
_EXPECTED_KERNEL = (
    "preserve-incident-evidence",
    "verify-selected-generation-again",
    "stage-exact-selected-kernel-artifacts",
    "verify-boot-artifacts-and-current-root-identity",
    "request-reboot",
    "verify-postboot-kernel-and-home-identity",
)

def _expected_ops(intent: R3RecoveryIntent) -> tuple[str, ...]:
    return _EXPECTED_FULL if intent.mode == "FULL_GENERATION" else _EXPECTED_KERNEL

def _result(
    intent: R3RecoveryIntent, phase: str, mutation_started: bool,
    evidence: Mapping[str, Any], *blockers: str,
) -> R3ExecutionResult:
    return R3ExecutionResult(
        phase, intent.mode, mutation_started,
        tuple(dict.fromkeys(blockers)), dict(evidence),
    )

def _require_identity(result: Mapping[str, Any], intent: R3RecoveryIntent) -> bool:
    return (
        result.get("system_generation_id") == str(intent.target_system_generation_id)
        and result.get("kernel_generation_id") == str(intent.target_kernel_generation_id)
    )

def _call_step(name: str, call, *, mutation_started: bool):
    try:
        result = call()
    except Exception as exc:
        phase = "MUTATION_FAILED" if mutation_started else "BLOCKED"
        return None, phase, f"{name}_exception:{type(exc).__name__}"
    if not isinstance(result, Mapping) or not _op_ok(result):
        phase = "MUTATION_FAILED" if mutation_started else "BLOCKED"
        return result if isinstance(result, Mapping) else {}, phase, f"{name}_failed"
    return result, None, None

def execute_r3(
    envelope: Mapping[str, Any], context: R3ExecutionContext, ops: R3RecoveryOps,
) -> R3ExecutionResult:
    intent = parse_envelope(envelope)
    blockers = list(authorize_context(intent, context))
    if intent.operations != _expected_ops(intent):
        blockers.append("r3_operation_sequence_invalid")
    if blockers:
        return _blocked(intent, *blockers)
    if getattr(ops, "production_safe", False) is not True:
        return _blocked(intent, "executor_not_production_safe")
    evidence: dict[str, Any] = {"intent_sha256": intent.intent_sha256}
    preserved, phase, blocker = _call_step(
        "preserve_incident_evidence", lambda: ops.preserve_incident_evidence(intent), mutation_started=False)
    if blocker:
        return _result(intent, phase, False, evidence, blocker)
    evidence["incident"] = dict(preserved)
    verified, phase, blocker = _call_step(
        "verify_selected_generation", lambda: ops.verify_selected_generation(intent), mutation_started=False)
    if blocker:
        return _result(intent, phase, False, evidence, blocker)
    if not _require_identity(verified, intent):
        return _result(intent, "BLOCKED", False, evidence, "selected_generation_identity_mismatch")
    evidence["selected_generation"] = dict(verified)
    mutation_started = False
    if intent.mode == "FULL_GENERATION":
        backup, phase, blocker = _call_step(
            "create_emergency_backup", lambda: ops.create_emergency_backup(intent), mutation_started=False)
        if blocker:
            return _result(intent, phase, False, evidence, blocker)
        if backup.get("read_only") is not True or not backup.get("snapshot_id"):
            return _result(intent, "BLOCKED", False, evidence, "emergency_backup_not_immutable")
        evidence["emergency_backup"] = dict(backup)
        mutation_started = True
        restored, phase, blocker = _call_step(
            "restore_full_generation", lambda: ops.restore_full_generation(intent), mutation_started=True)
        if blocker:
            return _result(intent, phase, True, evidence, blocker)
        if restored.get("system_generation_id") != str(intent.target_system_generation_id):
            return _result(intent, "MUTATION_FAILED", True, evidence, "restored_system_identity_mismatch")
        evidence["root_restore"] = dict(restored)
    mutation_started = True
    staged, phase, blocker = _call_step(
        "stage_selected_kernel", lambda: ops.stage_selected_kernel(intent), mutation_started=True)
    if blocker:
        return _result(intent, phase, True, evidence, blocker)
    if staged.get("kernel_generation_id") != str(intent.target_kernel_generation_id):
        return _result(intent, "MUTATION_FAILED", True, evidence, "staged_kernel_identity_mismatch")
    if staged.get("artifacts_verified") is not True:
        return _result(intent, "MUTATION_FAILED", True, evidence, "staged_kernel_artifacts_unverified")
    evidence["kernel_stage"] = dict(staged)
    verified_stage, phase, blocker = _call_step(
        "verify_staged_state", lambda: ops.verify_staged_state(intent), mutation_started=True)
    if blocker:
        return _result(intent, phase, True, evidence, blocker)
    if not _require_identity(verified_stage, intent):
        return _result(intent, "VERIFY_FAILED", True, evidence, "staged_generation_identity_mismatch")
    if verified_stage.get("boot_artifacts_verified") is not True:
        return _result(intent, "VERIFY_FAILED", True, evidence, "boot_artifacts_unverified")
    evidence["staged_verification"] = dict(verified_stage)
    try:
        home_after = ops.home_identity_after()
    except Exception as exc:
        return _result(intent, "VERIFY_FAILED", True, evidence, f"home_identity_exception:{type(exc).__name__}")
    if home_after != context.home_identity_before:
        return _result(intent, "VERIFY_FAILED", True, evidence, "home_identity_changed")
    evidence["home_identity"] = home_after
    return _result(intent, "AWAITING_REBOOT", True, evidence)
