#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from maho_generation_v2 import RootIdentity, SystemGeneration
from maho_kernel_generation import CompatibilityEvidence, ContentAddressedArtifactStore, KernelGeneration
from maho_trust_identity import ArtifactID, ProvenanceID, TransactionID, TrustState, canonical_bytes

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def package_set(root: pathlib.Path) -> tuple[str, bytes]:
    local = root / "var/lib/pacman/local"
    names = sorted(p.name for p in local.iterdir() if p.is_dir())
    data = ("\n".join(names) + "\n").encode()
    return sha(data), data

def modules_manifest(root: pathlib.Path, release: str) -> bytes:
    base = root / "usr/lib/modules" / release
    rows = []
    for p in sorted(x for x in base.rglob("*") if x.is_file() and not x.is_symlink()):
        rows.append({"path": str(p.relative_to(base)), "sha256": sha(p.read_bytes())})
    return canonical_bytes({"release": release, "files": rows})
def make_kernel(*, release: str, prefix: str, parent, trust: TrustState, tx, prov,
                module_root: pathlib.Path, store: ContentAddressedArtifactStore | None):
    kernel = pathlib.Path(f"/boot/vmlinuz-linux-cachyos{prefix}").read_bytes()
    initramfs = pathlib.Path(f"/boot/initramfs-linux-cachyos{prefix}.img").read_bytes()
    modules = modules_manifest(module_root, release)
    microcode = pathlib.Path("/boot/intel-ucode.img").read_bytes()
    ids = [ArtifactID.from_content(x) for x in (kernel, initramfs, modules, microcode)]
    if store is not None:
        for payload in (kernel, initramfs, modules, microcode):
            store.put(payload)
    return KernelGeneration.create(
        parent_kernel_generation_id=parent,
        kernel_image_id=ids[0], initramfs_id=ids[1], modules_tree_id=ids[2],
        dkms_output_ids=(), microcode_ids=(ids[3],),
        cmdline_contract="root=UUID=maho-ro recovery-selection",
        package_provider_identity=f"cachyos/{release}",
        provenance_id=prov, transaction_id=tx,
        kernel_abi=release, modules_abi=release, trust_state=trust,
    )

def main() -> int:
    if len(sys.argv) != 7:
        raise SystemExit("usage: guardian_r2_fixture.py OUT SNAPSHOT_ROOT ROOT_UUID SNAPSHOT_ID CURRENT_RELEASE LTS_RELEASE")
    out = pathlib.Path(sys.argv[1]); snap = pathlib.Path(sys.argv[2]); root_uuid = sys.argv[3]
    snapshot_id, current_release, lts_release = sys.argv[4:]
    evidence = out / "evidence"; store = ContentAddressedArtifactStore(evidence / "artifacts")
    prov = ProvenanceID.derive({"guardian-r2":"native-selection-fixture","root_uuid":root_uuid})
    tx_old = TransactionID.derive({"guardian-r2":"old","snapshot":snapshot_id})
    tx_new = TransactionID.derive({"guardian-r2":"current","kernel":current_release})
    old_kernel = make_kernel(
        release=lts_release, prefix="-lts", parent=None, trust=TrustState.VERIFIED,
        tx=tx_old, prov=prov, module_root=snap, store=store,
    )
    new_kernel = make_kernel(
        release=current_release, prefix="", parent=old_kernel.kernel_generation_id,
        trust=TrustState.REVOKED, tx=tx_new, prov=prov,
        module_root=pathlib.Path("/"), store=None,
    )
    old_pkg_sha, old_pkg_bytes = package_set(snap)
    new_pkg_sha, _ = package_set(pathlib.Path("/"))
    old_root_material = canonical_bytes({
        "snapshot": f"@snapshots/{snapshot_id}/snapshot",
        "package_set_sha256": old_pkg_sha,
        "root_uuid": root_uuid,
    })
    new_root_material = canonical_bytes({
        "snapshot": "@", "package_set_sha256": new_pkg_sha, "root_uuid": root_uuid,
    })
    old_system = SystemGeneration.create(
        parent_generation_id=None,
        root_identity=RootIdentity(f"btrfs:@snapshots/{snapshot_id}/snapshot", f"uuid:{root_uuid}", sha(old_root_material)),
        kernel_generation_id=old_kernel.kernel_generation_id,
        package_set_identity="pkg-" + old_pkg_sha,
        transaction_id=tx_old, provenance_id=prov,
        artifact_ids=(old_kernel.kernel_image_id,), trust_state=TrustState.VERIFIED,
    )
    new_system = SystemGeneration.create(
        parent_generation_id=old_system.generation_id,
        root_identity=RootIdentity("btrfs:@", f"uuid:{root_uuid}", sha(new_root_material)),
        kernel_generation_id=new_kernel.kernel_generation_id,
        package_set_identity="pkg-" + new_pkg_sha,
        transaction_id=tx_new, provenance_id=prov,
        artifact_ids=(new_kernel.kernel_image_id,), trust_state=TrustState.VERIFIED,
    )
    for d in ("manifests/system", "manifests/kernel", "evidence/compatibility"):
        (evidence / d).mkdir(parents=True, exist_ok=True)
    for item in (old_system, new_system):
        (evidence / "manifests/system" / f"{item.generation_id}.json").write_text(item.canonical_manifest())
    for item in (old_kernel, new_kernel):
        (evidence / "manifests/kernel" / f"{item.kernel_generation_id}.json").write_text(item.canonical_manifest())
    for i, (system, kernel) in enumerate(((old_system, old_kernel), (new_system, new_kernel))):
        compat = CompatibilityEvidence(
            system.generation_id, kernel.kernel_generation_id,
            system.root_identity.root_manifest_sha256, f"uuid:{root_uuid}",
            kernel.kernel_abi, kernel.modules_abi, "guardian-r2-native-fixture", True,
        )
        value = compat.__dict__ | {
            "system_generation_id": str(compat.system_generation_id),
            "kernel_generation_id": str(compat.kernel_generation_id),
        }
        (evidence / "evidence/compatibility" / f"pair-{i}.json").write_text(json.dumps(value, sort_keys=True))
    metadata = {
        "schema_version": 1,
        "fixture_kind": "native-r2-real-snapshot-synthetic-revocation",
        "current_system_generation_id": str(new_system.generation_id),
        "suspected_kernel_generation_id": str(new_kernel.kernel_generation_id),
        "expected_system_generation_id": str(old_system.generation_id),
        "expected_kernel_generation_id": str(old_kernel.kernel_generation_id),
        "expected_snapshot_path": f"@snapshots/{snapshot_id}/snapshot",
        "expected_snapshot_package_set_sha256": old_pkg_sha,
        "current_package_set_sha256": new_pkg_sha,
        "incident_id": "inc-r2-native-selection",
        "old_kernel_release": lts_release,
        "current_kernel_release": current_release,
    }
    (out / "fixture.json").write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n")
    (out / "snapshot-packages.txt").write_bytes(old_pkg_bytes)
    print(json.dumps(metadata, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
