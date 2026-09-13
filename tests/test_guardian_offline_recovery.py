#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_offline_recovery import (  # noqa: E402
    DirectoryRecoveryProvider, RecoveryEnvironmentEvidence, plan_offline_recovery,
)
from maho_generation_v2 import RootIdentity, SystemGeneration  # noqa: E402
from maho_kernel_generation import CompatibilityEvidence, ContentAddressedArtifactStore, KernelGeneration, modules_tree_artifact  # noqa: E402
from maho_trust_identity import ArtifactID, ProvenanceID, TransactionID, TrustState  # noqa: E402


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


PROV = ProvenanceID.derive({"offline": "fixture"})
TX_OLD = TransactionID.derive({"offline": 1})
TX_NEW = TransactionID.derive({"offline": 2})
FILESYSTEM = "uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def make_fixture(root: pathlib.Path, current_kernel_trust: TrustState, *, all_system_unknown=False):
    payloads = {
        "kernel-old": b"kernel-old", "initramfs-old": b"initramfs-old",
        "kernel-new": b"kernel-new", "initramfs-new": b"initramfs-new",
        "module": b"module", "microcode": b"microcode",
    }
    ids = {name: ArtifactID.from_content(value) for name, value in payloads.items()}
    modules_id, modules_payload = modules_tree_artifact({"kernel/demo.ko": ids["module"]})
    old_kernel = KernelGeneration.create(
        parent_kernel_generation_id=None, kernel_image_id=ids["kernel-old"],
        initramfs_id=ids["initramfs-old"], modules_tree_id=modules_id,
        dkms_output_ids=(ids["module"],), microcode_ids=(ids["microcode"],),
        cmdline_contract="root=UUID=test ro", package_provider_identity="core/linux-lts",
        provenance_id=PROV, transaction_id=TX_OLD, kernel_abi="abi-old", modules_abi="abi-old",
        trust_state=TrustState.VERIFIED,
    )
    new_kernel = KernelGeneration.create(
        parent_kernel_generation_id=old_kernel.kernel_generation_id,
        kernel_image_id=ids["kernel-new"], initramfs_id=ids["initramfs-new"],
        modules_tree_id=modules_id, dkms_output_ids=(ids["module"],), microcode_ids=(ids["microcode"],),
        cmdline_contract="root=UUID=test ro", package_provider_identity="core/linux",
        provenance_id=PROV, transaction_id=TX_NEW, kernel_abi="abi-new", modules_abi="abi-new",
        trust_state=current_kernel_trust,
    )
    old_system = SystemGeneration.create(
        parent_generation_id=None,
        root_identity=RootIdentity("snapper:root:209", FILESYSTEM, "1" * 64),
        kernel_generation_id=old_kernel.kernel_generation_id, package_set_identity="pkg-" + "1" * 64,
        transaction_id=TX_OLD, provenance_id=PROV, artifact_ids=(ids["kernel-old"],),
        trust_state=TrustState.UNKNOWN if all_system_unknown else TrustState.VERIFIED,
    )
    new_system = SystemGeneration.create(
        parent_generation_id=old_system.generation_id,
        root_identity=RootIdentity("snapper:root:210", FILESYSTEM, "2" * 64),
        kernel_generation_id=new_kernel.kernel_generation_id, package_set_identity="pkg-" + "2" * 64,
        transaction_id=TX_NEW, provenance_id=PROV, artifact_ids=(ids["kernel-new"],),
        trust_state=TrustState.UNKNOWN if all_system_unknown else TrustState.VERIFIED,
    )
    for directory in ("manifests/system", "manifests/kernel", "evidence/compatibility"):
        (root / directory).mkdir(parents=True)
    for item in (old_system, new_system):
        (root / "manifests/system" / f"{item.generation_id}.json").write_text(item.canonical_manifest(), encoding="utf-8")
    for item in (old_kernel, new_kernel):
        (root / "manifests/kernel" / f"{item.kernel_generation_id}.json").write_text(item.canonical_manifest(), encoding="utf-8")
    for index, (system, kernel) in enumerate(((old_system, old_kernel), (new_system, new_kernel))):
        evidence = CompatibilityEvidence(
            system.generation_id, kernel.kernel_generation_id,
            system.root_identity.root_manifest_sha256, FILESYSTEM,
            kernel.kernel_abi, kernel.modules_abi, "guardian-recovery-fixture", True,
        )
        value = evidence.__dict__ | {
            "system_generation_id": str(evidence.system_generation_id),
            "kernel_generation_id": str(evidence.kernel_generation_id),
        }
        (root / "evidence/compatibility" / f"pair-{index}.json").write_text(json.dumps(value), encoding="utf-8")
    store = ContentAddressedArtifactStore(root / "artifacts")
    for value in payloads.values():
        store.put(value)
    store.put(modules_payload)
    return old_system, new_system, old_kernel, new_kernel


def environment(**changes):
    values = {
        "environment_id": "guardian-recovery:fixture", "trust_state": TrustState.VERIFIED,
        "manifest_verified": True, "verification_authority": "maho-release-authority:fixture",
        "verification_kernel_id": "recovery-kernel:independent", "revocation_metadata_fresh": True,
    }
    values.update(changes)
    return RecoveryEnvironmentEvidence(**values)


for state in (TrustState.VERIFIED, TrustState.UNKNOWN, TrustState.REVOKED):
    with tempfile.TemporaryDirectory() as td:
        old_system, new_system, old_kernel, new_kernel = make_fixture(pathlib.Path(td), state)
        plan = plan_offline_recovery(
            DirectoryRecoveryProvider(td), environment(),
            current_system_generation_id=new_system.generation_id,
            suspected_running_kernel_id=new_kernel.kernel_generation_id, incident_id=f"inc-{state.value.lower()}",
        )
        expected = new_system if state is TrustState.VERIFIED else old_system
        check(f"current kernel {state.value} selects newest independently trusted pair", plan.eligible and plan.target_system_generation_id == expected.generation_id)
        check(f"current kernel {state.value} plan remains source-only and reboot-gated", plan.source_only and plan.requires_reboot and plan.operations[-1] == "request-reboot")

with tempfile.TemporaryDirectory() as td:
    old_system, new_system, old_kernel, new_kernel = make_fixture(pathlib.Path(td), TrustState.VERIFIED, all_system_unknown=True)
    plan = plan_offline_recovery(DirectoryRecoveryProvider(td), environment(), current_system_generation_id=new_system.generation_id, suspected_running_kernel_id=new_kernel.kernel_generation_id, incident_id="inc-all-untrusted")
    check("all local generations untrusted requires external recovery", not plan.eligible and "no_independently_trusted_compatible_pair" in plan.reasons)

with tempfile.TemporaryDirectory() as td:
    old_system, new_system, old_kernel, new_kernel = make_fixture(pathlib.Path(td), TrustState.VERIFIED)
    provider = DirectoryRecoveryProvider(td)
    common = dict(current_system_generation_id=new_system.generation_id, suspected_running_kernel_id=new_kernel.kernel_generation_id, incident_id="inc-env")
    unverified = plan_offline_recovery(provider, environment(manifest_verified=False), **common)
    check("unverifiable recovery environment refuses", "recovery_environment_manifest_unverified" in unverified.reasons)
    stale = plan_offline_recovery(provider, environment(revocation_metadata_fresh=False), **common)
    check("stale revocation metadata refuses", "revocation_metadata_stale" in stale.reasons)
    self_certifying = plan_offline_recovery(provider, environment(verification_kernel_id=str(new_kernel.kernel_generation_id)), **common)
    check("suspected running kernel cannot certify itself", "suspected_kernel_cannot_certify_itself" in self_certifying.reasons)
    manifest_path = next((pathlib.Path(td) / "manifests/kernel").glob("*.json"))
    manifest_path.write_text("{broken", encoding="utf-8")
    malformed = plan_offline_recovery(provider, environment(), **common)
    check("malformed recovery manifest fails closed", not malformed.eligible and "provider_evidence_invalid" in malformed.reasons)

print("ALL GUARDIAN OFFLINE RECOVERY CONTRACT TESTS PASS")
