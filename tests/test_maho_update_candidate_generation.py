#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import maho_update_candidate_generation as candidate_generation  # noqa: E402
from maho_generation_v2 import RootIdentity, SystemGeneration  # noqa: E402
from maho_kernel_generation import CompatibilityEvidence, KernelGeneration  # noqa: E402
from maho_live_generation import read_live_publication  # noqa: E402
from maho_trust_identity import (  # noqa: E402
    ArtifactID, ProvenanceID, TransactionID, TrustState, canonical_bytes,
)
from maho_update_candidate_generation import (  # noqa: E402
    load_current_verified_generations,
    promote_normal_candidate_generation,
    publish_normal_candidate_generation,
    read_candidate_publication,
)
from maho_update_state import UpdateState, create_transaction, transition_transaction  # noqa: E402

NOW = datetime(2026, 9, 27, 9, 0, tzinfo=timezone.utc)
TXID = "upd-20260927T090000Z-abcdefabcdef"
SOURCE = "a" * 40
CURRENT_ROOT = "11111111-1111-1111-1111-111111111111"
CANDIDATE_ROOT = "22222222-2222-2222-2222-222222222222"
FSUUID = "33333333-3333-3333-3333-333333333333"


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def current_store(root: Path) -> tuple[SystemGeneration, KernelGeneration, dict]:
    native_tx = TransactionID.derive({"kind": "fixture-current"})
    provenance = ProvenanceID.derive({"kind": "fixture-current"})
    kernel = KernelGeneration.create(
        parent_kernel_generation_id=None,
        kernel_image_id=ArtifactID.from_content(b"kernel"),
        initramfs_id=ArtifactID.from_content(b"initramfs"),
        modules_tree_id=ArtifactID.from_content(b"modules"),
        dkms_output_ids=(ArtifactID.from_content(b"dkms"),),
        microcode_ids=(ArtifactID.from_content(b"ucode"),),
        cmdline_contract="quiet rw",
        package_provider_identity="linux-cachyos=6.1",
        provenance_id=provenance,
        transaction_id=native_tx,
        kernel_abi="6.1-cachyos",
        modules_abi="6.1-cachyos",
        trust_state=TrustState.VERIFIED,
    )
    root_manifest = canonical_bytes({
        "schema_version": 1,
        "kind": "fixture-current-root",
        "uuid": CURRENT_ROOT,
    })
    root_art = ArtifactID.from_content(root_manifest)
    digest = str(root_art).removeprefix("art-")
    write(root / "artifacts/sha256" / digest[:2] / digest[2:], root_manifest)
    system = SystemGeneration.create(
        parent_generation_id=None,
        root_identity=RootIdentity(
            f"btrfs-uuid:{CURRENT_ROOT}",
            f"uuid:{FSUUID}",
            hashlib.sha256(root_manifest).hexdigest(),
        ),
        kernel_generation_id=kernel.kernel_generation_id,
        package_set_identity="pkg-" + "4" * 64,
        transaction_id=native_tx,
        provenance_id=provenance,
        artifact_ids=(root_art,),
        trust_state=TrustState.VERIFIED,
    )
    write(
        root / "manifests/system" / f"{system.generation_id}.json",
        (system.canonical_manifest() + "\n").encode(),
    )
    write(
        root / "manifests/kernel" / f"{kernel.kernel_generation_id}.json",
        (kernel.canonical_manifest() + "\n").encode(),
    )
    compatibility = CompatibilityEvidence(
        system_generation_id=system.generation_id,
        kernel_generation_id=kernel.kernel_generation_id,
        root_manifest_sha256=system.root_identity.root_manifest_sha256,
        filesystem_identity=system.root_identity.filesystem_identity,
        kernel_abi=kernel.kernel_abi,
        modules_abi=kernel.modules_abi,
        verifier_identity="fixture-current",
        independently_verified=True,
    )
    compatibility_payload = {
        "schema_version": 1,
        "system_generation_id": str(compatibility.system_generation_id),
        "kernel_generation_id": str(compatibility.kernel_generation_id),
        "root_manifest_sha256": compatibility.root_manifest_sha256,
        "filesystem_identity": compatibility.filesystem_identity,
        "kernel_abi": compatibility.kernel_abi,
        "modules_abi": compatibility.modules_abi,
        "verifier_identity": compatibility.verifier_identity,
        "independently_verified": True,
    }
    write(
        root / "evidence/compatibility" /
        f"{system.generation_id}--{kernel.kernel_generation_id}.json",
        canonical_bytes(compatibility_payload) + b"\n",
    )
    boot = {
        "/boot/vmlinuz-linux-cachyos": "5" * 64,
        "/boot/initramfs-linux-cachyos.img": "6" * 64,
    }
    publication = {
        "schema_version": 1,
        "kind": "maho-live-generation-publication",
        "system_generation_id": str(system.generation_id),
        "kernel_generation_id": str(kernel.kernel_generation_id),
        "transaction_id": "upd-20260901T000000Z-111111111111",
        "native_transaction_id": str(native_tx),
        "source_revision": SOURCE,
        "publisher_source_revision": SOURCE,
        "package_generation_id": "pkg-" + "4" * 64,
        "filesystem_uuid": FSUUID,
        "root_subvolume_uuid": CURRENT_ROOT,
        "fsroot": "/@",
        "running_kernel": kernel.kernel_abi,
        "cmdline_sha256": hashlib.sha256(b"quiet rw").hexdigest(),
        "boot_sha256": boot,
        "root_manifest_artifact_id": str(root_art),
        "recovery_generation_id": "g3-fixture",
        "previous_root_uuid": "99999999-9999-9999-9999-999999999999",
        "previous_root_read_only": True,
    }
    publication["publication_id"] = str(
        ArtifactID.from_content(canonical_bytes(publication))
    )
    write(root / "live.json", canonical_bytes(publication) + b"\n")
    assert read_live_publication(root) is not None
    return system, kernel, publication


def pending_transaction() -> dict:
    tx = create_transaction(
        transaction_id=TXID,
        source_revision=SOURCE,
        packages=[{
            "name": "demo",
            "installed_version": "1",
            "candidate_version": "2",
            "repository": "core",
            "download_size": 1,
            "installed_size": 1,
            "security_relevant": False,
            "roles": [],
        }],
        activation_requirements=[],
        recovery_generation_id=None,
        now=NOW,
    )
    for state in (
        UpdateState.STAGED,
        UpdateState.PREPARED,
        UpdateState.MAINTENANCE_READY,
        UpdateState.INSTALLING,
        UpdateState.INSTALLED_PENDING_ACTIVATION,
    ):
        tx = transition_transaction(tx, state, now=NOW)
    return tx


class CandidateGenerationContracts(unittest.TestCase):
    def test_normal_candidate_publication_is_unknown_and_does_not_replace_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_system, current_kernel, live = current_store(root)
            tx = pending_transaction()
            candidate = {
                "uuid": CANDIDATE_ROOT,
                "filesystem_uuid": FSUUID,
                "parent_root_uuid": CURRENT_ROOT,
            }
            authority = {
                "authority_id": "art-" + "a" * 64,
                "graph_id": "art-" + "b" * 64,
            }
            recovery = {
                "ready": True,
                "generation_id": "g3-fixture",
                "current_system_generation_id": str(current_system.generation_id),
            }
            boot_identity = {
                "unchanged": True,
                "sha256": dict(live["boot_sha256"]),
                "cmdline_sha256": live["cmdline_sha256"],
            }
            publication = publish_normal_candidate_generation(
                tx,
                candidate=candidate,
                activation_authority=authority,
                recovery_evidence=recovery,
                candidate_boot_identity=boot_identity,
                root=root,
            )
            observed = read_candidate_publication(TXID, root)
            self.assertIsNotNone(observed)
            self.assertEqual(observed["trust_state"], "UNKNOWN")
            self.assertEqual(observed["parent_system_generation_id"], str(current_system.generation_id))
            self.assertEqual(observed["kernel_generation_id"], str(current_kernel.kernel_generation_id))
            self.assertFalse(observed["kernel_generation_changed"])
            self.assertFalse(observed["boot_generation_changed"])
            self.assertEqual(
                read_live_publication(root)["system_generation_id"],
                live["system_generation_id"],
            )
            manifest = SystemGeneration.parse(json.loads((
                root / "manifests/system" / f"{publication['system_generation_id']}.json"
            ).read_text()))
            self.assertIs(manifest.trust_state, TrustState.UNKNOWN)

    def test_candidate_parent_must_be_current_verified_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_system, _kernel, live = current_store(root)
            tx = pending_transaction()
            with self.assertRaisesRegex(ValueError, "parent root"):
                publish_normal_candidate_generation(
                    tx,
                    candidate={
                        "uuid": CANDIDATE_ROOT,
                        "filesystem_uuid": FSUUID,
                        "parent_root_uuid": "88888888-8888-8888-8888-888888888888",
                    },
                    activation_authority={"authority_id": "art-" + "a" * 64},
                    recovery_evidence={
                        "ready": True,
                        "current_system_generation_id": str(current_system.generation_id),
                    },
                    candidate_boot_identity={
                        "unchanged": True,
                        "sha256": dict(live["boot_sha256"]),
                    },
                    root=root,
                )

    def test_postboot_success_promotes_same_system_identity_to_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_system, current_kernel, live = current_store(root)
            tx = pending_transaction()
            candidate = {
                "uuid": CANDIDATE_ROOT,
                "filesystem_uuid": FSUUID,
                "parent_root_uuid": CURRENT_ROOT,
            }
            recovery = {
                "ready": True,
                "generation_id": "g3-fixture",
                "current_system_generation_id": str(current_system.generation_id),
            }
            boot_identity = {
                "unchanged": True,
                "sha256": dict(live["boot_sha256"]),
                "cmdline_sha256": live["cmdline_sha256"],
            }
            candidate_pub = publish_normal_candidate_generation(
                tx,
                candidate=candidate,
                activation_authority={
                    "authority_id": "art-" + "a" * 64,
                    "graph_id": "art-" + "b" * 64,
                },
                recovery_evidence=recovery,
                candidate_boot_identity=boot_identity,
                root=root,
            )
            verifying = transition_transaction(tx, UpdateState.ACTIVE_VERIFYING, now=NOW)
            healthy = transition_transaction(
                verifying,
                UpdateState.HEALTHY,
                evidence={"ok": True, "root_uuid": CANDIDATE_ROOT},
                now=NOW,
            )
            promoted = promote_normal_candidate_generation(
                healthy,
                live_root_uuid=CANDIDATE_ROOT,
                filesystem_uuid=FSUUID,
                running_kernel_abi=current_kernel.kernel_abi,
                package_versions={"demo": "2"},
                boot_sha256=live["boot_sha256"],
                verifier_identity="maho-normal-postboot-fixture",
                root=root,
            )
            replayed = promote_normal_candidate_generation(
                healthy,
                live_root_uuid=CANDIDATE_ROOT,
                filesystem_uuid=FSUUID,
                running_kernel_abi=current_kernel.kernel_abi,
                package_versions={"demo": "2"},
                boot_sha256=live["boot_sha256"],
                verifier_identity="maho-normal-postboot-fixture",
                root=root,
            )
            self.assertEqual(
                promoted["system_generation_id"],
                candidate_pub["system_generation_id"],
            )
            self.assertEqual(replayed, promoted)
            verified = read_live_publication(root)
            self.assertIsNotNone(verified)
            self.assertEqual(
                verified["system_generation_id"],
                candidate_pub["system_generation_id"],
            )
            manifest = SystemGeneration.parse(json.loads((
                root / "manifests/system" / f"{candidate_pub['system_generation_id']}.json"
            ).read_text()))
            self.assertIs(manifest.trust_state, TrustState.VERIFIED)

    def test_partial_generation_promotion_replays_after_verified_manifest_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current_system, current_kernel, live = current_store(root)
            tx = pending_transaction()
            candidate = {
                "uuid": CANDIDATE_ROOT,
                "filesystem_uuid": FSUUID,
                "parent_root_uuid": CURRENT_ROOT,
            }
            recovery = {
                "ready": True,
                "generation_id": "g3-fixture",
                "current_system_generation_id": str(current_system.generation_id),
            }
            boot_identity = {
                "unchanged": True,
                "sha256": dict(live["boot_sha256"]),
                "cmdline_sha256": live["cmdline_sha256"],
            }
            candidate_pub = publish_normal_candidate_generation(
                tx,
                candidate=candidate,
                activation_authority={
                    "authority_id": "art-" + "a" * 64,
                    "graph_id": "art-" + "b" * 64,
                },
                recovery_evidence=recovery,
                candidate_boot_identity=boot_identity,
                root=root,
            )
            healthy = transition_transaction(
                transition_transaction(tx, UpdateState.ACTIVE_VERIFYING, now=NOW),
                UpdateState.HEALTHY,
                evidence={"ok": True, "root_uuid": CANDIDATE_ROOT},
                now=NOW,
            )
            real_write = candidate_generation._write_atomic
            writes = 0

            def interrupt_after_verified_manifest(path, data, mode=0o644):
                nonlocal writes
                writes += 1
                if writes == 2:
                    raise RuntimeError("fixture promotion interruption")
                return real_write(path, data, mode)

            with patch.object(
                candidate_generation,
                "_write_atomic",
                side_effect=interrupt_after_verified_manifest,
            ):
                with self.assertRaisesRegex(RuntimeError, "promotion interruption"):
                    promote_normal_candidate_generation(
                        healthy,
                        live_root_uuid=CANDIDATE_ROOT,
                        filesystem_uuid=FSUUID,
                        running_kernel_abi=current_kernel.kernel_abi,
                        package_versions={"demo": "2"},
                        boot_sha256=live["boot_sha256"],
                        verifier_identity="maho-normal-postboot-fixture",
                        root=root,
                    )
            manifest = SystemGeneration.parse(json.loads((
                root / "manifests/system" / f"{candidate_pub['system_generation_id']}.json"
            ).read_text()))
            self.assertIs(manifest.trust_state, TrustState.VERIFIED)
            self.assertEqual(
                read_live_publication(root)["system_generation_id"],
                live["system_generation_id"],
            )
            replayed = promote_normal_candidate_generation(
                healthy,
                live_root_uuid=CANDIDATE_ROOT,
                filesystem_uuid=FSUUID,
                running_kernel_abi=current_kernel.kernel_abi,
                package_versions={"demo": "2"},
                boot_sha256=live["boot_sha256"],
                verifier_identity="maho-normal-postboot-fixture",
                root=root,
            )
            self.assertEqual(
                replayed["system_generation_id"],
                candidate_pub["system_generation_id"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
