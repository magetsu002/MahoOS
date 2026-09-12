#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_revocation import (  # noqa: E402
    ArtifactEvidence, ArtifactUse, RevocationRecord, analyze_revocations,
    recovery_impact,
)
from maho_generation_v2 import GenerationGraph, RootIdentity, SystemGeneration  # noqa: E402
from maho_kernel_generation import KernelGeneration, KernelGenerationGraph, modules_tree_artifact  # noqa: E402
from maho_trust_identity import ArtifactID, ProvenanceID, TransactionID, TrustState  # noqa: E402


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


PROV = ProvenanceID.derive({"revocation": "fixture"})
GOOD = ArtifactID.from_content(b"good-package")
BAD = ArtifactID.from_content(b"revoked-package")
FIXED = ArtifactID.from_content(b"fixed-package")
KERNEL_BAD = ArtifactID.from_content(b"revoked-kernel")
INITRAMFS = ArtifactID.from_content(b"initramfs")
MODULE = ArtifactID.from_content(b"module")
MODULES, _ = modules_tree_artifact({"kernel/demo.ko": MODULE})
TX0, TX1, TX2, TX3 = (TransactionID.derive({"tx": i}) for i in range(4))
FS = "uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def kernel(image, tx, parent=None, trust=TrustState.VERIFIED):
    return KernelGeneration.create(
        parent_kernel_generation_id=parent.kernel_generation_id if parent else None,
        kernel_image_id=image, initramfs_id=INITRAMFS, modules_tree_id=MODULES,
        dkms_output_ids=(MODULE,), microcode_ids=(), cmdline_contract="root=UUID=test ro",
        package_provider_identity="core/linux", provenance_id=PROV, transaction_id=tx,
        kernel_abi="abi", modules_abi="abi", trust_state=trust,
    )


k0 = kernel(GOOD, TX0)
k1 = kernel(KERNEL_BAD, TX1, k0)
k2 = kernel(FIXED, TX2, k1)
kernel_graph = KernelGenerationGraph([k0, k1, k2])


def system(parent, number, kernel_generation, tx, artifacts, trust=TrustState.VERIFIED):
    return SystemGeneration.create(
        parent_generation_id=parent.generation_id if parent else None,
        root_identity=RootIdentity(f"snapper:root:{number}", FS, f"{number:x}".rjust(64, "0")),
        kernel_generation_id=kernel_generation.kernel_generation_id,
        package_set_identity="pkg-" + f"{number:x}".rjust(64, "0"),
        transaction_id=tx, provenance_id=PROV, artifact_ids=artifacts, trust_state=trust,
    )


g0 = system(None, 10, k0, TX0, (GOOD,))
g1 = system(g0, 11, k0, TX1, (BAD,))
g2 = system(g1, 12, k0, TX2, (GOOD,))
g3 = system(g2, 13, k0, TX3, (GOOD,))
unrelated = system(g0, 20, k0, TX2, (GOOD,))
graph = GenerationGraph([g0, g1, g2, g3, unrelated])

artifact_rows = (
    ArtifactEvidence(GOOD, TX0, "arch-key:good", "2026-09-01T00:00:00Z"),
    ArtifactEvidence(BAD, TX1, "arch-key:compromised", "2026-09-05T00:00:00Z"),
    ArtifactEvidence(FIXED, TX2, "arch-key:good", "2026-09-10T00:00:00Z"),
    ArtifactEvidence(KERNEL_BAD, TX1, "arch-key:compromised", "2026-09-05T01:00:00Z"),
)
use = ArtifactUse(BAD, g1.generation_id, TX1, True, True, True, True, True, False)
direct = RevocationRecord.create(
    target_kind="ARTIFACT", target_id=str(BAD), source="maho-advisory",
    reason="fixture compromise", issued_at="2026-09-12T00:00:00Z",
)
analysis = analyze_revocations(
    revocations=(direct,), artifacts=artifact_rows, uses=(use,), system_graph=graph,
    kernel_graph=kernel_graph, history_complete=True,
)
check("package revoked after three generations maps to its transaction", analysis.affected_transaction_ids == (TX1,))
check("first affected generation is exact", analysis.first_affected_generation_id == g1.generation_id)
check("revocation contaminates descendant generations", all(g.generation_id in analysis.affected_generation_ids for g in (g1, g2, g3)))
check("unrelated branch remains trusted", analysis.generation_trust[unrelated.generation_id] is TrustState.VERIFIED)
check("contaminated generation is retained for forensics", g1.generation_id in graph.generations and analysis.generation_trust[g1.generation_id] is TrustState.CONTAMINATED)
check("revoked generation cannot be normal recovery target", not analysis.normal_recovery_eligible(g2.generation_id))
check("newest independently trusted ancestor is selected", analysis.newest_independently_trusted_ancestor(graph, g3.generation_id) == g0)
impact = recovery_impact(analysis, selected_generation_id=g0.generation_id, restoration_verified=True)
check("verified rollback can restore system integrity", impact.system_integrity == "restored")
check("filesystem recovery does not erase possible credential exposure", impact.credential_exposure == "possible")

authority = RevocationRecord.create(
    target_kind="SIGNING_AUTHORITY", target_id="arch-key:compromised",
    source="arch-keyring", reason="bounded key compromise",
    issued_at="2026-09-12T01:00:00Z", effective_from="2026-09-04T00:00:00Z",
    effective_until="2026-09-06T00:00:00Z",
)
authority_analysis = analyze_revocations(
    revocations=(authority,), artifacts=artifact_rows, uses=(use,), system_graph=graph,
    kernel_graph=kernel_graph, history_complete=True,
)
check("bounded signing-authority revocation selects artifacts in interval", BAD in authority_analysis.revoked_artifact_ids and GOOD not in authority_analysis.revoked_artifact_ids)

kernel_use = ArtifactUse(KERNEL_BAD, g1.generation_id, TX1, True, True, True, True, False, True)
kernel_analysis = analyze_revocations(
    revocations=(RevocationRecord.create(target_kind="ARTIFACT", target_id=str(KERNEL_BAD), source="upstream", reason="kernel compromise", issued_at="2026-09-12T02:00:00Z"),),
    artifacts=artifact_rows, uses=(kernel_use,), system_graph=graph,
    kernel_graph=kernel_graph, history_complete=True,
)
check("kernel artifact revocation propagates through kernel lineage", all(k.kernel_generation_id in kernel_analysis.affected_kernel_generation_ids for k in (k1, k2)))
check("kernel impact is distinct exposure evidence", kernel_analysis.exposure.artifact_affected_kernel)

revalidated = system(g2, 14, k0, TX3, (FIXED,), trust=TrustState.REVALIDATED)
after_revalidation = system(revalidated, 15, k0, TX3, (FIXED,))
revalidation_graph = GenerationGraph([g0, g1, g2, revalidated, after_revalidation])
revalidation_analysis = analyze_revocations(
    revocations=(direct,), artifacts=artifact_rows, uses=(use,),
    system_graph=revalidation_graph, kernel_graph=kernel_graph, history_complete=True,
)
check("later independently revalidated generation creates an explicit clean boundary", revalidation_analysis.generation_trust[revalidated.generation_id] is TrustState.REVALIDATED)
check("descendants of revalidated clean state remain trusted", revalidation_analysis.generation_trust[after_revalidation.generation_id] is TrustState.VERIFIED)

all_bad_root = system(None, 30, k0, TX1, (BAD,))
all_bad_child = system(all_bad_root, 31, k0, TX2, (GOOD,))
all_bad_graph = GenerationGraph([all_bad_root, all_bad_child])
all_bad_use = ArtifactUse(BAD, all_bad_root.generation_id, TX1, True, True, False, False, False, False)
all_bad = analyze_revocations(
    revocations=(direct,), artifacts=artifact_rows, uses=(all_bad_use,),
    system_graph=all_bad_graph, kernel_graph=kernel_graph, history_complete=True,
)
check("all ancestors contaminated yields no trusted recovery state", all_bad.newest_independently_trusted_ancestor(all_bad_graph, all_bad_child.generation_id) is None and all_bad.refusal_reason() == "all_local_history_contaminated")
truncated = analyze_revocations(
    revocations=(direct,), artifacts=artifact_rows, uses=(all_bad_use,),
    system_graph=all_bad_graph, kernel_graph=kernel_graph, history_complete=False,
)
check("missing older local history is reported honestly", truncated.refusal_reason() == "last_trusted_state_predates_local_history")

incomplete_use = ArtifactUse(BAD, g1.generation_id, TX1, True, True, False, False, False, False, evidence_complete=False)
incomplete = analyze_revocations(
    revocations=(direct,), artifacts=artifact_rows, uses=(incomplete_use,),
    system_graph=graph, kernel_graph=kernel_graph, history_complete=True,
)
check("incomplete execution evidence leaves credential exposure unresolved", incomplete.exposure.credential_exposure == "unresolved")

print("ALL GUARDIAN REVOCATION CONTRACT TESTS PASS")
