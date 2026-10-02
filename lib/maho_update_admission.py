#!/usr/bin/env python3
"""Production Native Admission binding for Maho update candidates.

This module does not install packages or activate roots. It translates one exact
Maho update transaction into Native Admission evidence, then wraps the resulting
ALLOW authority in a durable activation handoff bound to the update transaction,
package generation, candidate root, mutation graph, runtime evidence, and source.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from guardian_admission import AdmissionOutcome, CandidateDeclaration, EffectKind, MutationGraph
from guardian_native_admission import (
    CandidateRoots,
    NativeAdmissionError,
    NativeInspection,
    NativeAdmissionResult,
    PromotionAuthority,
    RuntimeListenerEvidence,
    approve_persisted_admission,
    admit_candidate,
    package_ownership,
    revalidate_promotion_authority,
    root_identity,
    verify_persisted_admission_authority,
)
from maho_trust_identity import ArtifactID, TransactionID, canonical_bytes
from maho_boot_authority import BootAuthority, BootGeneration
from maho_update_state import validate_transaction
from maho_update_transaction import ExecutionPlan

_UPDATE_TX = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
_SHA40 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_ALL_EFFECTS = tuple(EffectKind)


class ProductionAdmissionError(ValueError):
    pass


def guardian_transaction_id(update_transaction_id: str) -> TransactionID:
    if _UPDATE_TX.fullmatch(update_transaction_id) is None:
        raise ProductionAdmissionError("update_transaction_identity_invalid")
    return TransactionID.derive({"kind": "maho-update", "transaction_id": update_transaction_id})


def _package_generation(transaction: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    current = validate_transaction(transaction)
    package_generation = current.get("package_generation")
    if not isinstance(package_generation, Mapping):
        raise ProductionAdmissionError("package_generation_missing")
    generation_id = package_generation.get("id")
    packages = package_generation.get("packages")
    if not isinstance(generation_id, str) or not generation_id.startswith("pkg-") or not isinstance(packages, list):
        raise ProductionAdmissionError("package_generation_invalid")
    names = tuple(sorted({str(item.get("name", "")) for item in packages if isinstance(item, Mapping)}))
    if not names or any(not item for item in names):
        raise ProductionAdmissionError("package_generation_packages_invalid")
    return generation_id, names


_MODULE_PATH = re.compile(r"^/usr/lib/modules/([^/]+)(?:/|$)")
_USR_SRC_DEBUG_PATH = re.compile(r"^/usr/src/debug/([^/]+)(?:/|$)")
_USR_SRC_PATH = re.compile(r"^/usr/src/([^/]+)(?:/|$)")
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+~-]*")
_KNOWN_CROSS_PACKAGE_OUTPUTS: Mapping[str, tuple[str, ...]] = {
    # Arch's JDK install hook advances java-runtime-common's selector symlinks.
    # Keep this exact: the rest of /usr/lib/jvm remains outside the declaration.
    "jdk-openjdk": ("/usr/lib/jvm/default", "/usr/lib/jvm/default-runtime"),
}


def _transaction_owned_paths(
    ownership: Mapping[str, str],
    package_set: set[str],
) -> set[str]:
    return {path for path, owner in ownership.items() if owner in package_set}


def _bounded_security_roots(
    ownership: Mapping[str, str],
    package_set: set[str],
) -> tuple[set[str], set[str]]:
    """Derive exact generated-parent roots from package-owned descendants."""
    module_roots: set[str] = set()
    source_roots: set[str] = set()
    for path, owner in ownership.items():
        if owner not in package_set:
            continue
        module = _MODULE_PATH.match(path)
        if module is not None:
            module_roots.add(f"/usr/lib/modules/{module.group(1)}")
            continue
        debug = _USR_SRC_DEBUG_PATH.match(path)
        if debug is not None:
            source_roots.add(f"/usr/src/debug/{debug.group(1)}")
            continue
        source = _USR_SRC_PATH.match(path)
        if source is not None and source.group(1) != "debug":
            source_roots.add(f"/usr/src/{source.group(1)}")
    return module_roots, source_roots


def _local_package_name(package_dir: Path) -> str:
    try:
        lines = (package_dir / "desc").read_text(encoding="utf-8", errors="strict").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ProductionAdmissionError("package_manifest_identity_unreadable") from exc
    names = [lines[index + 1] for index, line in enumerate(lines[:-1]) if line == "%NAME%" and lines[index + 1]]
    if len(names) != 1:
        raise ProductionAdmissionError("package_manifest_identity_invalid")
    return names[0]


def _transaction_source_directory_roots(root: Path, package_set: set[str]) -> set[str]:
    """Read exact transaction-owned /usr/src directory entries from Pacman manifests.

    Pacman's ownership projection intentionally excludes directory rows. Some
    packages, such as brave-bin, legitimately own only a package-specific debug
    directory there; removing that empty directory during an upgrade must remain
    attributable without declaring /usr/src as a whole.
    """
    database = root / "var/lib/pacman/local"
    try:
        package_dirs = sorted(item for item in database.iterdir() if item.is_dir())
    except OSError as exc:
        raise ProductionAdmissionError("package_manifest_database_unavailable") from exc
    seen: set[str] = set()
    roots: set[str] = set()
    for package_dir in package_dirs:
        name = _local_package_name(package_dir)
        if name not in package_set:
            continue
        if name in seen:
            raise ProductionAdmissionError("package_manifest_identity_ambiguous")
        seen.add(name)
        try:
            raw = (package_dir / "files").read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            raise ProductionAdmissionError("package_manifest_files_unreadable") from exc
        if raw == "":
            continue
        in_files = False
        found_files = False
        for line in raw.splitlines():
            if line == "%FILES%":
                in_files = True
                found_files = True
                continue
            if in_files and line.startswith("%") and line.endswith("%"):
                break
            if not in_files or not line or not line.endswith("/"):
                continue
            path = "/" + line.lstrip("/").rstrip("/")
            if ".." in path.split("/") or "//" in path:
                raise ProductionAdmissionError("package_manifest_directory_invalid")
            debug = _USR_SRC_DEBUG_PATH.match(path)
            if debug is not None and _SAFE_COMPONENT.fullmatch(debug.group(1)) is not None:
                roots.add(f"/usr/src/debug/{debug.group(1)}")
                continue
            source = _USR_SRC_PATH.match(path)
            if (
                source is not None
                and source.group(1) != "debug"
                and _SAFE_COMPONENT.fullmatch(source.group(1)) is not None
            ):
                roots.add(f"/usr/src/{source.group(1)}")
        if not found_files:
            raise ProductionAdmissionError("package_manifest_files_missing")
    return roots


def _kernel_boot_outputs(
    roots: CandidateRoots,
    ownership: Mapping[str, str],
    package_set: set[str],
) -> set[str]:
    """Bind mkinitcpio/kernel-install outputs to a transaction-owned pkgbase."""
    outputs: set[str] = set()
    for path, owner in ownership.items():
        if owner not in package_set or not path.endswith("/pkgbase"):
            continue
        match = _MODULE_PATH.match(path)
        if match is None:
            continue
        try:
            pkgbase = (roots.candidate_root / path.lstrip("/")).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            raise ProductionAdmissionError("candidate_kernel_pkgbase_unreadable")
        if _SAFE_COMPONENT.fullmatch(pkgbase) is None:
            raise ProductionAdmissionError("candidate_kernel_pkgbase_invalid")
        outputs.update({f"/boot/vmlinuz-{pkgbase}", f"/boot/initramfs-{pkgbase}.img"})
    return outputs


def _trusted_dkms_generated_paths(
    roots: CandidateRoots,
    module_roots: set[str],
) -> set[str]:
    """Allow DKMS rebuild state only for trusted modules and exact kernel releases."""
    releases = sorted(root.removeprefix("/usr/lib/modules/") for root in module_roots)
    if not releases:
        return set()
    dkms_root = roots.base_root / "var/lib/dkms"
    if not dkms_root.exists():
        return set()
    try:
        modules = sorted(os.scandir(dkms_root), key=lambda item: item.name)
    except OSError as exc:
        raise ProductionAdmissionError("base_dkms_state_unreadable") from exc
    arch = os.uname().machine
    if _SAFE_COMPONENT.fullmatch(arch) is None:
        raise ProductionAdmissionError("dkms_architecture_invalid")
    generated: set[str] = set()
    for module in modules:
        if not module.is_dir(follow_symlinks=False) or _SAFE_COMPONENT.fullmatch(module.name) is None:
            continue
        try:
            versions = sorted(os.scandir(module.path), key=lambda item: item.name)
        except OSError as exc:
            raise ProductionAdmissionError("base_dkms_module_state_unreadable") from exc
        for version in versions:
            if (
                version.is_symlink()
                or not version.is_dir(follow_symlinks=False)
                or _SAFE_COMPONENT.fullmatch(version.name) is None
            ):
                continue
            for release in releases:
                if _SAFE_COMPONENT.fullmatch(release) is None:
                    raise ProductionAdmissionError("kernel_release_identity_invalid")
                generated.add(f"/var/lib/dkms/{module.name}/{version.name}/{release}")
                generated.add(f"/var/lib/dkms/{module.name}/kernel-{release}-{arch}")
    return generated


def build_production_declaration(
    roots: CandidateRoots,
    transaction: Mapping[str, Any],
    plan: ExecutionPlan,
) -> CandidateDeclaration:
    """Build a bounded declaration from exact package ownership plus planned outputs."""
    generation_id, names = _package_generation(transaction)
    before_ownership, before_errors = package_ownership(roots.base_root)
    after_ownership, after_errors = package_ownership(roots.candidate_root)
    if before_errors:
        raise ProductionAdmissionError("base_package_ownership_incomplete")
    if after_errors:
        raise ProductionAdmissionError("candidate_package_ownership_incomplete")
    package_set = set(names)
    declared = _transaction_owned_paths(before_ownership, package_set)
    declared.update(_transaction_owned_paths(after_ownership, package_set))

    before_modules, before_sources = _bounded_security_roots(before_ownership, package_set)
    after_modules, after_sources = _bounded_security_roots(after_ownership, package_set)
    module_roots = before_modules | after_modules
    declared.update(module_roots)
    declared.update(before_sources | after_sources)
    declared.update(_transaction_source_directory_roots(roots.base_root, package_set))
    declared.update(_transaction_source_directory_roots(roots.candidate_root, package_set))

    # Generated outputs are admitted only when they are derivable from trusted
    # base state plus exact transaction-owned kernel identities.
    declared.update(_trusted_dkms_generated_paths(roots, module_roots))
    declared.update(_kernel_boot_outputs(roots, after_ownership, package_set))
    for package in package_set:
        declared.update(_KNOWN_CROSS_PACKAGE_OUTPUTS.get(package, ()))

    # These are package-manager/generated outputs that are expected from the
    # exact transaction but are not necessarily owned by a package database row.
    declared.update(str(path) for path in plan.boot_artifacts)
    declared.update({"/var/lib/pacman/local", "/var/log/pacman.log", "/etc/ld.so.cache"})
    if not declared:
        raise ProductionAdmissionError("candidate_declaration_empty")
    return CandidateDeclaration(
        package_identity=generation_id,
        path_prefixes=tuple(sorted(declared)),
        effect_kinds=_ALL_EFFECTS,
        package_identities=names,
    )


def build_normal_production_declaration(
    roots: CandidateRoots,
    transaction: Mapping[str, Any],
    *,
    operational_paths: Iterable[str] = (),
) -> CandidateDeclaration:
    """Declare exact normal-package ownership plus bounded transaction metadata."""
    generation_id, names = _package_generation(transaction)
    ownership, errors = package_ownership(roots.candidate_root)
    if errors:
        raise ProductionAdmissionError("candidate_package_ownership_incomplete")
    package_set = set(names)
    declared = {path for path, owner in ownership.items() if owner in package_set}
    declared.update({"/var/lib/pacman/local", "/var/log/pacman.log", "/etc/ld.so.cache"})
    for path in operational_paths:
        if not isinstance(path, str) or not path.startswith("/var/lib/maho/update/"):
            raise ProductionAdmissionError("normal_operational_path_invalid")
        declared.add(path)
    if not declared:
        raise ProductionAdmissionError("normal_candidate_declaration_empty")
    return CandidateDeclaration(
        package_identity=generation_id,
        path_prefixes=tuple(sorted(declared)),
        effect_kinds=_ALL_EFFECTS,
        package_identities=names,
    )


def evaluate_normal_production_candidate(
    roots: CandidateRoots,
    transaction: Mapping[str, Any],
    *,
    known_safe_graph_ids: Iterable[ArtifactID] = (),
    operational_paths: Iterable[str] = (),
) -> NativeAdmissionResult:
    declaration = build_normal_production_declaration(
        roots, transaction, operational_paths=operational_paths,
    )
    runtime = offline_runtime_evidence(roots)
    return admit_candidate(
        roots,
        declaration,
        runtime,
        known_safe_graph_ids=known_safe_graph_ids,
    )


def offline_runtime_evidence(roots: CandidateRoots) -> RuntimeListenerEvidence:
    """Bind the fact that the candidate remained offline during admission.

    M4B mutates an offline sysroot and starts no candidate services before
    activation. Runtime-listener evidence is therefore an exact empty set,
    explicitly bound to the immutable base/candidate roots. First-boot runtime
    health remains a separate post-activation verification boundary.
    """
    base = root_identity(roots.base_root)
    candidate = root_identity(roots.candidate_root)
    material = {
        "schema_version": 1,
        "kind": "maho-update-offline-runtime-evidence",
        "observer_identity": "maho-update-offline-observer-v1",
        "transaction_id": str(roots.transaction_id),
        "candidate_id": roots.candidate_id,
        "base_root_identity": base,
        "candidate_root_identity": candidate,
        "candidate_runtime_executed": False,
        "listeners_before": [],
        "listeners_after": [],
    }
    return RuntimeListenerEvidence(
        candidate_id=roots.candidate_id,
        transaction_id=roots.transaction_id,
        base_root_identity=base,
        candidate_root_identity=candidate,
        observer_identity="maho-update-offline-observer-v1",
        complete=True,
        isolated=True,
        before=(),
        after=(),
        evidence_sha256=ArtifactID.from_content(canonical_bytes(material)).removeprefix("art-"),
    )


def evaluate_production_candidate(
    roots: CandidateRoots,
    transaction: Mapping[str, Any],
    plan: ExecutionPlan,
    *,
    known_safe_graph_ids: Iterable[ArtifactID] = (),
) -> NativeAdmissionResult:
    declaration = build_production_declaration(roots, transaction, plan)
    runtime = offline_runtime_evidence(roots)
    return admit_candidate(
        roots,
        declaration,
        runtime,
        known_safe_graph_ids=known_safe_graph_ids,
    )


def admission_review_confirmation(update_transaction_id: str, graph_id: ArtifactID | str) -> str:
    if _UPDATE_TX.fullmatch(update_transaction_id) is None:
        raise ProductionAdmissionError("update_transaction_identity_invalid")
    graph = ArtifactID(str(graph_id))
    return f"ADMIT:{update_transaction_id}:{graph}"


@dataclass(frozen=True)
class FrozenAdmissionEvidence:
    evidence_id: ArtifactID
    update_transaction_id: str
    guardian_transaction_id: TransactionID
    candidate_id: str
    package_generation_id: str
    source_revision: str
    graph_id: ArtifactID
    candidate_btrfs_uuid: str
    base_btrfs_uuid: str
    base_root_identity: str
    candidate_root_identity: str
    runtime_evidence_sha256: str
    admission_payload_sha256: str
    candidate_boot_sha256: Mapping[str, str]

    def identity_material(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "maho-update-frozen-admission-evidence",
            "update_transaction_id": self.update_transaction_id,
            "guardian_transaction_id": str(self.guardian_transaction_id),
            "candidate_id": self.candidate_id,
            "package_generation_id": self.package_generation_id,
            "source_revision": self.source_revision,
            "graph_id": str(self.graph_id),
            "candidate_btrfs_uuid": self.candidate_btrfs_uuid,
            "base_btrfs_uuid": self.base_btrfs_uuid,
            "base_root_identity": self.base_root_identity,
            "candidate_root_identity": self.candidate_root_identity,
            "runtime_evidence_sha256": self.runtime_evidence_sha256,
            "admission_payload_sha256": self.admission_payload_sha256,
            "candidate_boot_sha256": dict(sorted(self.candidate_boot_sha256.items())),
        }

    def as_dict(self) -> dict[str, Any]:
        return self.identity_material() | {"evidence_id": str(self.evidence_id)}


@dataclass(frozen=True)
class FrozenActivationAuthority:
    authority_id: ArtifactID
    frozen_admission_evidence_id: ArtifactID
    candidate_btrfs_uuid: str
    base_btrfs_uuid: str
    activation_authority: Mapping[str, Any]

    def identity_material(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "maho-update-frozen-activation-authority",
            "authority_scope": "activate-exact-immutable-native-admitted-candidate",
            "frozen_admission_evidence_id": str(self.frozen_admission_evidence_id),
            "candidate_btrfs_uuid": self.candidate_btrfs_uuid,
            "base_btrfs_uuid": self.base_btrfs_uuid,
            "activation_authority": dict(self.activation_authority),
        }

    def as_dict(self) -> dict[str, Any]:
        return self.identity_material() | {"authority_id": str(self.authority_id)}


def freeze_admission_evidence(
    result: NativeAdmissionResult,
    *, update_transaction_id: str, transaction: Mapping[str, Any], source_revision: str,
    candidate_btrfs_uuid: str, base_btrfs_uuid: str,
    candidate_boot_sha256: Mapping[str, str],
    admission_payload: Mapping[str, Any] | None = None,
) -> FrozenAdmissionEvidence:
    generation_id, _ = _package_generation(transaction)
    if (
        _UPDATE_TX.fullmatch(update_transaction_id) is None
        or _SHA40.fullmatch(source_revision) is None
        or _UUID.fullmatch(candidate_btrfs_uuid) is None
        or _UUID.fullmatch(base_btrfs_uuid) is None
        or result.inspection.candidate_id != candidate_btrfs_uuid
        or result.decision.transaction_id != guardian_transaction_id(update_transaction_id)
        or result.decision.graph_id != result.inspection.graph.graph_id
    ):
        raise ProductionAdmissionError("frozen_admission_context_invalid")
    boot = dict(candidate_boot_sha256)
    if (
        not boot
        or any(not isinstance(path, str) or not path.startswith("/boot/") for path in boot)
        or any(not isinstance(digest, str) or _SHA256.fullmatch(digest) is None for digest in boot.values())
    ):
        raise ProductionAdmissionError("frozen_admission_boot_identity_invalid")
    payload = dict(admission_payload) if admission_payload is not None else result.as_dict()
    payload_graph = payload.get("mutation_graph")
    if (
        payload.get("candidate_id") != result.inspection.candidate_id
        or payload.get("base_root_identity") != result.inspection.base_root_identity
        or payload.get("candidate_root_identity") != result.inspection.candidate_root_identity
        or not isinstance(payload_graph, Mapping)
        or payload_graph.get("graph_id") != str(result.inspection.graph.graph_id)
        or payload.get("decision") != result.decision.as_dict()
    ):
        raise ProductionAdmissionError("frozen_admission_payload_mismatch")
    provisional = FrozenAdmissionEvidence(
        evidence_id=ArtifactID.from_content(b"placeholder"),
        update_transaction_id=update_transaction_id,
        guardian_transaction_id=result.decision.transaction_id,
        candidate_id=result.inspection.candidate_id,
        package_generation_id=generation_id,
        source_revision=source_revision,
        graph_id=result.inspection.graph.graph_id,
        candidate_btrfs_uuid=candidate_btrfs_uuid,
        base_btrfs_uuid=base_btrfs_uuid,
        base_root_identity=result.inspection.base_root_identity,
        candidate_root_identity=result.inspection.candidate_root_identity,
        runtime_evidence_sha256=result.inspection.runtime_evidence_sha256,
        admission_payload_sha256=ArtifactID.from_content(canonical_bytes(payload)).removeprefix("art-"),
        candidate_boot_sha256=boot,
    )
    return FrozenAdmissionEvidence(
        evidence_id=ArtifactID.from_content(canonical_bytes(provisional.identity_material())),
        **{name: getattr(provisional, name) for name in provisional.__dataclass_fields__ if name != "evidence_id"},
    )


def _parse_frozen_admission(value: Mapping[str, Any]) -> FrozenAdmissionEvidence:
    required = {
        "schema_version", "kind", "update_transaction_id", "guardian_transaction_id",
        "candidate_id", "package_generation_id", "source_revision", "graph_id",
        "candidate_btrfs_uuid", "base_btrfs_uuid", "base_root_identity",
        "candidate_root_identity", "runtime_evidence_sha256", "admission_payload_sha256",
        "candidate_boot_sha256", "evidence_id",
    }
    if set(value) != required or value.get("schema_version") != 1 or value.get("kind") != "maho-update-frozen-admission-evidence":
        raise ProductionAdmissionError("frozen_admission_fields_invalid")
    boot = value.get("candidate_boot_sha256")
    if not isinstance(boot, Mapping):
        raise ProductionAdmissionError("frozen_admission_boot_identity_invalid")
    try:
        evidence = FrozenAdmissionEvidence(
            evidence_id=ArtifactID(str(value["evidence_id"])),
            update_transaction_id=str(value["update_transaction_id"]),
            guardian_transaction_id=TransactionID(str(value["guardian_transaction_id"])),
            candidate_id=str(value["candidate_id"]),
            package_generation_id=str(value["package_generation_id"]),
            source_revision=str(value["source_revision"]),
            graph_id=ArtifactID(str(value["graph_id"])),
            candidate_btrfs_uuid=str(value["candidate_btrfs_uuid"]),
            base_btrfs_uuid=str(value["base_btrfs_uuid"]),
            base_root_identity=str(value["base_root_identity"]),
            candidate_root_identity=str(value["candidate_root_identity"]),
            runtime_evidence_sha256=str(value["runtime_evidence_sha256"]),
            admission_payload_sha256=str(value["admission_payload_sha256"]),
            candidate_boot_sha256={str(path): str(digest) for path, digest in boot.items()},
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProductionAdmissionError("frozen_admission_invalid") from exc
    if value != evidence.as_dict():
        raise ProductionAdmissionError("frozen_admission_contract_invalid")
    if ArtifactID.from_content(canonical_bytes(evidence.identity_material())) != evidence.evidence_id:
        raise ProductionAdmissionError("frozen_admission_digest_mismatch")
    return evidence


def _verify_frozen_admission(
    value: Mapping[str, Any], *, admission_payload: Mapping[str, Any], roots: CandidateRoots,
    update_transaction_id: str, transaction: Mapping[str, Any], source_revision: str,
    candidate_btrfs_uuid: str, base_btrfs_uuid: str,
    candidate_boot_sha256: Mapping[str, str],
) -> FrozenAdmissionEvidence:
    evidence = _parse_frozen_admission(value)
    generation_id, _ = _package_generation(transaction)
    runtime = offline_runtime_evidence(roots)
    mutation_graph = admission_payload.get("mutation_graph")
    graph_id = mutation_graph.get("graph_id") if isinstance(mutation_graph, Mapping) else None
    if (
        evidence.update_transaction_id != update_transaction_id
        or evidence.guardian_transaction_id != guardian_transaction_id(update_transaction_id)
        or evidence.candidate_id != roots.candidate_id
        or evidence.package_generation_id != generation_id
        or evidence.source_revision != source_revision
        or str(evidence.graph_id) != graph_id
        or evidence.candidate_btrfs_uuid != candidate_btrfs_uuid
        or evidence.base_btrfs_uuid != base_btrfs_uuid
        or evidence.base_root_identity != root_identity(roots.base_root)
        or evidence.candidate_root_identity != root_identity(roots.candidate_root)
        or evidence.runtime_evidence_sha256 != runtime.evidence_sha256
        or evidence.admission_payload_sha256 != ArtifactID.from_content(canonical_bytes(dict(admission_payload))).removeprefix("art-")
        or dict(evidence.candidate_boot_sha256) != dict(candidate_boot_sha256)
    ):
        raise ProductionAdmissionError("frozen_admission_binding_mismatch")
    return evidence


def _wrap_frozen_activation_authority(
    authority: "ProductionActivationAuthority", evidence: FrozenAdmissionEvidence,
) -> FrozenActivationAuthority:
    provisional = FrozenActivationAuthority(
        authority_id=ArtifactID.from_content(b"placeholder"),
        frozen_admission_evidence_id=evidence.evidence_id,
        candidate_btrfs_uuid=evidence.candidate_btrfs_uuid,
        base_btrfs_uuid=evidence.base_btrfs_uuid,
        activation_authority=authority.as_dict(),
    )
    return FrozenActivationAuthority(
        authority_id=ArtifactID.from_content(canonical_bytes(provisional.identity_material())),
        frozen_admission_evidence_id=provisional.frozen_admission_evidence_id,
        candidate_btrfs_uuid=provisional.candidate_btrfs_uuid,
        base_btrfs_uuid=provisional.base_btrfs_uuid,
        activation_authority=provisional.activation_authority,
    )


@dataclass(frozen=True)
class ProductionActivationAuthority:
    authority_id: ArtifactID
    update_transaction_id: str
    guardian_transaction_id: TransactionID
    candidate_id: str
    package_generation_id: str
    graph_id: ArtifactID
    base_root_identity: str
    candidate_root_identity: str
    runtime_evidence_sha256: str
    source_revision: str
    boot_generation_id: str | None
    boot_authority_id: str | None
    release_sequence: int | None
    security_epoch: int | None
    signer_fingerprint: str | None
    native_promotion_authority: Mapping[str, Any]

    def identity_material(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "kind": "maho-update-admission-activation-authority",
            "authority_scope": "activate-exact-native-admitted-update-candidate",
            "update_transaction_id": self.update_transaction_id,
            "guardian_transaction_id": str(self.guardian_transaction_id),
            "candidate_id": self.candidate_id,
            "package_generation_id": self.package_generation_id,
            "graph_id": str(self.graph_id),
            "base_root_identity": self.base_root_identity,
            "candidate_root_identity": self.candidate_root_identity,
            "runtime_evidence_sha256": self.runtime_evidence_sha256,
            "source_revision": self.source_revision,
            "boot_generation_id": self.boot_generation_id,
            "boot_authority_id": self.boot_authority_id,
            "release_sequence": self.release_sequence,
            "security_epoch": self.security_epoch,
            "signer_fingerprint": self.signer_fingerprint,
            "native_promotion_authority": dict(self.native_promotion_authority),
        }

    def as_dict(self) -> dict[str, Any]:
        return self.identity_material() | {"authority_id": str(self.authority_id)}


def issue_activation_authority(
    result: NativeAdmissionResult,
    *,
    update_transaction_id: str,
    transaction: Mapping[str, Any],
    source_revision: str,
    boot_generation: BootGeneration | None = None,
    boot_authority: BootAuthority | None = None,
) -> ProductionActivationAuthority:
    if _UPDATE_TX.fullmatch(update_transaction_id) is None or _SHA40.fullmatch(source_revision) is None:
        raise ProductionAdmissionError("activation_authority_context_invalid")
    if result.decision.outcome is not AdmissionOutcome.ALLOW or result.promotion_authority is None:
        raise ProductionAdmissionError("native_admission_did_not_allow_activation")
    generation_id, _ = _package_generation(transaction)
    inspection = result.inspection
    if (boot_generation is None) != (boot_authority is None):
        raise ProductionAdmissionError("signed_boot_binding_incomplete")
    if boot_generation is not None and boot_authority is not None:
        if (
            boot_generation.source_revision != source_revision
            or boot_generation.package_generation_id != generation_id
            or boot_generation.candidate_root_identity != inspection.candidate_root_identity
            or boot_authority.permitted_boot_generation_id != boot_generation.boot_generation_id
            or boot_authority.source_revision != source_revision
        ):
            raise ProductionAdmissionError("signed_boot_binding_mismatch")
    native = result.promotion_authority.as_dict()
    authority = ProductionActivationAuthority(
        authority_id=ArtifactID.from_content(b"placeholder"),
        update_transaction_id=update_transaction_id,
        guardian_transaction_id=result.decision.transaction_id,
        candidate_id=inspection.candidate_id,
        package_generation_id=generation_id,
        graph_id=inspection.graph.graph_id,
        base_root_identity=inspection.base_root_identity,
        candidate_root_identity=inspection.candidate_root_identity,
        runtime_evidence_sha256=inspection.runtime_evidence_sha256,
        source_revision=source_revision,
        boot_generation_id=boot_generation.boot_generation_id if boot_generation else None,
        boot_authority_id=boot_authority.boot_authority_id if boot_authority else None,
        release_sequence=boot_authority.release_sequence if boot_authority else None,
        security_epoch=boot_authority.security_epoch if boot_authority else None,
        signer_fingerprint=boot_authority.device_signing_certificate_fingerprint if boot_authority else None,
        native_promotion_authority=native,
    )
    material = authority.identity_material()
    return ProductionActivationAuthority(
        authority_id=ArtifactID.from_content(canonical_bytes(material)),
        update_transaction_id=authority.update_transaction_id,
        guardian_transaction_id=authority.guardian_transaction_id,
        candidate_id=authority.candidate_id,
        package_generation_id=authority.package_generation_id,
        graph_id=authority.graph_id,
        base_root_identity=authority.base_root_identity,
        candidate_root_identity=authority.candidate_root_identity,
        runtime_evidence_sha256=authority.runtime_evidence_sha256,
        source_revision=authority.source_revision,
        boot_generation_id=authority.boot_generation_id,
        boot_authority_id=authority.boot_authority_id,
        release_sequence=authority.release_sequence,
        security_epoch=authority.security_epoch,
        signer_fingerprint=authority.signer_fingerprint,
        native_promotion_authority=authority.native_promotion_authority,
    )


def issue_frozen_activation_authority(
    result: NativeAdmissionResult,
    frozen_evidence: Mapping[str, Any],
    *, update_transaction_id: str, transaction: Mapping[str, Any], source_revision: str,
) -> FrozenActivationAuthority:
    evidence = _parse_frozen_admission(frozen_evidence)
    if (
        result.decision.outcome is not AdmissionOutcome.ALLOW
        or result.promotion_authority is None
        or evidence.update_transaction_id != update_transaction_id
        or evidence.graph_id != result.decision.graph_id
        or evidence.candidate_id != result.inspection.candidate_id
        or evidence.base_root_identity != result.inspection.base_root_identity
        or evidence.candidate_root_identity != result.inspection.candidate_root_identity
        or evidence.runtime_evidence_sha256 != result.inspection.runtime_evidence_sha256
    ):
        raise ProductionAdmissionError("frozen_admission_allow_binding_mismatch")
    authority = issue_activation_authority(
        result,
        update_transaction_id=update_transaction_id,
        transaction=transaction,
        source_revision=source_revision,
    )
    return _wrap_frozen_activation_authority(authority, evidence)


def approve_frozen_production_admission(
    frozen_evidence: Mapping[str, Any], admission_payload: Mapping[str, Any],
    *, roots: CandidateRoots, reviewed_graph_id: ArtifactID,
    update_transaction_id: str, transaction: Mapping[str, Any], source_revision: str,
    candidate_btrfs_uuid: str, base_btrfs_uuid: str,
    candidate_boot_sha256: Mapping[str, str],
) -> tuple[dict[str, Any], FrozenActivationAuthority]:
    """Approve one immutable reviewed graph and issue activation authority without rescanning."""
    evidence = _verify_frozen_admission(
        frozen_evidence,
        admission_payload=admission_payload,
        roots=roots,
        update_transaction_id=update_transaction_id,
        transaction=transaction,
        source_revision=source_revision,
        candidate_btrfs_uuid=candidate_btrfs_uuid,
        base_btrfs_uuid=base_btrfs_uuid,
        candidate_boot_sha256=candidate_boot_sha256,
    )
    try:
        approved_payload, decision, promotion = approve_persisted_admission(
            admission_payload, roots=roots, reviewed_graph_id=reviewed_graph_id,
        )
    except NativeAdmissionError as exc:
        raise ProductionAdmissionError(str(exc)) from exc
    inspection = NativeInspection(
        graph=MutationGraph(decision.transaction_id, decision.graph_id, (), True),
        candidate_id=roots.candidate_id,
        base_root_identity=evidence.base_root_identity,
        candidate_root_identity=evidence.candidate_root_identity,
        excluded_roots=tuple(str(item) for item in approved_payload["excluded_roots"]),
        errors=(), runtime_complete=True, runtime_isolated=True,
        runtime_evidence_sha256=evidence.runtime_evidence_sha256,
    )
    synthetic = NativeAdmissionResult(inspection, decision, promotion)
    authority = issue_activation_authority(
        synthetic,
        update_transaction_id=update_transaction_id,
        transaction=transaction,
        source_revision=source_revision,
    )
    approval = {
        "decision": decision.as_dict(),
        "promotion_authority": promotion.as_dict(),
        "frozen_admission_evidence_id": str(evidence.evidence_id),
    }
    return approval, _wrap_frozen_activation_authority(authority, evidence)


def _parse_frozen_activation_authority(value: Mapping[str, Any]) -> FrozenActivationAuthority:
    required = {
        "schema_version", "kind", "authority_scope", "frozen_admission_evidence_id",
        "candidate_btrfs_uuid", "base_btrfs_uuid", "activation_authority", "authority_id",
    }
    nested = value.get("activation_authority")
    if (
        set(value) != required
        or value.get("schema_version") != 1
        or value.get("kind") != "maho-update-frozen-activation-authority"
        or value.get("authority_scope") != "activate-exact-immutable-native-admitted-candidate"
        or not isinstance(nested, Mapping)
    ):
        raise ProductionAdmissionError("frozen_activation_authority_fields_invalid")
    try:
        authority = FrozenActivationAuthority(
            authority_id=ArtifactID(str(value["authority_id"])),
            frozen_admission_evidence_id=ArtifactID(str(value["frozen_admission_evidence_id"])),
            candidate_btrfs_uuid=str(value["candidate_btrfs_uuid"]),
            base_btrfs_uuid=str(value["base_btrfs_uuid"]),
            activation_authority=dict(nested),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProductionAdmissionError("frozen_activation_authority_invalid") from exc
    if value != authority.as_dict():
        raise ProductionAdmissionError("frozen_activation_authority_contract_invalid")
    if ArtifactID.from_content(canonical_bytes(authority.identity_material())) != authority.authority_id:
        raise ProductionAdmissionError("frozen_activation_authority_digest_mismatch")
    return authority


def verify_frozen_activation_authority(
    value: Mapping[str, Any], frozen_evidence: Mapping[str, Any],
    admission_payload: Mapping[str, Any], admission_approval: Mapping[str, Any],
    *, roots: CandidateRoots, update_transaction_id: str,
    transaction: Mapping[str, Any], source_revision: str,
    candidate_btrfs_uuid: str, base_btrfs_uuid: str,
    candidate_boot_sha256: Mapping[str, str],
) -> FrozenActivationAuthority:
    """Consume exact immutable Admission authority without a third root scan."""
    envelope = _parse_frozen_activation_authority(value)
    evidence = _verify_frozen_admission(
        frozen_evidence,
        admission_payload=admission_payload,
        roots=roots,
        update_transaction_id=update_transaction_id,
        transaction=transaction,
        source_revision=source_revision,
        candidate_btrfs_uuid=candidate_btrfs_uuid,
        base_btrfs_uuid=base_btrfs_uuid,
        candidate_boot_sha256=candidate_boot_sha256,
    )
    if (
        envelope.frozen_admission_evidence_id != evidence.evidence_id
        or envelope.candidate_btrfs_uuid != candidate_btrfs_uuid
        or envelope.base_btrfs_uuid != base_btrfs_uuid
        or admission_approval.get("frozen_admission_evidence_id") != str(evidence.evidence_id)
    ):
        raise ProductionAdmissionError("frozen_activation_authority_binding_mismatch")
    decision_value = admission_approval.get("decision")
    promotion_value = admission_approval.get("promotion_authority")
    if not isinstance(decision_value, Mapping) or not isinstance(promotion_value, Mapping):
        raise ProductionAdmissionError("frozen_admission_approval_invalid")
    approved_payload = dict(admission_payload)
    approved_payload["decision"] = dict(decision_value)
    approved_payload["promotion_authority"] = dict(promotion_value)
    try:
        decision, promotion = verify_persisted_admission_authority(approved_payload, roots=roots)
    except NativeAdmissionError as exc:
        raise ProductionAdmissionError(str(exc)) from exc
    authority = _parse_authority(envelope.activation_authority)
    generation_id, _ = _package_generation(transaction)
    if (
        authority.update_transaction_id != update_transaction_id
        or authority.guardian_transaction_id != guardian_transaction_id(update_transaction_id)
        or authority.candidate_id != roots.candidate_id
        or authority.package_generation_id != generation_id
        or authority.graph_id != decision.graph_id
        or authority.base_root_identity != evidence.base_root_identity
        or authority.candidate_root_identity != evidence.candidate_root_identity
        or authority.runtime_evidence_sha256 != evidence.runtime_evidence_sha256
        or authority.source_revision != source_revision
        or authority.native_promotion_authority != promotion.as_dict()
    ):
        raise ProductionAdmissionError("frozen_activation_authority_context_mismatch")
    return envelope


def _parse_authority(value: Mapping[str, Any]) -> ProductionActivationAuthority:
    required = {
        "schema_version", "kind", "authority_scope", "update_transaction_id",
        "guardian_transaction_id", "candidate_id", "package_generation_id", "graph_id",
        "base_root_identity", "candidate_root_identity", "runtime_evidence_sha256",
        "source_revision", "native_promotion_authority", "authority_id",
        "boot_generation_id", "boot_authority_id", "release_sequence", "security_epoch",
        "signer_fingerprint",
    }
    if set(value) != required or value.get("schema_version") != 2:
        raise ProductionAdmissionError("activation_authority_fields_invalid")
    native = value.get("native_promotion_authority")
    if not isinstance(native, Mapping):
        raise ProductionAdmissionError("activation_authority_native_binding_invalid")
    try:
        authority = ProductionActivationAuthority(
            authority_id=ArtifactID(str(value["authority_id"])),
            update_transaction_id=str(value["update_transaction_id"]),
            guardian_transaction_id=TransactionID(str(value["guardian_transaction_id"])),
            candidate_id=str(value["candidate_id"]),
            package_generation_id=str(value["package_generation_id"]),
            graph_id=ArtifactID(str(value["graph_id"])),
            base_root_identity=str(value["base_root_identity"]),
            candidate_root_identity=str(value["candidate_root_identity"]),
            runtime_evidence_sha256=str(value["runtime_evidence_sha256"]),
            source_revision=str(value["source_revision"]),
            boot_generation_id=str(value["boot_generation_id"]) if value["boot_generation_id"] is not None else None,
            boot_authority_id=str(value["boot_authority_id"]) if value["boot_authority_id"] is not None else None,
            release_sequence=int(value["release_sequence"]) if value["release_sequence"] is not None else None,
            security_epoch=int(value["security_epoch"]) if value["security_epoch"] is not None else None,
            signer_fingerprint=str(value["signer_fingerprint"]) if value["signer_fingerprint"] is not None else None,
            native_promotion_authority=dict(native),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProductionAdmissionError("activation_authority_invalid") from exc
    if value != authority.as_dict():
        raise ProductionAdmissionError("activation_authority_contract_invalid")
    signed_fields = (
        authority.boot_generation_id, authority.boot_authority_id,
        authority.release_sequence, authority.security_epoch, authority.signer_fingerprint,
    )
    if any(item is None for item in signed_fields) and any(item is not None for item in signed_fields):
        raise ProductionAdmissionError("activation_authority_signed_boot_binding_incomplete")
    if authority.boot_generation_id is not None:
        if (
            not authority.boot_generation_id.startswith("bootgen-")
            or not authority.boot_authority_id.startswith("bootauth-")
            or authority.release_sequence < 1 or authority.security_epoch < 1
            or re.fullmatch(r"[0-9A-F]{40,128}", authority.signer_fingerprint or "") is None
        ):
            raise ProductionAdmissionError("activation_authority_signed_boot_binding_invalid")
    expected = ArtifactID.from_content(canonical_bytes(authority.identity_material()))
    if authority.authority_id != expected:
        raise ProductionAdmissionError("activation_authority_digest_mismatch")
    return authority


def verify_normal_activation_authority(
    value: Mapping[str, Any],
    *,
    roots: CandidateRoots,
    update_transaction_id: str,
    transaction: Mapping[str, Any],
    source_revision: str,
) -> ProductionActivationAuthority:
    """Revalidate one admitted normal candidate before root-only activation.

    Normal S2.2 activation deliberately has no live Pacman mutation.  This
    verifier therefore reuses the exact Guardian promotion authority against
    the still-frozen candidate and the normal package declaration.
    """
    authority = _parse_authority(value)
    generation_id, _ = _package_generation(transaction)
    expected_guardian_tx = guardian_transaction_id(update_transaction_id)
    if (
        authority.update_transaction_id != update_transaction_id
        or authority.guardian_transaction_id != expected_guardian_tx
        or authority.candidate_id != roots.candidate_id
        or authority.package_generation_id != generation_id
        or authority.source_revision != source_revision
    ):
        raise ProductionAdmissionError("normal_activation_authority_context_mismatch")
    if any((
        authority.boot_generation_id is not None,
        authority.boot_authority_id is not None,
        authority.release_sequence is not None,
        authority.security_epoch is not None,
        authority.signer_fingerprint is not None,
    )):
        raise ProductionAdmissionError("normal_activation_authority_boot_scope_invalid")
    declaration = build_normal_production_declaration(
        roots,
        transaction,
        operational_paths=(
            f"/var/lib/maho/update/transactions/{update_transaction_id}.json",
            "/var/lib/maho/update/current",
        ),
    )
    runtime = offline_runtime_evidence(roots)
    try:
        native, inspection = revalidate_promotion_authority(
            authority.native_promotion_authority,
            roots=roots,
            declaration=declaration,
            runtime=runtime,
        )
    except NativeAdmissionError as exc:
        raise ProductionAdmissionError(str(exc)) from exc
    if not isinstance(native, PromotionAuthority):
        raise ProductionAdmissionError("normal_activation_authority_native_binding_invalid")
    if (
        authority.graph_id != inspection.graph.graph_id
        or authority.base_root_identity != inspection.base_root_identity
        or authority.candidate_root_identity != inspection.candidate_root_identity
        or authority.runtime_evidence_sha256 != inspection.runtime_evidence_sha256
    ):
        raise ProductionAdmissionError("normal_activation_authority_evidence_mismatch")
    return authority


def verify_activation_authority(
    value: Mapping[str, Any],
    *,
    roots: CandidateRoots,
    update_transaction_id: str,
    transaction: Mapping[str, Any],
    plan: ExecutionPlan,
    source_revision: str,
    boot_generation: BootGeneration | None = None,
    boot_authority: BootAuthority | None = None,
) -> ProductionActivationAuthority:
    authority = _parse_authority(value)
    generation_id, _ = _package_generation(transaction)
    expected_guardian_tx = guardian_transaction_id(update_transaction_id)
    if (
        authority.update_transaction_id != update_transaction_id
        or authority.guardian_transaction_id != expected_guardian_tx
        or authority.candidate_id != roots.candidate_id
        or authority.package_generation_id != generation_id
        or authority.source_revision != source_revision
    ):
        raise ProductionAdmissionError("activation_authority_context_mismatch")
    bound = authority.boot_generation_id is not None
    if bound != (boot_generation is not None and boot_authority is not None):
        raise ProductionAdmissionError("activation_authority_signed_boot_context_missing")
    if bound and boot_generation is not None and boot_authority is not None and (
        authority.boot_generation_id != boot_generation.boot_generation_id
        or authority.boot_authority_id != boot_authority.boot_authority_id
        or authority.release_sequence != boot_authority.release_sequence
        or authority.security_epoch != boot_authority.security_epoch
        or authority.signer_fingerprint != boot_authority.device_signing_certificate_fingerprint
        or boot_authority.permitted_boot_generation_id != boot_generation.boot_generation_id
        or boot_generation.candidate_root_identity != authority.candidate_root_identity
    ):
        raise ProductionAdmissionError("activation_authority_signed_boot_context_mismatch")
    declaration = build_production_declaration(roots, transaction, plan)
    runtime = offline_runtime_evidence(roots)
    try:
        native, inspection = revalidate_promotion_authority(
            authority.native_promotion_authority,
            roots=roots,
            declaration=declaration,
            runtime=runtime,
        )
    except NativeAdmissionError as exc:
        raise ProductionAdmissionError(str(exc)) from exc
    if not isinstance(native, PromotionAuthority):
        raise ProductionAdmissionError("activation_authority_native_binding_invalid")
    if (
        authority.graph_id != inspection.graph.graph_id
        or authority.base_root_identity != inspection.base_root_identity
        or authority.candidate_root_identity != inspection.candidate_root_identity
        or authority.runtime_evidence_sha256 != inspection.runtime_evidence_sha256
    ):
        raise ProductionAdmissionError("activation_authority_evidence_mismatch")
    return authority
