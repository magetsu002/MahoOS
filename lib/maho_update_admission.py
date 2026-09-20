#!/usr/bin/env python3
"""Production Native Admission binding for Maho update candidates.

This module does not install packages or activate roots. It translates one exact
Maho update transaction into Native Admission evidence, then wraps the resulting
ALLOW authority in a durable activation handoff bound to the update transaction,
package generation, candidate root, mutation graph, runtime evidence, and source.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from guardian_admission import AdmissionOutcome, CandidateDeclaration, EffectKind
from guardian_native_admission import (
    CandidateRoots,
    NativeAdmissionError,
    NativeAdmissionResult,
    PromotionAuthority,
    RuntimeListenerEvidence,
    admit_candidate,
    package_ownership,
    revalidate_promotion_authority,
    root_identity,
)
from maho_trust_identity import ArtifactID, TransactionID, canonical_bytes
from maho_boot_authority import BootAuthority, BootGeneration
from maho_update_state import validate_transaction
from maho_update_transaction import ExecutionPlan

_UPDATE_TX = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
_SHA40 = re.compile(r"[0-9a-f]{40}")
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


def build_production_declaration(
    roots: CandidateRoots,
    transaction: Mapping[str, Any],
    plan: ExecutionPlan,
) -> CandidateDeclaration:
    """Build a bounded declaration from exact package ownership plus planned outputs."""
    generation_id, names = _package_generation(transaction)
    ownership, errors = package_ownership(roots.candidate_root)
    if errors:
        raise ProductionAdmissionError("candidate_package_ownership_incomplete")
    package_set = set(names)
    declared = {path for path, owner in ownership.items() if owner in package_set}
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
) -> CandidateDeclaration:
    """Declare exact normal-package ownership plus bounded package-manager metadata."""
    generation_id, names = _package_generation(transaction)
    ownership, errors = package_ownership(roots.candidate_root)
    if errors:
        raise ProductionAdmissionError("candidate_package_ownership_incomplete")
    package_set = set(names)
    declared = {path for path, owner in ownership.items() if owner in package_set}
    declared.update({"/var/lib/pacman/local", "/var/log/pacman.log", "/etc/ld.so.cache"})
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
) -> NativeAdmissionResult:
    declaration = build_normal_production_declaration(roots, transaction)
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
