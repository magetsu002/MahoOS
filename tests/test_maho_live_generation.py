#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_live_generation import LiveGenerationObservation, publish_live_generations, publish_initial_live_generations, read_live_publication  # noqa: E402
from maho_generation_v2 import RootIdentity, SystemGeneration  # noqa: E402
from maho_kernel_generation import KernelGeneration  # noqa: E402
from maho_trust_identity import ArtifactID, TrustState, canonical_bytes  # noqa: E402
from maho_update_receipts import build_receipt  # noqa: E402
from maho_update_state import UpdateState, bind_native_authority, create_transaction, transition_transaction  # noqa: E402


NOW = datetime(2026, 9, 24, 19, 42, tzinfo=timezone.utc)
TXID = "upd-20260924T185307Z-8c9c00b0dbc9"
SOURCE = "6b0dda9c515a97358e40e519c9ee10b85aecc567"
CANDIDATE = "6c1473c2-60fa-984d-a49b-11c7458d57be"
PREVIOUS = "a7a682fe-1f34-5d4e-b912-1f9720b7aebb"
FSUUID = "ce979d1c-c145-4be0-9ce3-591b6fd0a3a1"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def rejects(name: str, operation) -> None:
    try:
        operation()
    except (KeyError, TypeError, ValueError):
        print("PASS", name)
        return
    raise AssertionError(name)


def transaction() -> dict:
    packages = [
        {"name": name, "installed_version": "old", "candidate_version": version,
         "repository": "cachyos", "download_size": 1, "installed_size": 1,
         "roles": ["kernel"] if name.startswith("linux-cachyos") else [],
         "security_relevant": True}
        for name, version in {
            "linux-cachyos": "7.2.5-1", "linux-cachyos-headers": "7.2.5-1",
            "linux-cachyos-lts": "6.18.50-1", "linux-cachyos-lts-headers": "6.18.50-1",
            "nvidia-580xx-dkms": "580.178.04-1", "intel-ucode": "20260812-1",
        }.items()
    ]
    value = create_transaction(
        transaction_id=TXID, source_revision=SOURCE, packages=packages,
        activation_requirements=["restart", "initramfs", "boot-artifacts"],
        recovery_generation_id="g3-623c64a36c689d4d23c82130", now=NOW,
    )
    value = bind_native_authority(
        value, recovery_generation_id="g3-623c64a36c689d4d23c82130",
        m3b_evidence={"physical": True}, update_kind="m4b-campaign",
        update_evidence={"physical": True},
    )
    for offset, state in enumerate((
        UpdateState.STAGED, UpdateState.PREPARED, UpdateState.MAINTENANCE_READY,
        UpdateState.INSTALLING, UpdateState.INSTALLED_PENDING_ACTIVATION,
        UpdateState.ACTIVE_VERIFYING,
    ), 1):
        value = transition_transaction(value, state, now=NOW + timedelta(minutes=offset))
    return transition_transaction(
        value, UpdateState.HEALTHY, now=NOW + timedelta(minutes=7),
        evidence={"ok": True, "root_uuid": CANDIDATE, "previous_root_uuid": PREVIOUS,
                  "previous_root_read_only": True},
    )


def fixture():
    tx = transaction()
    expected = {item["name"]: item["candidate_version"] for item in tx["package_generation"]["packages"]}
    boot = {
        "/boot/intel-ucode.img": b"microcode",
        "/boot/vmlinuz-linux-cachyos": b"primary-kernel",
        "/boot/initramfs-linux-cachyos.img": b"primary-initramfs",
        "/boot/vmlinuz-linux-cachyos-lts": b"fallback-kernel",
        "/boot/initramfs-linux-cachyos-lts.img": b"fallback-initramfs",
    }
    hashes = {name: __import__("hashlib").sha256(data).hexdigest() for name, data in boot.items()}
    home = {"source": "/dev/test[/@home]", "uuid": FSUUID, "fsroot": "/@home"}
    journal = {
        "schema_version": 1, "transaction_id": TXID, "transaction_state": "HEALTHY",
        "phase": "verified", "source_revision": SOURCE, "expected_versions": expected,
        "candidate": {"uuid": CANDIDATE},
        "activation": {"boot_sha256": hashes, "previous_root_uuid": PREVIOUS},
        "home_identity": home, "l3_seed": {"generation_id": "g3-623c64a36c689d4d23c82130"},
        "frozen_admission": {"graph_id": "art-" + "1" * 64, "evidence_id": "art-" + "2" * 64},
        "activation_authority": {"authority_id": "art-" + "3" * 64},
    }
    observation = LiveGenerationObservation(
        filesystem_uuid=FSUUID, root_subvolume_uuid=CANDIDATE, fsroot="/@",
        running_kernel="7.2.5-1-cachyos", cmdline=f"root=UUID={FSUUID} rw rootflags=subvol=@",
        package_versions=expected, boot_artifacts=boot,
        module_artifacts={"kernel/demo.ko": b"module", "updates/dkms/nvidia.ko": b"nvidia"},
        dkms_artifacts={"updates/dkms/nvidia.ko": b"nvidia"},
        runtime_source_revision=SOURCE, runtime_content_sha256="4" * 64,
        home_identity=home, recovery_generation_id="g3-623c64a36c689d4d23c82130",
        previous_root_uuid=PREVIOUS, previous_root_read_only=True,
    )
    return tx, journal, build_receipt(tx), observation


def main() -> None:
    tx, journal, receipt, observation = fixture()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result = publish_live_generations(tx, journal, receipt, observation, publisher_source_revision="a" * 40, root=root)
        check("HEALTHY physical proof publishes exact generation pair", result["transaction_id"] == TXID and result["system_generation_id"].startswith("gen-") and result["kernel_generation_id"].startswith("kgen-"))
        check("published generation authority verifies and roundtrips", read_live_publication(root) == result)
        check("first legitimate lineage has no manufactured historical parent", json.loads(next((root / "manifests/system").iterdir()).read_text())["parent_generation_id"] is None)
        tampered = json.loads((root / "live.json").read_text())
        tampered["package_generation_id"] = "pkg-" + "f" * 64
        (root / "live.json").write_text(json.dumps(tampered))
        check("tampered live publication fails closed", read_live_publication(root) is None)
        for key, changed in (
            ("package_generation_id", "pkg-" + "f" * 64),
            ("native_transaction_id", "txn-" + "f" * 64),
            ("transaction_id", "upd-20260924T185307Z-ffffffffffff"),
            ("source_revision", "f" * 40),
            ("filesystem_uuid", PREVIOUS), ("root_subvolume_uuid", PREVIOUS),
            ("running_kernel", "wrong-kernel"), ("cmdline_sha256", "f" * 64),
            ("boot_sha256", {}), ("recovery_generation_id", "wrong-recovery"),
            ("previous_root_uuid", CANDIDATE), ("previous_root_read_only", False),
        ):
            relabelled = dict(result)
            relabelled.pop("publication_id")
            relabelled[key] = changed
            relabelled["publication_id"] = "art-" + __import__("hashlib").sha256(
                json.dumps(relabelled, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            (root / "live.json").write_text(json.dumps(relabelled))
            check("rehashed " + key + " relabelling fails closed", read_live_publication(root) is None)
        (root / "live.json").write_text(json.dumps(result))
        check("original exact publication remains valid", read_live_publication(root) == result)

        # Exercise the separate first-boot publisher with its actual root-proof
        # schema; it has no previous-root lineage to borrow from an update.
        kernel = KernelGeneration.parse(json.loads(next((root / "manifests/kernel").iterdir()).read_text()))
        base_system = SystemGeneration.parse(json.loads(next((root / "manifests/system").iterdir()).read_text()))
        initial = root / "initial"
        attempt, installation, recovery = "install-test", "installation-test", "recovery-test"
        proof_bytes = canonical_bytes({"schema_version": 1, "kind": "maho-initial-root-manifest",
            "source_revision": SOURCE, "install_attempt_id": attempt,
            "installation_uuid": installation, "recovery_identity": recovery})
        artifact = ArtifactID.from_content(proof_bytes)
        digest = str(artifact)[4:]
        path = initial / "artifacts/sha256" / digest[:2] / digest[2:]
        path.parent.mkdir(parents=True); path.write_bytes(proof_bytes)
        system = SystemGeneration.create(parent_generation_id=None,
            root_identity=RootIdentity("btrfs-subvolume:@", "uuid:" + FSUUID, digest),
            kernel_generation_id=kernel.kernel_generation_id,
            package_set_identity=base_system.package_set_identity,
            transaction_id=base_system.transaction_id, provenance_id=base_system.provenance_id,
            artifact_ids=(artifact,), trust_state=TrustState.UNKNOWN)
        for kind, identity, manifest in (
            ("system", system.generation_id, system.canonical_manifest()),
            ("kernel", kernel.kernel_generation_id, replace(kernel, trust_state=TrustState.UNKNOWN).canonical_manifest()),
        ):
            path = initial / "manifests" / kind / (str(identity) + ".json")
            path.parent.mkdir(parents=True); path.write_text(manifest)
        (initial / "initial-pending.json").write_text(json.dumps({"root_manifest_artifact_id": str(artifact)}))
        ids = {"system_generation_id": str(system.generation_id),
               "kernel_generation_id": str(kernel.kernel_generation_id),
               "package_generation_id": system.package_set_identity, "boot_generation_id": "bootgen-" + "a" * 64}
        storage = {"btrfs_uuid": FSUUID, "root_fsroot": "/@", "root_subvolume_uuid": CANDIDATE}
        boot = {"running_kernel": kernel.kernel_abi, "cmdline": observation.cmdline, "boot_sha256": result["boot_sha256"]}
        initial_receipt = {**ids, "source_revision": SOURCE, "installation_uuid": installation,
            "install_attempt_id": attempt, "recovery_identity": recovery, "storage": storage,
            "kernel": {"primary_release": kernel.kernel_abi}, "boot": boot}
        published = publish_initial_live_generations(initial_receipt,
            {"generations": ids, "storage": storage, "boot": boot}, root=initial)
        check("first-boot publication retains exact independent manifest bindings", read_live_publication(initial) == published)
        for key in ("initial_installation_uuid", "recovery_generation_id", "source_revision"):
            changed = dict(published); changed.pop("publication_id"); changed[key] = "wrong-identity"
            changed["publication_id"] = str(ArtifactID.from_content(canonical_bytes(changed)))
            (initial / "live.json").write_text(json.dumps(changed))
            check("first-boot rehashed " + key + " drift fails closed", read_live_publication(initial) is None)

    bad = LiveGenerationObservation(**(observation.__dict__ | {"root_subvolume_uuid": PREVIOUS}))
    rejects("candidate UUID drift blocks generation publication", lambda: publish_live_generations(tx, journal, receipt, bad, publisher_source_revision="a" * 40, root=Path(temporary)))
    bad = LiveGenerationObservation(**(observation.__dict__ | {"previous_root_read_only": False}))
    rejects("mutable previous root blocks generation publication", lambda: publish_live_generations(tx, journal, receipt, bad, publisher_source_revision="a" * 40, root=Path(temporary)))
    print("ALL LIVE GENERATION PUBLICATION TESTS PASS")


if __name__ == "__main__":
    main()
