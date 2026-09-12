#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_generation_v2 import (  # noqa: E402
    GenerationGraph, RootIdentity, SystemGeneration, from_legacy_recovery,
)
from maho_trust_identity import (  # noqa: E402
    ArtifactID, KernelGenerationID, ProvenanceID, TransactionID, TrustState,
)


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


TX1 = TransactionID.derive({"tx": 1})
TX2 = TransactionID.derive({"tx": 2})
PROV = ProvenanceID.derive({"builder": "test"})
KERNEL = KernelGenerationID.derive({"kernel": "6.18"})
ART1 = ArtifactID.from_content(b"package-one")
ART2 = ArtifactID.from_content(b"package-two")
FS = "uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def generation(parent=None, *, tx=TX1, artifacts=(ART1,), trust=TrustState.VERIFIED, fs=FS, root_hash="1" * 64):
    return SystemGeneration.create(
        parent_generation_id=parent.generation_id if parent else None,
        root_identity=RootIdentity("snapper:root:20", fs, root_hash),
        kernel_generation_id=KERNEL, package_set_identity="pkg-" + "2" * 64,
        transaction_id=tx, provenance_id=PROV, artifact_ids=artifacts,
        trust_state=trust,
    )


root = generation()
child = generation(root, tx=TX2, artifacts=(ART2,), root_hash="3" * 64)
graph = GenerationGraph([root, child], artifact_transactions={ART1: TX1, ART2: TX2})
check("canonical SystemGeneration manifest roundtrips", SystemGeneration.parse(json.loads(child.canonical_manifest())) == child)
check("lineage traversal reaches parent", [x.generation_id for x in graph.lineage(child.generation_id)] == [child.generation_id, root.generation_id])
check("ancestor lookup excludes self", graph.ancestors(child.generation_id) == (root,))
check("artifact maps to exact generation", graph.generations_for_artifact(ART2) == (child.generation_id,))
check("generation maps to exact transaction", graph.transaction_for(child.generation_id) == TX2)
check("verified lineage remains verified", graph.effective_trust(child.generation_id) is TrustState.VERIFIED)

rejects("missing parent fails closed", lambda: GenerationGraph([child]))
rejects("duplicate IDs fail closed", lambda: GenerationGraph([root, root]))

cycle_a = root.as_dict()
cycle_b = child.as_dict()
cycle_a["parent_generation_id"] = cycle_b["generation_id"]
cycle_a["generation_id"] = str(SystemGeneration.parse(root.as_dict()).generation_id)
# Constructor identity protection prevents editing a manifest into a cycle. Build
# two test-only objects without __post_init__ to exercise graph cycle handling.
a = object.__new__(SystemGeneration)
b = object.__new__(SystemGeneration)
for target, source in ((a, root), (b, child)):
    for key, value in source.__dict__.items():
        object.__setattr__(target, key, value)
object.__setattr__(a, "parent_generation_id", b.generation_id)
object.__setattr__(b, "parent_generation_id", a.generation_id)
rejects("parent cycle fails closed", lambda: GenerationGraph([a, b]))

rejects("mismatched filesystem identity fails closed", lambda: GenerationGraph([root], expected_filesystems={root.generation_id: "uuid:ffffffff-ffff-ffff-ffff-ffffffffffff"}))
rejects("mismatched artifact transaction fails closed", lambda: GenerationGraph([root], artifact_transactions={ART1: TX2}))

unknown_parent = generation(trust=TrustState.UNKNOWN)
unknown_child = generation(unknown_parent, tx=TX2, artifacts=(ART2,), root_hash="4" * 64)
unknown_graph = GenerationGraph([unknown_parent, unknown_child])
check("UNKNOWN parent keeps descendant UNKNOWN", unknown_graph.effective_trust(unknown_child.generation_id) is TrustState.UNKNOWN)

revoked_parent = generation(trust=TrustState.REVOKED)
revoked_child = generation(revoked_parent, tx=TX2, artifacts=(ART2,), root_hash="5" * 64)
revoked_graph = GenerationGraph([revoked_parent, revoked_child])
check("REVOKED ancestor contaminates descendant", revoked_graph.effective_trust(revoked_child.generation_id) is TrustState.CONTAMINATED)
check("newest verified ancestor is explicit and lineage bounded", revoked_graph.newest_verified_ancestor(revoked_child.generation_id) is None)

legacy = from_legacy_recovery({
    "generation_id": "g3-1234567890abcdef12345678",
    "root_filesystem_uuid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "snapshot": {"config_name": "root", "snapshot_id": 12},
})
check("pre-schema recovery generation migrates as UNKNOWN", legacy.trust_state is TrustState.UNKNOWN and legacy.metadata_status == "LEGACY_PARTIAL")
check("historical partial metadata remains non-eligible", legacy.kernel_generation_id is None and legacy.transaction_id is None)
check("legacy manifest roundtrips without trust promotion", SystemGeneration.parse(json.loads(legacy.canonical_manifest())).trust_state is TrustState.UNKNOWN)

broken_artifact = child.as_dict()
broken_artifact["artifact_ids"] = ["art-broken"]
rejects("malformed artifact reference fails closed", lambda: SystemGeneration.parse(broken_artifact))
broken_manifest = child.as_dict()
broken_manifest["root_identity"]["root_manifest_sha256"] = "broken"
rejects("broken root manifest fails closed", lambda: SystemGeneration.parse(broken_manifest))
forward = child.as_dict() | {"schema_version": 3}
rejects("forward schema version fails closed", lambda: SystemGeneration.parse(forward))
unknown_field = child.as_dict() | {"future_authority": "yes"}
rejects("unknown schema field fails closed", lambda: SystemGeneration.parse(unknown_field))

print("ALL VERIFIED GENERATIONS V2 TESTS PASS")
