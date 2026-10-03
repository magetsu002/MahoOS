#!/usr/bin/env python3
"""Guardian selection for one exact Maho Update postboot failure.

This module is deliberately a selector, not a mutation owner.  It accepts
current provider facts from Maho Update and can select only the previous
SystemGeneration already bound into that transaction.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping


_SHA40 = re.compile(r"[0-9a-f]{40}")
_SHA256_ID = re.compile(r"(?:gen|kgen)-[0-9a-f]{64}")
_TXID = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
_UUID = re.compile(r"[0-9a-fA-F-]{36}")


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _decision_id(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode()
    return "art-" + hashlib.sha256(encoded).hexdigest()


def select_exact_previous_generation(
    provider_evidence: Mapping[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    """Select the provider-bound previous generation or fail closed.

    No caller-supplied alternative target is accepted.  UNKNOWN, stale,
    historical, incomplete, or incompatible facts produce ATTENTION_REQUIRED.
    """
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    value = dict(provider_evidence)
    required = {
        "schema_version", "kind", "observed_at", "current",
        "transaction_id", "source_revision", "filesystem_uuid",
        "failed_candidate_uuid", "failed_system_generation_id",
        "previous_root_uuid", "previous_system_generation_id",
        "current_kernel_generation_id", "candidate_kernel_generation_id",
        "root_topology", "recovery_artifacts_intact", "failure_code",
        "postboot_verification_succeeded",
    }
    reasons: list[str] = []
    if set(value) != required:
        reasons.append("provider_evidence_fields_invalid")
    if value.get("schema_version") != 1 or value.get("kind") != "maho-update-postboot-failure":
        reasons.append("provider_evidence_kind_invalid")
    try:
        observed = datetime.fromisoformat(str(value.get("observed_at", "")).replace("Z", "+00:00"))
        if observed.tzinfo is None or current < observed or (current - observed).total_seconds() > 300:
            reasons.append("provider_evidence_stale")
    except ValueError:
        reasons.append("provider_evidence_time_invalid")
    if value.get("current") is not True:
        reasons.append("provider_evidence_not_current")
    if value.get("postboot_verification_succeeded") is not False:
        reasons.append("provider_failure_not_proven")
    if value.get("recovery_artifacts_intact") is not True:
        reasons.append("recovery_artifacts_not_intact")
    if value.get("root_topology") != "ARMED":
        reasons.append("recovery_topology_not_exact")
    if not isinstance(value.get("transaction_id"), str) or _TXID.fullmatch(value["transaction_id"]) is None:
        reasons.append("transaction_identity_invalid")
    if not isinstance(value.get("source_revision"), str) or _SHA40.fullmatch(value["source_revision"]) is None:
        reasons.append("source_revision_invalid")
    for key in ("failed_candidate_uuid", "previous_root_uuid", "filesystem_uuid"):
        if not isinstance(value.get(key), str) or _UUID.fullmatch(value[key]) is None:
            reasons.append(f"{key}_invalid")
    for key in (
        "failed_system_generation_id", "previous_system_generation_id",
        "current_kernel_generation_id", "candidate_kernel_generation_id",
    ):
        if not isinstance(value.get(key), str) or _SHA256_ID.fullmatch(value[key]) is None:
            reasons.append(f"{key}_invalid")
    if value.get("current_kernel_generation_id") != value.get("candidate_kernel_generation_id"):
        reasons.append("system_kernel_generation_incompatible")
    if value.get("failed_candidate_uuid") == value.get("previous_root_uuid"):
        reasons.append("failed_and_previous_root_are_identical")
    if value.get("failed_system_generation_id") == value.get("previous_system_generation_id"):
        reasons.append("failed_and_previous_generation_are_identical")
    if not isinstance(value.get("failure_code"), str) or not value.get("failure_code"):
        reasons.append("failure_identity_missing")

    decision: dict[str, Any] = {
        "schema_version": 1,
        "kind": "guardian-bad-update-recovery-decision",
        "decided_at": _stamp(current),
        "outcome": "ATTENTION_REQUIRED" if reasons else "RECOVER_EXACT_PREVIOUS",
        "reasons": sorted(set(reasons)),
        "transaction_id": value.get("transaction_id"),
        "failed_candidate_uuid": value.get("failed_candidate_uuid"),
        "failed_system_generation_id": value.get("failed_system_generation_id"),
        "selected_root_uuid": value.get("previous_root_uuid") if not reasons else None,
        "selected_system_generation_id": (
            value.get("previous_system_generation_id") if not reasons else None
        ),
        "selected_kernel_generation_id": (
            value.get("current_kernel_generation_id") if not reasons else None
        ),
        "recovery_scope": "exact-previous-system-root" if not reasons else None,
        "provider_evidence_sha256": hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    decision["decision_id"] = _decision_id(decision)
    return decision
