#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_generation_v2 import GenerationGraph, RootIdentity, SystemGeneration  # noqa: E402
from maho_kernel_generation import (  # noqa: E402
    CompatibilityEvidence, ContentAddressedArtifactStore, KernelGeneration,
    KernelGenerationGraph, can_boot, modules_tree_artifact, newest_verified_pair,
    system_generations_referencing, verify_artifacts,
)
from maho_trust_identity import ArtifactID, ProvenanceID, TransactionID, TrustState  # noqa: E402


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def rejects(name, operation):
    try:
        operation()
    except (KeyError, TypeError, ValueError):
        print("PASS", name)
        return
    raise AssertionError(name)


PROV = ProvenanceID.derive({"builder": "kernel-test"})
TX1 = TransactionID.derive({"kernel-tx": 1})
TX2 = TransactionID.derive({"kernel-tx": 2})
kernel_bytes = b"linux-image-6.18"
initramfs_bytes = b"initramfs-for-linux-image-6.18"
module_bytes = b"demo-module"
microcode_bytes = b"microcode"
KERNEL_ART = ArtifactID.from_content(kernel_bytes)
INITRAMFS_ART = ArtifactID.from_content(initramfs_bytes)
MODULE_ART = ArtifactID.from_content(module_bytes)
MICROCODE_ART = ArtifactID.from_content(microcode_bytes)
MODULES_TREE, modules_manifest = modules_tree_artifact({"kernel/drivers/demo.ko": MODULE_ART})


def kernel(parent=None, *, tx=TX1, trust=TrustState.VERIFIED, image=KERNEL_ART):
    return KernelGeneration.create(
        parent_kernel_generation_id=parent.kernel_generation_id if parent else None,
        kernel_image_id=image, initramfs_id=INITRAMFS_ART, modules_tree_id=MODULES_TREE,
        dkms_output_ids=(MODULE_ART,), microcode_ids=(MICROCODE_ART,),
        cmdline_contract="root=UUID=test ro quiet", package_provider_identity="core/linux",
        provenance_id=PROV, transaction_id=tx, kernel_abi="6.18-maho", modules_abi="6.18-maho",
        trust_state=trust,
    )


k51 = kernel()
k52 = kernel(k51, tx=TX2, image=ArtifactID.from_content(b"linux-image-6.19"))
kg = KernelGenerationGraph([k51, k52])
check("KernelGeneration manifest roundtrips", KernelGeneration.parse(json.loads(k52.canonical_manifest())) == k52)
check("newest verified kernel ancestor is exact", kg.newest_verified_ancestor(k52.kernel_generation_id) == k52)
check("artifact introduction is lineage-queryable", kg.first_introducing(k52.kernel_image_id) == k52)
check("shared artifact introduction resolves to oldest lineage member", kg.first_introducing(MICROCODE_ART, descendant=k52.kernel_generation_id) == k51)

observed = {
    KERNEL_ART: kernel_bytes, INITRAMFS_ART: initramfs_bytes, MODULES_TREE: modules_manifest,
    MODULE_ART: module_bytes, MICROCODE_ART: microcode_bytes,
}
check("kernel artifacts verify by content", verify_artifacts(k51, observed) == (True, ()))
bad = dict(observed)
bad[KERNEL_ART] = b"changed"
check("changed kernel artifact fails verification", not verify_artifacts(k51, bad)[0])

with tempfile.TemporaryDirectory() as td:
    store = ContentAddressedArtifactStore(td)
    first_id, first_path = store.put(kernel_bytes)
    second_id, second_path = store.put(kernel_bytes)
    check("content-addressed storage deduplicates identical artifacts", first_id == second_id and first_path == second_path and store.verify(first_id))
    check("content-addressed store is outside production ESP", str(first_path).startswith(td) and "/boot/" not in str(first_path))

system = SystemGeneration.create(
    parent_generation_id=None,
    root_identity=RootIdentity("snapper:root:210", "uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "a" * 64),
    kernel_generation_id=k51.kernel_generation_id, package_set_identity="pkg-" + "b" * 64,
    transaction_id=TX1, provenance_id=PROV, artifact_ids=(KERNEL_ART,), trust_state=TrustState.VERIFIED,
)
sg = GenerationGraph([system])
compat = CompatibilityEvidence(
    system_generation_id=system.generation_id, kernel_generation_id=k51.kernel_generation_id,
    root_manifest_sha256="a" * 64, filesystem_identity="uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    kernel_abi="6.18-maho", modules_abi="6.18-maho", verifier_identity="guardian-fixture",
    independently_verified=True,
)
check("exact evidence answers whether K51 can boot G210", can_boot(k51, system, compat))
check("version resemblance without evidence never proves compatibility", not can_boot(k51, system, None))
wrong = CompatibilityEvidence(**(compat.__dict__ | {"root_manifest_sha256": "f" * 64}))
check("mismatched root evidence blocks compatibility", not can_boot(k51, system, wrong))
check("SystemGeneration references are queryable", system_generations_referencing(sg, k51.kernel_generation_id) == (system.generation_id,))
check("kernel-only recovery can be proven for an exact pair", can_boot(k51, system, compat) and kg.effective_trust(k51.kernel_generation_id) is TrustState.VERIFIED)
pair = newest_verified_pair(system.generation_id, sg, kg, {(system.generation_id, k51.kernel_generation_id): compat})
check("newest complete verified pair is selected", pair == (system, k51))

unknown_kernel = kernel(trust=TrustState.UNKNOWN)
unknown_graph = KernelGenerationGraph([unknown_kernel])
check("UNKNOWN kernel has no verified ancestor", unknown_graph.newest_verified_ancestor(unknown_kernel.kernel_generation_id) is None)
rejects("malformed modules path is rejected", lambda: modules_tree_artifact({"../../escape.ko": MODULE_ART}))
malformed = k51.as_dict() | {"kernel_image_id": "art-broken"}
rejects("malformed kernel artifact reference fails closed", lambda: KernelGeneration.parse(malformed))
forward = k51.as_dict() | {"schema_version": 2}
rejects("forward KernelGeneration schema fails closed", lambda: KernelGeneration.parse(forward))

print("ALL KERNEL GENERATION TESTS PASS")
