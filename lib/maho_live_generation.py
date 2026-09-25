#!/usr/bin/env python3
"""Publish and verify the first live, transaction-backed Maho generations.

Publication is deliberately postboot-only.  A HEALTHY M4B transaction and its
verified campaign journal are the authority; older recovery snapshots are not
promoted into an invented parent lineage.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
from typing import Any, Mapping, Sequence

from maho_generation_v2 import RootIdentity, SystemGeneration
from maho_kernel_generation import CompatibilityEvidence, KernelGeneration, can_boot, modules_tree_artifact
from maho_trust_identity import (
    ArtifactID, ProvenanceID, TransactionID, TrustState, canonical_bytes,
)
from maho_update_state import UpdateState, validate_transaction


GENERATION_ROOT = Path("/var/lib/maho/generations")


@dataclass(frozen=True)
class LiveGenerationObservation:
    filesystem_uuid: str
    root_subvolume_uuid: str
    fsroot: str
    running_kernel: str
    cmdline: str
    package_versions: Mapping[str, str]
    boot_artifacts: Mapping[str, bytes]
    module_artifacts: Mapping[str, bytes]
    dkms_artifacts: Mapping[str, bytes]
    runtime_source_revision: str
    runtime_content_sha256: str
    home_identity: Mapping[str, str]
    recovery_generation_id: str
    previous_root_uuid: str
    previous_root_read_only: bool


def certification_confirmation(transaction_id: str, candidate_uuid: str) -> str:
    return f"CERTIFY-M4B:{transaction_id}:{candidate_uuid}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_bytes(dict(value))


def _write_atomic(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o755)
    if path.is_symlink():
        raise ValueError("generation evidence path cannot be a symlink")
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _artifact(store: Path, data: bytes) -> ArtifactID:
    identity = ArtifactID.from_content(data)
    digest = str(identity).removeprefix("art-")
    path = store / "sha256" / digest[:2] / digest[2:]
    if path.is_file():
        if path.read_bytes() != data:
            raise ValueError("content-addressed generation store collision")
    else:
        _write_atomic(path, data)
    return identity


def _history_evidence(transaction: Mapping[str, Any]) -> Mapping[str, Any]:
    for event in reversed(transaction["history"]):
        if event.get("state") == UpdateState.HEALTHY.value and isinstance(event.get("evidence"), Mapping):
            return event["evidence"]
    raise ValueError("HEALTHY transaction has no activation evidence")


def publish_live_generations(
    transaction: Mapping[str, Any], journal: Mapping[str, Any], receipt: Mapping[str, Any],
    observation: LiveGenerationObservation, *, publisher_source_revision: str,
    root: Path = GENERATION_ROOT,
) -> dict[str, Any]:
    tx = validate_transaction(transaction)
    txid = tx["transaction_id"]
    generation = tx["package_generation"]
    if tx["state"] != UpdateState.HEALTHY.value or tx["blockers"]:
        raise ValueError("generation publication requires an unblocked HEALTHY transaction")
    if tx["activation"]["native_execution_certified"] is not True or tx["recovery"]["native_l3_certified"] is not True:
        raise ValueError("generation publication requires durable native M4B authority")
    if journal.get("phase") != "verified" or journal.get("transaction_state") != UpdateState.HEALTHY.value:
        raise ValueError("generation publication requires a verified M4B campaign")
    if journal.get("transaction_id") != txid or journal.get("source_revision") != tx["source_revision"]:
        raise ValueError("campaign and transaction authority do not match")
    if any(receipt.get(key) != expected for key, expected in (
        ("transaction_id", txid), ("state", UpdateState.HEALTHY.value),
        ("source_revision", tx["source_revision"]),
        ("package_generation_id", generation["id"]),
    )):
        raise ValueError("HEALTHY receipt does not match the transaction")
    candidate = journal.get("candidate")
    activation = journal.get("activation")
    expected_versions = journal.get("expected_versions")
    if not all(isinstance(item, Mapping) for item in (candidate, activation, expected_versions)):
        raise ValueError("campaign activation evidence is incomplete")
    assert isinstance(candidate, Mapping) and isinstance(activation, Mapping) and isinstance(expected_versions, Mapping)
    if observation.fsroot != "/@" or observation.root_subvolume_uuid != candidate.get("uuid"):
        raise ValueError("live root is not the exact promoted candidate")
    if observation.package_versions != expected_versions:
        raise ValueError("live package generation does not match the campaign")
    primary = str(expected_versions.get("linux-cachyos", ""))
    if observation.running_kernel != f"{primary}-cachyos":
        raise ValueError("running Primary kernel does not match the transaction")
    expected_boot = activation.get("boot_sha256")
    if not isinstance(expected_boot, Mapping) or {
        path: _sha256(content) for path, content in observation.boot_artifacts.items()
    } != expected_boot:
        raise ValueError("live boot artifacts do not match activation evidence")
    if observation.runtime_source_revision != tx["source_revision"]:
        raise ValueError("live Maho runtime source does not match the certified transaction")
    if observation.home_identity != journal.get("home_identity"):
        raise ValueError("/home identity changed after activation")
    l3_seed = journal.get("l3_seed")
    if not isinstance(l3_seed, Mapping) or observation.recovery_generation_id != l3_seed.get("generation_id"):
        raise ValueError("M3B recovery generation does not match")
    if observation.previous_root_uuid != activation.get("previous_root_uuid") or not observation.previous_root_read_only:
        raise ValueError("previous root backup is absent or mutable")
    health = _history_evidence(tx)
    if health.get("ok") is not True or health.get("root_uuid") != candidate.get("uuid"):
        raise ValueError("transaction health evidence does not prove the live candidate")

    store = root / "artifacts"
    boot_ids = {path: _artifact(store, content) for path, content in observation.boot_artifacts.items()}
    module_ids = {path: ArtifactID.from_content(content) for path, content in observation.module_artifacts.items()}
    modules_tree_id, modules_manifest = modules_tree_artifact(module_ids)
    if _artifact(store, modules_manifest) != modules_tree_id:
        raise ValueError("modules-tree artifact identity changed")
    dkms_ids = tuple(sorted(ArtifactID.from_content(content) for content in observation.dkms_artifacts.values()))
    if not dkms_ids:
        raise ValueError("certified NVIDIA/DKMS output is missing")
    microcode_ids = tuple(
        identity for path, identity in sorted(boot_ids.items()) if path.endswith("-ucode.img")
    )
    if not microcode_ids:
        raise ValueError("certified microcode artifact is missing")
    kernel_image_id = boot_ids.get("/boot/vmlinuz-linux-cachyos")
    initramfs_id = boot_ids.get("/boot/initramfs-linux-cachyos.img")
    if kernel_image_id is None or initramfs_id is None:
        raise ValueError("Primary boot artifacts are incomplete")

    native_tx = TransactionID.derive({
        "kind": "maho-update-transaction", "transaction_id": txid,
        "source_revision": tx["source_revision"], "package_generation_id": generation["id"],
    })
    provenance = ProvenanceID.derive({
        "kind": "m4b-physical-postboot-proof", "transaction_id": txid,
        "source_revision": tx["source_revision"],
        "frozen_admission_evidence_id": (journal.get("frozen_admission") or {}).get("evidence_id"),
        "activation_authority_id": (journal.get("activation_authority") or {}).get("authority_id"),
        "publisher_source_revision": publisher_source_revision,
    })
    provider = f"linux-cachyos={primary};linux-cachyos-headers={expected_versions.get('linux-cachyos-headers')}"
    kernel = KernelGeneration.create(
        parent_kernel_generation_id=None,
        kernel_image_id=kernel_image_id, initramfs_id=initramfs_id,
        modules_tree_id=modules_tree_id, dkms_output_ids=dkms_ids,
        microcode_ids=microcode_ids, cmdline_contract=observation.cmdline,
        package_provider_identity=provider, provenance_id=provenance,
        transaction_id=native_tx, kernel_abi=observation.running_kernel,
        modules_abi=observation.running_kernel, trust_state=TrustState.VERIFIED,
    )
    root_manifest = {
        "schema_version": 1, "kind": "maho-live-root-proof",
        "transaction_id": txid, "native_transaction_id": str(native_tx),
        "source_revision": tx["source_revision"], "package_generation_id": generation["id"],
        "filesystem_uuid": observation.filesystem_uuid,
        "root_subvolume_uuid": observation.root_subvolume_uuid,
        "admission_graph_id": (journal.get("frozen_admission") or {}).get("graph_id"),
        "frozen_admission_evidence_id": (journal.get("frozen_admission") or {}).get("evidence_id"),
        "activation_authority_id": (journal.get("activation_authority") or {}).get("authority_id"),
        "runtime_source_revision": observation.runtime_source_revision,
        "runtime_content_sha256": observation.runtime_content_sha256,
        "boot_sha256": dict(sorted(expected_boot.items())),
        "recovery_generation_id": observation.recovery_generation_id,
        "previous_root_uuid": observation.previous_root_uuid,
        "previous_root_read_only": True,
        "receipt_sha256": _sha256(_json_bytes(receipt)),
    }
    root_manifest_bytes = _json_bytes(root_manifest)
    root_artifact = _artifact(store, root_manifest_bytes)
    system_artifacts = tuple(sorted({
        root_artifact, *boot_ids.values(), modules_tree_id, *dkms_ids,
        ArtifactID(str(root_manifest["admission_graph_id"])),
        ArtifactID(str(root_manifest["frozen_admission_evidence_id"])),
        ArtifactID(str(root_manifest["activation_authority_id"])),
    }))
    system = SystemGeneration.create(
        parent_generation_id=None,
        root_identity=RootIdentity(
            f"btrfs-uuid:{observation.root_subvolume_uuid}",
            f"uuid:{observation.filesystem_uuid}", _sha256(root_manifest_bytes),
        ),
        kernel_generation_id=kernel.kernel_generation_id,
        package_set_identity=generation["id"], transaction_id=native_tx,
        provenance_id=provenance, artifact_ids=system_artifacts,
        trust_state=TrustState.VERIFIED,
    )
    compatibility = CompatibilityEvidence(
        system_generation_id=system.generation_id,
        kernel_generation_id=kernel.kernel_generation_id,
        root_manifest_sha256=system.root_identity.root_manifest_sha256,
        filesystem_identity=system.root_identity.filesystem_identity,
        kernel_abi=kernel.kernel_abi, modules_abi=kernel.modules_abi,
        verifier_identity=f"maho-m4b-postboot:{publisher_source_revision}",
        independently_verified=True,
    )
    compatibility_payload = {
        "schema_version": 1, **compatibility.__dict__,
        "system_generation_id": str(compatibility.system_generation_id),
        "kernel_generation_id": str(compatibility.kernel_generation_id),
    }
    publication = {
        "schema_version": 1, "kind": "maho-live-generation-publication",
        "system_generation_id": str(system.generation_id),
        "kernel_generation_id": str(kernel.kernel_generation_id),
        "transaction_id": txid, "native_transaction_id": str(native_tx),
        "source_revision": tx["source_revision"],
        "publisher_source_revision": publisher_source_revision,
        "package_generation_id": generation["id"],
        "filesystem_uuid": observation.filesystem_uuid,
        "root_subvolume_uuid": observation.root_subvolume_uuid,
        "fsroot": observation.fsroot, "running_kernel": observation.running_kernel,
        "cmdline_sha256": _sha256(observation.cmdline.encode()),
        "boot_sha256": dict(sorted(expected_boot.items())),
        "root_manifest_artifact_id": str(root_artifact),
        "recovery_generation_id": observation.recovery_generation_id,
        "previous_root_uuid": observation.previous_root_uuid,
        "previous_root_read_only": True,
    }
    publication["publication_id"] = str(ArtifactID.from_content(_json_bytes(publication)))
    _write_atomic(root / "manifests/system" / f"{system.generation_id}.json", (system.canonical_manifest() + "\n").encode())
    _write_atomic(root / "manifests/kernel" / f"{kernel.kernel_generation_id}.json", (kernel.canonical_manifest() + "\n").encode())
    _write_atomic(root / "evidence/compatibility" / f"{system.generation_id}--{kernel.kernel_generation_id}.json", _json_bytes(compatibility_payload) + b"\n")
    _write_atomic(root / "publications" / f"{txid}.json", _json_bytes(publication) + b"\n")
    _write_atomic(root / "live.json", _json_bytes(publication) + b"\n")
    return publication


def _run(command: Sequence[str]) -> str:
    result = subprocess.run(list(command), check=False, text=True, capture_output=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    if result.returncode != 0:
        raise RuntimeError(f"live generation observation failed: {' '.join(command)}: {result.stderr.strip()}")
    return result.stdout


def observe_live_generation(
    *, expected_versions: Mapping[str, str], boot_paths: Sequence[str], runtime_source_revision: str,
    runtime_content_sha256: str, home_identity: Mapping[str, str], recovery_generation_id: str,
    previous_root_uuid: str, previous_root_read_only: bool,
) -> LiveGenerationObservation:
    mount = json.loads(_run(("findmnt", "--json", "--target", "/", "--output", "TARGET,SOURCE,FSTYPE,FSROOT,UUID")))["filesystems"][0]
    shown = _run(("btrfs", "subvolume", "show", "/"))
    root_uuid = next((line.split(":", 1)[1].strip() for line in shown.splitlines() if line.strip().startswith("UUID:")), "")
    names = sorted(expected_versions)
    packages = _run(("pacman", "-Q", *names))
    observed_versions = dict(line.split(" ", 1) for line in packages.splitlines() if " " in line)
    running = os.uname().release
    modules = Path("/usr/lib/modules") / running
    module_artifacts: dict[str, bytes] = {}
    dkms_artifacts: dict[str, bytes] = {}
    for path in sorted(modules.rglob("*")):
        if path.is_symlink():
            content = f"symlink:{os.readlink(path)}".encode()
        elif path.is_file():
            content = path.read_bytes()
        else:
            continue
        relative = str(path.relative_to(modules))
        module_artifacts[relative] = content
        if relative.startswith("updates/dkms/"):
            dkms_artifacts[relative] = content
    return LiveGenerationObservation(
        filesystem_uuid=str(mount.get("uuid", "")), root_subvolume_uuid=root_uuid,
        fsroot=str(mount.get("fsroot", "")), running_kernel=running,
        cmdline=Path("/proc/cmdline").read_text(encoding="utf-8").strip(),
        package_versions=observed_versions,
        boot_artifacts={path: Path(path).read_bytes() for path in boot_paths},
        module_artifacts=module_artifacts, dkms_artifacts=dkms_artifacts,
        runtime_source_revision=runtime_source_revision,
        runtime_content_sha256=runtime_content_sha256, home_identity=dict(home_identity),
        recovery_generation_id=recovery_generation_id,
        previous_root_uuid=previous_root_uuid, previous_root_read_only=previous_root_read_only,
    )


def read_live_publication(root: Path = GENERATION_ROOT) -> dict[str, Any] | None:
    path = root / "live.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("kind") != "maho-live-generation-publication":
        return None
    claimed = value.get("publication_id")
    material = dict(value)
    material.pop("publication_id", None)
    if claimed != str(ArtifactID.from_content(_json_bytes(material))):
        return None
    try:
        system = json.loads((root / "manifests/system" / f"{value['system_generation_id']}.json").read_text())
        kernel = json.loads((root / "manifests/kernel" / f"{value['kernel_generation_id']}.json").read_text())
        compatibility_value = json.loads((
            root / "evidence/compatibility" /
            f"{value['system_generation_id']}--{value['kernel_generation_id']}.json"
        ).read_text())
        parsed_system = SystemGeneration.parse(system)
        parsed_kernel = KernelGeneration.parse(kernel)
        compatibility = CompatibilityEvidence(
            system_generation_id=parsed_system.generation_id,
            kernel_generation_id=parsed_kernel.kernel_generation_id,
            root_manifest_sha256=str(compatibility_value["root_manifest_sha256"]),
            filesystem_identity=str(compatibility_value["filesystem_identity"]),
            kernel_abi=str(compatibility_value["kernel_abi"]),
            modules_abi=str(compatibility_value["modules_abi"]),
            verifier_identity=str(compatibility_value["verifier_identity"]),
            independently_verified=compatibility_value["independently_verified"] is True,
        )
    except (KeyError, OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    if str(parsed_system.generation_id) != value.get("system_generation_id") or str(parsed_kernel.kernel_generation_id) != value.get("kernel_generation_id"):
        return None
    if parsed_system.kernel_generation_id != parsed_kernel.kernel_generation_id or parsed_system.trust_state is not TrustState.VERIFIED or parsed_kernel.trust_state is not TrustState.VERIFIED or not can_boot(parsed_kernel, parsed_system, compatibility):
        return None
    try:
        root_artifact = ArtifactID(str(value.get("root_manifest_artifact_id", "")))
    except ValueError:
        return None
    digest = str(root_artifact).removeprefix("art-")
    try:
        root_manifest = (root / "artifacts/sha256" / digest[:2] / digest[2:]).read_bytes()
    except OSError:
        return None
    if ArtifactID.from_content(root_manifest) != root_artifact or hashlib.sha256(root_manifest).hexdigest() != parsed_system.root_identity.root_manifest_sha256:
        return None
    return value
