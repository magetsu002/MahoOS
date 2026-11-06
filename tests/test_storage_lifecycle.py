#!/usr/bin/env python3
"""Adversarial read-only historical Snapper retention classification tests."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from maho_recovery_generation import (
    BootEvidence, RecoveryGeneration, RecoveryGenerationReport, SnapshotEvidence,
)
from maho_storage_lifecycle import classify_snapper_history


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


snapshot = SnapshotEvidence(
    config_name="root", snapshot_id=41, creation_time="2026-11-06T12:00:00+04:00",
    subvolume="/", snapshot_type="single", cleanup=None, description="old migration head",
    userdata={"important": "yes", "maho.known_good": "yes"},
    active=False, default=False, read_only=True,
)
generation = RecoveryGeneration(
    generation_id="g3-test41", snapshot=snapshot,
    root_filesystem_uuid="btrfs-identity", root_source="/dev/mapper/system",
    root_fsroot="/@", home_scope="excluded",
    boot=BootEvidence(source="limine-history", entry_id="limine-snapshot-41"),
    lts_kernel_present=True, known_good=True, evidence_complete=True,
    boot_state_coherent=True, eligible=True, rejection_reasons=(),
    verification_status="eligible",
)
platform = {
    "root_filesystem_uuid": "btrfs-identity",
    "snapper_config_available": True,
    "limine_manifest_available": True,
}
report = RecoveryGenerationReport(
    schema_version=1, current_platform=platform, generations=(generation,),
    selected_generation_id="g3-test41", certified_system_restore_plannable=True,
    planning_facts={},
)
roles = {name: "g3-test41" for name in (
    "verified_known_good", "previous_working", "pre_update", "emergency",
)}
result = classify_snapper_history(
    report, role_claims=roles,
    active_transaction_ids=("g3-test41",),
    incident_pins=("g3-test41",), boot_pins=("g3-test41",),
)
row = result["snapshots"][0]
check("every logical role is represented without equating it to a physical count", len(row["logical_roles_claimed"]) == 4)
check("current reported restoration eligibility does not authorize deletion", not row["retirement_authorized"])
check("important labels remain held until certified transition", "important-or-manual-label-requires-certified-release" in row["holds"])
check("published Limine entry retains snapshot", "limine-published-entry-not-yet-retired" in row["holds"])
check("active transaction and Guardian incident independently pin state", {"active-transaction", "guardian-incident"} <= set(row["holds"]))
check("missing Agent 2 interface never becomes authority", "agent2-retirement-admission-unavailable" in row["holds"])
check("source report has stable content identity", len(result["source_recovery_report_sha256"]) == 64)

stale = replace(report, current_platform={
    "root_filesystem_uuid": None,
    "snapper_config_available": False,
    "limine_manifest_available": False,
})
rejected = classify_snapper_history(stale)
check("unknown filesystem and boot inventory fail closed", {"filesystem-identity-unknown", "limine-boot-inventory-unavailable"} <= set(rejected["global_blockers"]))
check("unbound roles cannot silently become empty retention slots", any(x.startswith("unbound-logical-role:") for x in rejected["global_blockers"]))
check("historical verification does not become current retirement trust", rejected["retirement_authorized_count"] == 0)

unknown = classify_snapper_history(report, role_claims={"emergency": "g3-stale"})
check("stale external reference appears as an explicit blocker", unknown["unknown_external_references"] == ["g3-stale"] and "unknown-external-identity-reference" in unknown["global_blockers"])

pair = replace(snapshot, snapshot_id=42, snapshot_type="pre", cleanup="number", userdata={})
paired = replace(generation, generation_id="g3-test42", snapshot=pair, boot=BootEvidence())
result_pair = classify_snapper_history(replace(report, generations=(paired,)))
check("pre-update relationship requires independent pair retirement", "package-pair-retirement-not-proven" in result_pair["snapshots"][0]["holds"])

try:
    classify_snapper_history(replace(report, generations=(generation, generation)))
except ValueError:
    print("PASS duplicate Snapper identity refused")
else:
    raise AssertionError("duplicate Snapper identity accepted")

print("ALL STORAGE HISTORY OBSERVATION CONTRACTS PASS")
