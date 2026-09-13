#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, pathlib, re, shutil, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from guardian_recovery_r3 import R3RecoveryIntent, intent_envelope, recovery_operations
from maho_trust_identity import GenerationID, KernelGenerationID

def fail(msg: str) -> None:
    raise SystemExit(msg)

def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def artifact_path(store: pathlib.Path, artifact_id: str) -> pathlib.Path:
    digest = artifact_id.removeprefix("art-")
    return store / "sha256" / digest[:2] / digest[2:]

def main() -> int:
    if len(sys.argv) != 5:
        fail("usage: guardian_r3_native_campaign.py OUT R2_MANIFEST R2_REPORT R2_EVIDENCE")
    out, r2m_path, r2r_path, r2e = map(pathlib.Path, sys.argv[1:])
    r2m = json.loads(r2m_path.read_text()); r2r = json.loads(r2r_path.read_text())
    manifest_sha = r2r.get("manifest_sha256")
    if not isinstance(manifest_sha, str) or re.fullmatch(r"[0-9a-f]{64}", manifest_sha) is None:
        fail("R2 report manifest binding is invalid")
    if sha256_file(r2m_path) != manifest_sha:
        fail("R2 manifest digest does not match certified report")
    if r2m.get("campaign_id") != r2r.get("campaign_id"):
        fail("R2 campaign identity mismatch")
    if r2r.get("outcome") != "PASS" or r2r.get("reason") != "independently_trusted_generation_pair_selected":
        fail("R2 report is not certified PASS")
    selection = r2r.get("selection", {})
    if selection.get("outcome") != "READY" or selection.get("selection_matches_expected") is not True:
        fail("R2 selection is not READY")
    fixture = r2m.get("selection_fixture", {})
    current_system = fixture.get("current_system_generation_id")
    current_kernel = fixture.get("suspected_kernel_generation_id")
    target_kernel = selection.get("target_kernel_generation_id")
    if not all(isinstance(x, str) and x for x in (current_system, current_kernel, target_kernel)):
        fail("R2 generation identities are incomplete")
    kernel_manifest = r2e / "manifests/kernel" / f"{target_kernel}.json"
    if not kernel_manifest.is_file():
        fail("selected KernelGeneration manifest is missing")
    km = json.loads(kernel_manifest.read_text())
    if km.get("kernel_generation_id") != target_kernel or km.get("trust_state") not in {"VERIFIED", "REVALIDATED"}:
        fail("selected KernelGeneration is not independently trusted")
    intent = R3RecoveryIntent(
        mode="KERNEL_ONLY", incident_id=str(selection.get("incident_id")),
        r2_campaign_id=str(r2r.get("campaign_id")),
        current_system_generation_id=GenerationID(current_system),
        current_kernel_generation_id=KernelGenerationID(current_kernel),
        target_system_generation_id=GenerationID(current_system),
        target_kernel_generation_id=KernelGenerationID(target_kernel),
        target_snapshot_identity="btrfs:@", target_snapshot_id=None,
        operations=recovery_operations("KERNEL_ONLY"),
    )
    out.mkdir(parents=True, exist_ok=False)
    evidence = out / "r2-evidence"
    shutil.copytree(r2e, evidence)
    shutil.copy2(r2m_path, out / "r2-manifest.json")
    shutil.copy2(r2r_path, out / "r2-report.json")
    (out / "intent.json").write_text(json.dumps(intent_envelope(intent), sort_keys=True, separators=(",", ":")) + "\n")
    store = evidence / "artifacts"
    ids = {
        "kernel": km["kernel_image_id"], "initramfs": km["initramfs_id"],
        "modules": km["modules_tree_id"], "microcode": km["microcode_ids"][0],
    }
    for name, artifact_id in ids.items():
        if not artifact_path(store, artifact_id).is_file():
            fail(f"selected {name} artifact is missing")
    metadata = {
        "schema_version": 1,
        "r2_campaign_id": r2r["campaign_id"],
        "r2_manifest_sha256": r2r["manifest_sha256"],
        "incident_id": selection["incident_id"],
        "current_system_generation_id": current_system,
        "suspected_kernel_generation_id": current_kernel,
        "target_system_generation_id": current_system,
        "target_kernel_generation_id": target_kernel,
        "target_kernel_release": km["kernel_abi"],
        "target_modules_release": km["modules_abi"],
        "current_package_set_sha256": fixture["current_package_set_sha256"],
        "root_uuid": r2m["root"]["uuid"],
        "artifact_ids": ids,
        "intent_sha256": intent.intent_sha256,
        "policy": "smallest-known-good-kernel-only-recovery",
    }
    (out / "metadata.json").write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(metadata, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
