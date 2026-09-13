#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from guardian_recovery_r3 import R3PlanningError, intent_envelope, plan_r3_recovery
from maho_generation_v2 import RootIdentity, SystemGeneration
from maho_kernel_generation import CompatibilityEvidence, ContentAddressedArtifactStore, KernelGeneration, modules_tree_artifact
from maho_trust_identity import ArtifactID, ProvenanceID, TransactionID, TrustState


def check(name: str, value: bool) -> None:
    if not value:
        raise AssertionError(name)
    print("PASS", name)


def rejected(name: str, reason: str, fn) -> None:
    try:
        fn()
    except R3PlanningError as exc:
        check(name, reason in str(exc))
        return
    raise AssertionError(name)


def build_fixture(root: Path):
    evidence = root / "evidence"
    for rel in ("manifests/system", "manifests/kernel", "evidence/compatibility"):
        (evidence / rel).mkdir(parents=True)
    store = ContentAddressedArtifactStore(evidence / "artifacts")
    payloads = {name: data.encode() for name, data in {
        "old_kernel":"old-kernel", "old_initramfs":"old-initramfs",
        "new_kernel":"new-kernel", "new_initramfs":"new-initramfs",
        "module":"module", "microcode":"microcode",
    }.items()}
    ids = {name: ArtifactID.from_content(data) for name, data in payloads.items()}
    modules_id, modules_payload = modules_tree_artifact({"kernel/demo.ko": ids["module"]})
    prov = ProvenanceID.derive({"r3":"fixture"})
    old_tx = TransactionID.derive({"r3":"old"})
    new_tx = TransactionID.derive({"r3":"new"})
    old_kernel = KernelGeneration.create(
        parent_kernel_generation_id=None,
        kernel_image_id=ids["old_kernel"], initramfs_id=ids["old_initramfs"],
        modules_tree_id=modules_id, dkms_output_ids=(ids["module"],), microcode_ids=(ids["microcode"],),
        cmdline_contract="root=UUID=test ro", package_provider_identity="fixture/lts",
        provenance_id=prov, transaction_id=old_tx, kernel_abi="abi-old", modules_abi="abi-old",
        trust_state=TrustState.VERIFIED,
    )
    new_kernel = KernelGeneration.create(
        parent_kernel_generation_id=old_kernel.kernel_generation_id,
        kernel_image_id=ids["new_kernel"], initramfs_id=ids["new_initramfs"],
        modules_tree_id=modules_id, dkms_output_ids=(ids["module"],), microcode_ids=(ids["microcode"],),
        cmdline_contract="root=UUID=test ro", package_provider_identity="fixture/current",
        provenance_id=prov, transaction_id=new_tx, kernel_abi="abi-new", modules_abi="abi-new",
        trust_state=TrustState.REVOKED,
    )
    fs = "uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    old_system = SystemGeneration.create(
        parent_generation_id=None,
        root_identity=RootIdentity("btrfs:@snapshots/377/snapshot", fs, "1" * 64),
        kernel_generation_id=old_kernel.kernel_generation_id,
        package_set_identity="pkg-" + "1" * 64,
        transaction_id=old_tx, provenance_id=prov,
        artifact_ids=(ids["old_kernel"],), trust_state=TrustState.VERIFIED,
    )
    new_system = SystemGeneration.create(
        parent_generation_id=old_system.generation_id,
        root_identity=RootIdentity("btrfs:@", fs, "2" * 64),
        kernel_generation_id=new_kernel.kernel_generation_id,
        package_set_identity="pkg-" + "2" * 64,
        transaction_id=new_tx, provenance_id=prov,
        artifact_ids=(ids["new_kernel"],), trust_state=TrustState.VERIFIED,
    )
    for item in (old_system, new_system):
        (evidence / "manifests/system" / f"{item.generation_id}.json").write_text(item.canonical_manifest())
    for item in (old_kernel, new_kernel):
        (evidence / "manifests/kernel" / f"{item.kernel_generation_id}.json").write_text(item.canonical_manifest())
    for index, (system, kernel) in enumerate(((old_system, old_kernel), (new_system, new_kernel))):
        compat = CompatibilityEvidence(
            system.generation_id, kernel.kernel_generation_id,
            system.root_identity.root_manifest_sha256, fs,
            kernel.kernel_abi, kernel.modules_abi, "guardian-r3-test", True,
        )
        body = compat.__dict__ | {
            "system_generation_id": str(compat.system_generation_id),
            "kernel_generation_id": str(compat.kernel_generation_id),
        }
        (evidence / "evidence/compatibility" / f"pair-{index}.json").write_text(json.dumps(body))
    for payload in payloads.values():
        store.put(payload)
    store.put(modules_payload)
    return evidence, store, old_system, new_system, old_kernel, new_kernel


def report_for(system, kernel):
    return {
        "schema_version": 2,
        "outcome": "PASS",
        "reason": "independently_trusted_generation_pair_selected",
        "campaign_id": "r2-20260913T110506Z-60c7b34d",
        "selection": {
            "outcome": "READY", "selection_matches_expected": True,
            "source_only": True, "requires_reboot": True,
            "incident_id": "inc-r3-test",
            "target_system_generation_id": str(system.generation_id),
            "target_kernel_generation_id": str(kernel.kernel_generation_id),
            "expected_system_generation_id": str(system.generation_id),
            "expected_kernel_generation_id": str(kernel.kernel_generation_id),
        },
    }

def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        evidence, store, old_system, new_system, old_kernel, new_kernel = build_fixture(Path(td))
        full = plan_r3_recovery(
            report_for(old_system, old_kernel), evidence,
            current_system_generation_id=new_system.generation_id,
            current_kernel_generation_id=new_kernel.kernel_generation_id,
        )
        check("R3 selects full-generation recovery for older trusted ancestor", full.mode == "FULL_GENERATION")
        check("R3 binds exact Btrfs snapshot 377", full.target_snapshot_id == 377)
        check("R3 preserves home and never mutates live root", full.preserves_home and not full.mutates_live_root)
        check("R3 requires offline recovery and explicit reboot", full.requires_offline_recovery and full.requires_user_reboot)
        check("R3 intent has stable digest", len(full.intent_sha256) == 64 and intent_envelope(full)["automatic"] is False)
        kernel_only = plan_r3_recovery(
            report_for(old_system, old_kernel), evidence,
            current_system_generation_id=old_system.generation_id,
            current_kernel_generation_id=new_kernel.kernel_generation_id,
        )
        check("R3 can choose kernel-only recovery when root generation is already trusted", kernel_only.mode == "KERNEL_ONLY")
        rejected("uncertified R2 report is refused", "r2_not_certified_pass", lambda: plan_r3_recovery(
            report_for(old_system, old_kernel) | {"outcome":"FAIL"}, evidence,
            current_system_generation_id=new_system.generation_id,
            current_kernel_generation_id=new_kernel.kernel_generation_id))
        bad = report_for(old_system, old_kernel)
        bad["selection"]["target_kernel_generation_id"] = str(new_kernel.kernel_generation_id)
        rejected("mismatched R2 selected identity is refused", "r2_selected_identity_mismatch", lambda: plan_r3_recovery(
            bad, evidence,
            current_system_generation_id=new_system.generation_id,
            current_kernel_generation_id=new_kernel.kernel_generation_id))
        blob = store.path_for(old_kernel.kernel_image_id)
        blob.write_bytes(b"tampered")
        rejected("tampered selected kernel artifact is refused", "selected_kernel_artifacts_invalid", lambda: plan_r3_recovery(
            report_for(old_system, old_kernel), evidence,
            current_system_generation_id=new_system.generation_id,
            current_kernel_generation_id=new_kernel.kernel_generation_id))
    print("ALL GUARDIAN RECOVERY R3 PLANNER TESTS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
