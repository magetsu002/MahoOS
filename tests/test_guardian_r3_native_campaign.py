#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, pathlib, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "lib/guardian_r3_native_campaign.py"

def check(name: str, ok: bool) -> None:
    if not ok: raise AssertionError(name)
    print("PASS", name)

def write_json(path: pathlib.Path, value) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")

def art(store: pathlib.Path, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest(); aid = "art-" + digest
    path = store / "sha256" / digest[:2] / digest[2:]; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(payload)
    return aid

def fixture(root: pathlib.Path):
    evidence = root / "evidence"; store = evidence / "artifacts"
    kernel = art(store, b"kernel"); initramfs = art(store, b"initramfs"); modules = art(store, b"modules"); microcode = art(store, b"microcode")
    current_system = "gen-" + "1" * 64; current_kernel = "kgen-" + "2" * 64; target_kernel = "kgen-" + "3" * 64
    kdir = evidence / "manifests/kernel"; kdir.mkdir(parents=True)
    write_json(kdir / f"{target_kernel}.json", {
        "kernel_generation_id": target_kernel, "trust_state": "VERIFIED", "kernel_image_id": kernel,
        "initramfs_id": initramfs, "modules_tree_id": modules, "microcode_ids": [microcode],
        "kernel_abi": "6.18.42-1-cachyos-lts", "modules_abi": "6.18.42-1-cachyos-lts",
    })
    campaign = "r2-20260913T151805Z-9192ef7a"
    manifest = root / "r2-manifest.json"
    write_json(manifest, {"campaign_id": campaign, "root": {"uuid": "root-uuid"}, "selection_fixture": {
        "current_system_generation_id": current_system, "suspected_kernel_generation_id": current_kernel,
        "current_package_set_sha256": "4" * 64,
    }})
    report = root / "r2-report.json"
    write_json(report, {"schema_version": 2, "campaign_id": campaign, "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "outcome": "PASS", "reason": "independently_trusted_generation_pair_selected", "selection": {
            "outcome": "READY", "selection_matches_expected": True, "incident_id": "inc-determinism",
            "target_kernel_generation_id": target_kernel,
        }})
    return manifest, report, evidence

def run(out: pathlib.Path, manifest: pathlib.Path, report: pathlib.Path, evidence: pathlib.Path):
    return subprocess.run([sys.executable, str(SCRIPT), str(out), str(manifest), str(report), str(evidence)], text=True, capture_output=True)

def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td); manifest, report, evidence = fixture(root)
        a = run(root / "out-a", manifest, report, evidence); b = run(root / "out-b", manifest, report, evidence)
        check("identical certified R2 evidence builds twice", a.returncode == 0 and b.returncode == 0)
        check("R3 intent generation is byte deterministic", (root / "out-a/intent.json").read_bytes() == (root / "out-b/intent.json").read_bytes())
        check("R3 metadata generation is byte deterministic", (root / "out-a/metadata.json").read_bytes() == (root / "out-b/metadata.json").read_bytes())
        check("R3 generator output is deterministic", a.stdout == b.stdout)
        manifest.write_text(manifest.read_text().replace("root-uuid", "tampered-root"))
        bad = run(root / "out-tampered", manifest, report, evidence)
        check("tampered R2 manifest is rejected before R3 generation", bad.returncode != 0 and "digest does not match" in bad.stderr)
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td); manifest, report, evidence = fixture(root)
        data = json.loads(report.read_text()); data["campaign_id"] = "r2-20260913T151806Z-9192ef7a"; data["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest(); write_json(report, data)
        bad = run(root / "out-mismatch", manifest, report, evidence)
        check("mismatched R2 campaign identity is rejected", bad.returncode != 0 and "campaign identity mismatch" in bad.stderr)
    print("ALL GUARDIAN R3 NATIVE CAMPAIGN TESTS PASS")

if __name__ == "__main__": main()
