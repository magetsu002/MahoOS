#!/usr/bin/env python3
"""Read-only historical Snapper retention inventory.

This is NOT a deletion authority. Recovery generation eligibility is not a
retirement certificate. Agent 2 must provide fresh exact retirement admission,
and Snapper/Limine/update mutation owners must execute their own transitions.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from maho_recovery_generation import RecoveryGenerationReport

LOGICAL_ROLES = (
    "verified_known_good",
    "previous_working",
    "pre_update",
    "emergency",
)
_TRUE = {"yes", "true", "1"}


def _positive(value: object) -> bool:
    return isinstance(value, str) and value.lower() in _TRUE


def classify_snapper_history(
    report: RecoveryGenerationReport, *,
    role_claims: Mapping[str, str] | None = None,
    active_transaction_ids: Iterable[str] = (),
    incident_pins: Iterable[str] = (),
    boot_pins: Iterable[str] = (),
) -> dict[str, Any]:
    """Explain every observed snapshot without authorizing retirement.

    Claims and pins are annotations, not validated Agent 2 authority. Unknown
    external heads and missing role bindings are surfaced, never ignored.
    Snapshot numeric IDs are only meaningful with filesystem/config identity.
    """
    platform = report.current_platform
    fs_uuid = platform.get("root_filesystem_uuid")
    roles = dict(role_claims or {})
    if set(roles) - set(LOGICAL_ROLES):
        raise ValueError("unknown logical recovery role")
    for name, ids in (
        ("active_transaction_ids", active_transaction_ids),
        ("incident_pins", incident_pins),
        ("boot_pins", boot_pins),
    ):
        if isinstance(ids, (str, bytes)):
            raise ValueError(f"{name} must contain generation identities, not text")
    active = set(active_transaction_ids)
    incidents = set(incident_pins)
    boot = set(boot_pins)
    for values in (active, incidents, boot):
        if not all(isinstance(x, str) and x for x in values):
            raise ValueError("pins must contain nonempty generation identities")
    observations = sorted(
        report.generations,
        key=lambda gen: (gen.snapshot.config_name, gen.snapshot.snapshot_id),
    )
    keys = [(gen.snapshot.config_name, gen.snapshot.snapshot_id) for gen in observations]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate Snapper identity makes retirement inventory ambiguous")
    known = {gen.generation_id for gen in observations if gen.generation_id}
    unknown_references = sorted((set(roles.values()) | active | incidents | boot) - known)
    blockers: list[str] = []
    if not isinstance(fs_uuid, str) or not fs_uuid:
        blockers.append("filesystem-identity-unknown")
    if platform.get("snapper_config_available") is not True:
        blockers.append("snapper-config-unavailable")
    if platform.get("limine_manifest_available") is not True:
        blockers.append("limine-boot-inventory-unavailable")
    if unknown_references:
        blockers.append("unknown-external-identity-reference")
    for role in LOGICAL_ROLES:
        if role not in roles:
            blockers.append(f"unbound-logical-role:{role}")

    rows: list[dict[str, Any]] = []
    for gen in observations:
        snap = gen.snapshot
        data = snap.userdata
        claimed = sorted(name for name, identity in roles.items() if identity == gen.generation_id)
        purposes: set[str] = set(claimed)
        reasons: set[str] = set(blockers)
        if snap.snapshot_type == "pre":
            purposes.add("pre-update")
        elif snap.snapshot_type == "post":
            purposes.add("post-update")
        if _positive(data.get("maho.restore_backup")):
            purposes.add("emergency-backup-claimed")
        if _positive(data.get("maho.known_good")):
            purposes.add("known-good-label-claimed-not-current-trust")
        if _positive(data.get("maho.recovery_overlay")):
            purposes.add("recovery-overlay")
        if _positive(data.get("maho.l3_target")):
            purposes.add("recovery-target")
        if not purposes:
            purposes.add("historical-or-manual")

        if not gen.generation_id or gen.root_filesystem_uuid != fs_uuid:
            reasons.add("unbound-generation-or-filesystem-identity")
        if snap.active is not False:
            reasons.add("active-state-or-observation-unknown")
        if snap.default is not False:
            reasons.add("default-state-or-observation-unknown")
        if _positive(data.get("important")) or snap.cleanup in {None, ""}:
            reasons.add("important-or-manual-label-requires-certified-release")
        if claimed:
            reasons.add("logical-role-must-remain-protected")
        if gen.generation_id in active:
            reasons.add("active-transaction")
        if gen.generation_id in incidents:
            reasons.add("guardian-incident")
        if gen.generation_id in boot:
            reasons.add("boot-reference")
        if gen.boot.entry_id:
            reasons.add("limine-published-entry-not-yet-retired")
        if snap.snapshot_type in {"pre", "post"}:
            reasons.add("package-pair-retirement-not-proven")
        if snap.read_only is not True:
            reasons.add("snapshot-readonly-state-unverified")
        if not gen.evidence_complete:
            reasons.add("recovery-evidence-incomplete")
        # Neither discovery nor a historical known-good label proves that
        # current Agent 2 recovery admission authorizes retirement.
        reasons.add("agent2-retirement-admission-unavailable")
        reasons.add("snapshot-subvolume-uuid-must-be-rechecked-by-snapper-owner")

        rows.append({
            "snapper_config": snap.config_name,
            "snapshot_id": snap.snapshot_id,
            "generation_id": gen.generation_id,
            "purposes": sorted(purposes),
            "logical_roles_claimed": claimed,
            "retirement_authorized": False,
            "holds": sorted(reasons),
        })

    source = report.as_dict()
    source_hash = hashlib.sha256(
        json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "kind": "maho-snapper-lifecycle-observation",
        "source_recovery_report_sha256": source_hash,
        "authority": "read-only; no retirement execution allowed",
        "logical_roles": list(LOGICAL_ROLES),
        "global_blockers": sorted(set(blockers)),
        "unknown_external_references": unknown_references,
        "snapshot_count": len(rows),
        "retirement_authorized_count": 0,
        "snapshots": rows,
    }
