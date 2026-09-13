#!/usr/bin/env python3
from __future__ import annotations
import json, pathlib, shutil, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from maho_generation_v2 import RootIdentity, SystemGeneration
from maho_kernel_generation import CompatibilityEvidence, ContentAddressedArtifactStore, KernelGeneration, modules_tree_artifact
from maho_trust_identity import ArtifactID, ProvenanceID, TransactionID, TrustState

def check(name: str, value: bool) -> None:
    if not value:
        raise AssertionError(name)
    print("PASS", name)

def fixture(base: pathlib.Path):
    evidence = base / "evidence"
    for d in ("manifests/system", "manifests/kernel", "evidence/compatibility"):
        (evidence / d).mkdir(parents=True)
    store = ContentAddressedArtifactStore(evidence / "artifacts")
    payload = {k: v.encode() for k, v in {"oldk":"old-kernel","oldi":"old-initramfs","newk":"new-kernel","newi":"new-initramfs","mod":"module","ucode":"microcode"}.items()}
    ids = {k: ArtifactID.from_content(v) for k, v in payload.items()}
    modules_id, modules_payload = modules_tree_artifact({"kernel/demo.ko": ids["mod"]})
    prov = ProvenanceID.derive({"r2":"fixture"}); old_tx = TransactionID.derive({"r2":1}); new_tx = TransactionID.derive({"r2":2})
    old_kernel = KernelGeneration.create(parent_kernel_generation_id=None,
        kernel_image_id=ids["oldk"], initramfs_id=ids["oldi"], modules_tree_id=modules_id,
        dkms_output_ids=(ids["mod"],), microcode_ids=(ids["ucode"],), cmdline_contract="root=ro",
        package_provider_identity="fixture/lts", provenance_id=prov, transaction_id=old_tx,
        kernel_abi="abi-old", modules_abi="abi-old", trust_state=TrustState.VERIFIED)
    new_kernel = KernelGeneration.create(parent_kernel_generation_id=old_kernel.kernel_generation_id,
        kernel_image_id=ids["newk"], initramfs_id=ids["newi"], modules_tree_id=modules_id,
        dkms_output_ids=(ids["mod"],), microcode_ids=(ids["ucode"],), cmdline_contract="root=ro",
        package_provider_identity="fixture/current", provenance_id=prov, transaction_id=new_tx,
        kernel_abi="abi-new", modules_abi="abi-new", trust_state=TrustState.REVOKED)
    fs = "uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    old_system = SystemGeneration.create(parent_generation_id=None,
        root_identity=RootIdentity("btrfs:@snapshots/1/snapshot", fs, "1"*64),
        kernel_generation_id=old_kernel.kernel_generation_id, package_set_identity="pkg-"+"1"*64,
        transaction_id=old_tx, provenance_id=prov, artifact_ids=(ids["oldk"],), trust_state=TrustState.VERIFIED)
    new_system = SystemGeneration.create(parent_generation_id=old_system.generation_id,
        root_identity=RootIdentity("btrfs:@", fs, "2"*64), kernel_generation_id=new_kernel.kernel_generation_id,
        package_set_identity="pkg-"+"2"*64, transaction_id=new_tx, provenance_id=prov,
        artifact_ids=(ids["newk"],), trust_state=TrustState.VERIFIED)
    for item in (old_system, new_system):
        (evidence/"manifests/system"/f"{item.generation_id}.json").write_text(item.canonical_manifest())
    for item in (old_kernel, new_kernel):
        (evidence/"manifests/kernel"/f"{item.kernel_generation_id}.json").write_text(item.canonical_manifest())
    for i, (system, kernel) in enumerate(((old_system, old_kernel), (new_system, new_kernel))):
        ev = CompatibilityEvidence(system.generation_id, kernel.kernel_generation_id,
            system.root_identity.root_manifest_sha256, fs, kernel.kernel_abi, kernel.modules_abi,
            "guardian-r2-test", True)
        body = ev.__dict__ | {"system_generation_id":str(ev.system_generation_id), "kernel_generation_id":str(ev.kernel_generation_id)}
        (evidence/"evidence/compatibility"/f"pair-{i}.json").write_text(json.dumps(body))
    for value in payload.values(): store.put(value)
    store.put(modules_payload)
    campaign = {"selection_authority": {
        "environment_id":"guardian-recovery-r2:test", "trust_state":"VERIFIED",
        "verification_authority":"guardian-r1-native-mechanics:test",
        "verification_kernel_id":"guardian-recovery-kernel:independent"},
        "selection_fixture": {"current_system_generation_id":str(new_system.generation_id),
        "suspected_kernel_generation_id":str(new_kernel.kernel_generation_id), "incident_id":"inc-r2-test",
        "expected_system_generation_id":str(old_system.generation_id), "expected_kernel_generation_id":str(old_kernel.kernel_generation_id)}}
    manifest = base / "campaign.json"; manifest.write_text(json.dumps(campaign))
    return evidence, manifest, old_kernel

def run_selector(evidence: pathlib.Path, manifest: pathlib.Path):
    env = dict(**__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT / "lib")
    cp = subprocess.run([sys.executable, str(ROOT/"lib/maho_guardian_r2_select.py"), str(evidence), str(manifest)],
        text=True, capture_output=True, env=env)
    data = json.loads(cp.stdout) if cp.stdout.strip() else {}
    return cp.returncode, data

def main() -> int:
    stage = (ROOT/"bin/maho-guardian-recovery-r2-stage").read_text()
    verifier = (ROOT/"lib/maho-guardian-recovery-r2").read_text()
    service = (ROOT/"config/systemd/initrd/maho-guardian-recovery-r2.service").read_text()
    hook = (ROOT/"config/mkinitcpio/install/sd-maho-guardian-recovery-r2").read_text()
    check("R2 verifier runs before initrd cleanup", "Before=initrd-cleanup.service initrd-switch-root.target" in service)
    check("R2 initramfs carries manifest-copy primitive", " cp " in (" " + hook + " "))
    check("R2 copies staged manifest into stable initrd state", 'cp "$esp_manifest" "$LOCAL_MANIFEST"' in verifier)
    check("R2 stager preserves Primary default", "default_entry: MahoOS/Primary" in stage)
    check("R2 stager binds exact Limine campaign", "verify_limine_binding" in stage)
    check("R2 verifier requires read-only root", "root_not_read_only" in verifier)
    check("R2 verifier checks real snapshot package identity", "expected_snapshot_package_set_mismatch" in verifier)
    check("R2 verifier never stages recovery mutation", "stage-bounded-generation-restore" not in verifier)
    with tempfile.TemporaryDirectory() as td:
        evidence, manifest, old_kernel = fixture(pathlib.Path(td))
        rc, result = run_selector(evidence, manifest)
        check("revoked current kernel selects older verified pair", rc == 0 and result.get("selection_matches_expected") is True)
        check("selection names exact expected kernel", result.get("target_kernel_generation_id") == str(old_kernel.kernel_generation_id))
        victim = next((evidence/"evidence/compatibility").glob("pair-0.json")); victim.unlink()
        rc, result = run_selector(evidence, manifest)
        check("missing compatibility evidence fails closed", rc != 0 and result.get("selection_matches_expected") is False)
    print("ALL GUARDIAN RECOVERY R2 CONTRACTS PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
