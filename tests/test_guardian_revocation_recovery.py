#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_recovery_r3 import recovery_operations  # noqa: E402
from guardian_revocation import (  # noqa: E402
    ArtifactEvidence, ArtifactUse, RevocationRecord, analyze_revocations,
)
from guardian_revocation_recovery import plan_revocation_recovery  # noqa: E402
from maho_generation_v2 import GenerationGraph, RootIdentity, SystemGeneration  # noqa: E402
from maho_kernel_generation import (  # noqa: E402
    CompatibilityEvidence, KernelGeneration, KernelGenerationGraph,
    modules_tree_artifact,
)
from maho_trust_identity import (  # noqa: E402
    ArtifactID, ProvenanceID, TransactionID, TrustState,
)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


PROV = ProvenanceID.derive({"revocation-recovery": "fixture"})
TX0 = TransactionID.derive({"rr": 0})
TX1 = TransactionID.derive({"rr": 1})
GOOD_PACKAGE = ArtifactID.from_content(b"good-package")
BAD_PACKAGE = ArtifactID.from_content(b"bad-package")
BAD_KERNEL_IMAGE = ArtifactID.from_content(b"bad-kernel")
FS = "uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def kernel(name: str, tx: TransactionID, parent=None, *, image_payload=None):
    payloads = {
        "kernel": image_payload or f"kernel-{name}".encode(),
        "initramfs": f"initramfs-{name}".encode(),
        "module": f"module-{name}".encode(),
        "microcode": f"microcode-{name}".encode(),
    }
    module_id = ArtifactID.from_content(payloads["module"])
    modules_id, modules_payload = modules_tree_artifact({f"kernel/{name}.ko": module_id})
    image_id = ArtifactID.from_content(payloads["kernel"])
    initramfs_id = ArtifactID.from_content(payloads["initramfs"])
    microcode_id = ArtifactID.from_content(payloads["microcode"])
    value = KernelGeneration.create(
        parent_kernel_generation_id=parent.kernel_generation_id if parent else None,
        kernel_image_id=image_id,
        initramfs_id=initramfs_id,
        modules_tree_id=modules_id,
        dkms_output_ids=(module_id,),
        microcode_ids=(microcode_id,),
        cmdline_contract="root=UUID=test ro",
        package_provider_identity=f"fixture/{name}",
        provenance_id=PROV,
        transaction_id=tx,
        kernel_abi=f"abi-{name}",
        modules_abi=f"abi-{name}",
        trust_state=TrustState.VERIFIED,
    )
    observed = {
        image_id: payloads["kernel"],
        initramfs_id: payloads["initramfs"],
        modules_id: modules_payload,
        module_id: payloads["module"],
        microcode_id: payloads["microcode"],
    }
    return value, observed


K0, K0_ARTIFACTS = kernel("lts", TX0)
K1, K1_ARTIFACTS = kernel("primary", TX1, K0, image_payload=b"bad-kernel")
KERNEL_GRAPH = KernelGenerationGraph((K0, K1))


def system(parent, number: int, kernel_value, tx, artifacts, *, current=False):
    snapshot = "btrfs:@" if current else f"btrfs:@snapshots/{number}/snapshot"
    return SystemGeneration.create(
        parent_generation_id=parent.generation_id if parent else None,
        root_identity=RootIdentity(snapshot, FS, f"{number:x}".rjust(64, "0")),
        kernel_generation_id=kernel_value.kernel_generation_id,
        package_set_identity="pkg-" + f"{number:x}".rjust(64, "0"),
        transaction_id=tx,
        provenance_id=PROV,
        artifact_ids=artifacts,
        trust_state=TrustState.VERIFIED,
    )


G0 = system(None, 10, K0, TX0, (GOOD_PACKAGE,))
G1 = system(G0, 11, K1, TX1, (GOOD_PACKAGE,), current=True)
GRAPH = GenerationGraph((G0, G1))


def compatibility(system_value, kernel_value, *, verified=True):
    return CompatibilityEvidence(
        system_generation_id=system_value.generation_id,
        kernel_generation_id=kernel_value.kernel_generation_id,
        root_manifest_sha256=system_value.root_identity.root_manifest_sha256,
        filesystem_identity=system_value.root_identity.filesystem_identity,
        kernel_abi=kernel_value.kernel_abi,
        modules_abi=kernel_value.modules_abi,
        verifier_identity="guardian-independent-compatibility-v1",
        independently_verified=verified,
    )


ARTIFACT_ROWS = (
    ArtifactEvidence(GOOD_PACKAGE, TX0, "arch-key:good", "2026-09-01T00:00:00Z"),
    ArtifactEvidence(BAD_PACKAGE, TX1, "arch-key:bad", "2026-09-10T00:00:00Z"),
    ArtifactEvidence(BAD_KERNEL_IMAGE, TX1, "arch-key:bad", "2026-09-10T00:01:00Z"),
)


def analysis_for(artifact, use):
    record = RevocationRecord.create(
        target_kind="ARTIFACT",
        target_id=str(artifact),
        source="fixture-advisory",
        reason="compromised artifact",
        issued_at="2026-09-14T00:00:00Z",
    )
    return analyze_revocations(
        revocations=(record,),
        artifacts=ARTIFACT_ROWS,
        uses=(use,),
        system_graph=GRAPH,
        kernel_graph=KERNEL_GRAPH,
        history_complete=True,
    )


def plan(analysis, *, compatible=True, artifacts=True):
    compatibility_rows = {
        (G1.generation_id, K0.kernel_generation_id): compatibility(G1, K0, verified=compatible),
        (G0.generation_id, K0.kernel_generation_id): compatibility(G0, K0, verified=compatible),
    }
    observed = {K0.kernel_generation_id: K0_ARTIFACTS} if artifacts else {}
    return plan_revocation_recovery(
        analysis,
        incident_id="inc-revocation-recovery-test",
        current_system_generation_id=G1.generation_id,
        current_kernel_generation_id=K1.kernel_generation_id,
        system_graph=GRAPH,
        kernel_graph=KERNEL_GRAPH,
        compatibility=compatibility_rows,
        observed_kernel_artifacts=observed,
    )


def main() -> None:
    kernel_use = ArtifactUse(
        BAD_KERNEL_IMAGE, G1.generation_id, TX1,
        True, True, True, True, False, True,
    )
    kernel_analysis = analysis_for(BAD_KERNEL_IMAGE, kernel_use)
    check("kernel-only contamination is retained distinctly", G1.generation_id in kernel_analysis.kernel_induced_generation_ids and G1.generation_id not in kernel_analysis.directly_affected_generation_ids)
    kernel_plan = plan(kernel_analysis)
    check("revoked kernel selects KERNEL_ONLY", kernel_plan.ready and kernel_plan.mode == "KERNEL_ONLY")
    check("kernel-only keeps exact current root", kernel_plan.target_system_generation_id == G1.generation_id)
    check("kernel-only selects newest independently trusted kernel ancestor", kernel_plan.target_kernel_generation_id == K0.kernel_generation_id)
    check("kernel-only plan reuses certified R3 operation vocabulary", kernel_plan.operations == recovery_operations("KERNEL_ONLY"))
    check("kernel exposure remains visible after recovery selection", kernel_plan.exposure.artifact_affected_kernel and "credential_exposure_possible" in kernel_plan.reasons)

    h0 = G0
    h1 = system(h0, 12, K0, TX1, (BAD_PACKAGE,))
    h2 = system(h1, 13, K1, TX1, (GOOD_PACKAGE,), current=True)
    combined_graph = GenerationGraph((h0, h1, h2))
    package_record = RevocationRecord.create(
        target_kind="ARTIFACT", target_id=str(BAD_PACKAGE), source="fixture-advisory",
        reason="package compromise", issued_at="2026-09-14T00:10:00Z",
    )
    kernel_record = RevocationRecord.create(
        target_kind="ARTIFACT", target_id=str(BAD_KERNEL_IMAGE), source="fixture-advisory",
        reason="kernel compromise", issued_at="2026-09-14T00:11:00Z",
    )
    combined = analyze_revocations(
        revocations=(package_record, kernel_record), artifacts=ARTIFACT_ROWS,
        uses=(
            ArtifactUse(BAD_PACKAGE, h1.generation_id, TX1, True, True, True, True, True, False),
            ArtifactUse(BAD_KERNEL_IMAGE, h2.generation_id, TX1, True, True, True, True, False, True),
        ),
        system_graph=combined_graph, kernel_graph=KERNEL_GRAPH, history_complete=True,
    )
    combined_plan = plan_revocation_recovery(
        combined,
        incident_id="inc-combined-contamination",
        current_system_generation_id=h2.generation_id,
        current_kernel_generation_id=K1.kernel_generation_id,
        system_graph=combined_graph,
        kernel_graph=KERNEL_GRAPH,
        compatibility={
            (h2.generation_id, K0.kernel_generation_id): compatibility(h2, K0),
            (h0.generation_id, K0.kernel_generation_id): compatibility(h0, K0),
        },
        observed_kernel_artifacts={K0.kernel_generation_id: K0_ARTIFACTS},
    )
    check("root contamination descendants cannot be misclassified kernel-only", h2.generation_id in combined.directly_affected_generation_ids and combined_plan.mode == "FULL_GENERATION")

    package_use = ArtifactUse(
        BAD_PACKAGE, G1.generation_id, TX1,
        True, True, True, True, True, False,
    )
    package_analysis = analysis_for(BAD_PACKAGE, package_use)
    package_plan = plan(package_analysis)
    check("revoked userspace artifact selects FULL_GENERATION", package_plan.ready and package_plan.mode == "FULL_GENERATION")
    check("full recovery selects newest clean bounded snapshot", package_plan.target_system_generation_id == G0.generation_id)
    check("full recovery binds compatible trusted kernel", package_plan.target_kernel_generation_id == K0.kernel_generation_id)
    check("full plan reuses certified R3 operation vocabulary", package_plan.operations == recovery_operations("FULL_GENERATION"))
    check("affected transaction is carried into recovery evidence", str(TX1) in package_plan.affected_transaction_ids)
    check("selection evidence identity is deterministic", plan(package_analysis).evidence_digest == package_plan.evidence_digest)

    incomplete_use = ArtifactUse(
        BAD_PACKAGE, G1.generation_id, TX1,
        True, True, False, False, False, False, evidence_complete=False,
    )
    incomplete_analysis = analysis_for(BAD_PACKAGE, incomplete_use)
    incomplete_plan = plan(incomplete_analysis)
    check("recovery never erases unresolved credential exposure", incomplete_plan.ready and incomplete_plan.exposure.credential_exposure == "unresolved" and "credential_exposure_unresolved" in incomplete_plan.reasons)

    no_compatibility = plan(package_analysis, compatible=False)
    check("unverified compatibility requires EXTERNAL_RECOVERY", not no_compatibility.ready and no_compatibility.mode == "EXTERNAL_RECOVERY")
    no_artifacts = plan(package_analysis, artifacts=False)
    check("missing exact kernel artifacts requires EXTERNAL_RECOVERY", no_artifacts.mode == "EXTERNAL_RECOVERY")

    kernel_without_cross_pair = plan_revocation_recovery(
        kernel_analysis,
        incident_id="inc-no-cross-pair",
        current_system_generation_id=G1.generation_id,
        current_kernel_generation_id=K1.kernel_generation_id,
        system_graph=GRAPH,
        kernel_graph=KERNEL_GRAPH,
        compatibility={(G0.generation_id, K0.kernel_generation_id): compatibility(G0, K0)},
        observed_kernel_artifacts={K0.kernel_generation_id: K0_ARTIFACTS},
    )
    check("kernel-only ambiguity falls back to independently trusted full generation", kernel_without_cross_pair.mode == "FULL_GENERATION" and kernel_without_cross_pair.ready)

    wrong_snapshot = system(None, 20, K0, TX0, (GOOD_PACKAGE,), current=True)
    wrong_current = system(wrong_snapshot, 21, K1, TX1, (BAD_PACKAGE,), current=True)
    wrong_graph = GenerationGraph((wrong_snapshot, wrong_current))
    wrong_use = ArtifactUse(BAD_PACKAGE, wrong_current.generation_id, TX1, True, True, False, False, False, False)
    record = RevocationRecord.create(
        target_kind="ARTIFACT", target_id=str(BAD_PACKAGE), source="fixture-advisory",
        reason="compromised", issued_at="2026-09-14T01:00:00Z",
    )
    wrong_analysis = analyze_revocations(
        revocations=(record,), artifacts=ARTIFACT_ROWS, uses=(wrong_use,),
        system_graph=wrong_graph, kernel_graph=KERNEL_GRAPH, history_complete=True,
    )
    wrong_plan = plan_revocation_recovery(
        wrong_analysis,
        incident_id="inc-unbounded-snapshot",
        current_system_generation_id=wrong_current.generation_id,
        current_kernel_generation_id=K1.kernel_generation_id,
        system_graph=wrong_graph,
        kernel_graph=KERNEL_GRAPH,
        compatibility={(wrong_snapshot.generation_id, K0.kernel_generation_id): compatibility(wrong_snapshot, K0)},
        observed_kernel_artifacts={K0.kernel_generation_id: K0_ARTIFACTS},
    )
    check("unbounded root identity cannot become full recovery target", wrong_plan.mode == "EXTERNAL_RECOVERY")

    serialized = package_plan.as_dict()
    check("plan is source-only and authorization-gated", serialized["source_only"] is True and serialized["requires_explicit_authorization"] is True)
    check("plan contains no arbitrary repair command field", "command" not in serialized and all(not item.startswith("/") for item in serialized["operations"]))
    check("revocation evidence has content identity", str(package_plan.evidence_digest).startswith("art-") and len(str(package_plan.evidence_digest)) == 68)

    try:
        plan_revocation_recovery(
            package_analysis,
            incident_id="inc-inconsistent-pair",
            current_system_generation_id=G1.generation_id,
            current_kernel_generation_id=K0.kernel_generation_id,
            system_graph=GRAPH,
            kernel_graph=KERNEL_GRAPH,
            compatibility={},
            observed_kernel_artifacts={},
        )
    except ValueError as exc:
        check("inconsistent current generation pair is refused", str(exc) == "current generation pair is inconsistent")
    else:
        raise AssertionError("inconsistent current generation pair accepted")

    print("ALL GUARDIAN REVOCATION RECOVERY TESTS PASS")


if __name__ == "__main__":
    main()
