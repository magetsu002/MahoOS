#!/usr/bin/env python3
"""Deterministic, explainable causal relationships for Guardian.

This module grants no mutation authority. It records why already-observed facts
are related and keeps proven causality distinct from semantic correlation and
unresolved relationships. Time proximity alone is never causal evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
from typing import Any, Iterable, Mapping

from guardian_intent import CorrelationStatus, IntentCorrelation


class RelationStrength(str, Enum):
    PROVEN = "proven"
    CORRELATED = "correlated"
    UNKNOWN = "unknown"


_PROVEN_PROOFS = {
    "verified-authority-predicts-change",
    "package-metadata-owns-file",
    "verified-executable-identity",
    "service-cgroup-membership",
    "verified-socket-owner",
    "kernel-device-cause",
    "verified-recovery-receipt",
}
_CORRELATED_PROOFS = {
    "explicit-incident-subject",
    "same-package-path",
    "same-executable-path",
    "same-service-cgroup",
    "same-process-listener",
    "same-device-identity",
    "shared-transaction-identity",
}
_TIME_ONLY_PROOFS = {"timestamp", "time-proximity", "same-time", "nearby-in-time"}


def _edge_id(source: str, target: str, relation: str, strength: RelationStrength,
             evidence_ids: tuple[str, ...]) -> str:
    material = "\0".join((source, target, relation, strength.value, *evidence_ids)).encode()
    return "cause-" + hashlib.sha256(material).hexdigest()[:24]


@dataclass(frozen=True)
class CausalNode:
    node_id: str
    kind: str
    subject: str
    evidence_ids: tuple[str, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.node_id or not self.kind or not self.subject:
            raise ValueError("causal node identity is incomplete")
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind,
            "subject": self.subject,
            "evidence_ids": list(self.evidence_ids),
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class CausalEdge:
    source: str
    target: str
    relation: str
    strength: RelationStrength
    reason: str
    proof: str
    evidence_ids: tuple[str, ...] = ()
    edge_id: str = ""

    def __post_init__(self) -> None:
        if not self.source or not self.target or self.source == self.target:
            raise ValueError("causal edge endpoints are invalid")
        if not self.relation or not self.reason or not self.proof:
            raise ValueError("causal edge explanation is incomplete")
        if self.proof in _TIME_ONLY_PROOFS:
            raise ValueError("time proximity cannot establish a causal relationship")
        evidence = tuple(sorted(set(self.evidence_ids)))
        object.__setattr__(self, "evidence_ids", evidence)
        if self.strength is RelationStrength.PROVEN:
            if self.proof not in _PROVEN_PROOFS or not evidence:
                raise ValueError("proven causal edges require allowlisted exact proof and evidence")
        elif self.strength is RelationStrength.CORRELATED:
            if self.proof not in _CORRELATED_PROOFS or not evidence:
                raise ValueError("correlated edges require a semantic relation and evidence")
        if not self.edge_id:
            object.__setattr__(self, "edge_id", _edge_id(
                self.source, self.target, self.relation, self.strength, evidence,
            ))

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["strength"] = self.strength.value
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload


@dataclass(frozen=True)
class CausalGraph:
    nodes: tuple[CausalNode, ...]
    edges: tuple[CausalEdge, ...]

    def __post_init__(self) -> None:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("causal graph contains duplicate nodes")
        known = set(node_ids)
        edge_ids: set[str] = set()
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError("causal edge references unknown node")
            if edge.edge_id in edge_ids:
                raise ValueError("causal graph contains duplicate edges")
            edge_ids.add(edge.edge_id)

    def as_dict(self) -> dict[str, Any]:
        counts = {strength.value: 0 for strength in RelationStrength}
        for edge in self.edges:
            counts[edge.strength.value] += 1
        return {
            "schema_version": 1,
            "kind": "guardian-causal-graph",
            "counts": counts,
            "nodes": [node.as_dict() for node in self.nodes],
            "edges": [edge.as_dict() for edge in self.edges],
        }


def relationship(source: CausalNode, target: CausalNode, *, relation: str,
                 strength: RelationStrength, reason: str, proof: str,
                 evidence_ids: Iterable[str] = ()) -> CausalEdge:
    return CausalEdge(source.node_id, target.node_id, relation, strength, reason,
                      proof, tuple(evidence_ids))


def authority_change_edge(authority: CausalNode, change: CausalNode,
                          correlation: IntentCorrelation, *,
                          evidence_ids: Iterable[str]) -> CausalEdge:
    if (correlation.status is CorrelationStatus.AUTHORIZED_EXPECTED
            and correlation.suppress_escalation):
        return relationship(
            authority, change,
            relation="authorized-operation-caused-change",
            strength=RelationStrength.PROVEN,
            reason="independently verified authority predicted this exact change inside its bounded window",
            proof="verified-authority-predicts-change",
            evidence_ids=evidence_ids,
        )
    return relationship(
        authority, change,
        relation="authority-change-relationship",
        strength=RelationStrength.UNKNOWN,
        reason=f"authority did not prove this change: {correlation.status.value}",
        proof="authority-not-proven",
    )


def package_file_edge(package: CausalNode, file_node: CausalNode, *,
                      package_identity: str, observed_package: str,
                      file_path: str, evidence_id: str) -> CausalEdge:
    if observed_package == package_identity and file_path == file_node.subject:
        return relationship(
            package, file_node,
            relation="package-owns-file",
            strength=RelationStrength.PROVEN,
            reason="package metadata evidence binds this exact package to this exact file path",
            proof="package-metadata-owns-file",
            evidence_ids=(evidence_id,),
        )
    return relationship(
        package, file_node,
        relation="package-file-relationship",
        strength=RelationStrength.UNKNOWN,
        reason="package ownership of this file is not proven by the supplied evidence",
        proof="package-ownership-unknown",
    )


def file_process_edge(file_node: CausalNode, process: CausalNode, *,
                      file_path: str, process_exe: str,
                      executable_identity_verified: bool,
                      process_identity_stable: bool,
                      evidence_ids: Iterable[str]) -> CausalEdge:
    if file_path != process_exe:
        return relationship(
            file_node, process,
            relation="file-process-relationship",
            strength=RelationStrength.UNKNOWN,
            reason="observed process executable path does not identify this file",
            proof="executable-relationship-unknown",
        )
    if executable_identity_verified and process_identity_stable:
        return relationship(
            file_node, process,
            relation="file-executed-by-process",
            strength=RelationStrength.PROVEN,
            reason="stable process identity and executable content identity bind the process to the file",
            proof="verified-executable-identity",
            evidence_ids=evidence_ids,
        )
    return relationship(
        file_node, process,
        relation="file-matches-process-executable",
        strength=RelationStrength.CORRELATED,
        reason="process reports the same executable path but stable process/content identity is incomplete",
        proof="same-executable-path",
        evidence_ids=evidence_ids,
    )


def process_service_edge(process: CausalNode, service: CausalNode, *,
                         observed_cgroup: str | None, expected_cgroup: str | None,
                         process_identity_stable: bool,
                         evidence_ids: Iterable[str]) -> CausalEdge:
    if not observed_cgroup or observed_cgroup != expected_cgroup:
        return relationship(process, service, relation="process-service-relationship",
                            strength=RelationStrength.UNKNOWN,
                            reason="service cgroup ownership is not established",
                            proof="service-ownership-unknown")
    if process_identity_stable:
        return relationship(
            process, service, relation="process-owned-by-service",
            strength=RelationStrength.PROVEN,
            reason="stable process identity is a member of the exact service cgroup",
            proof="service-cgroup-membership", evidence_ids=evidence_ids,
        )
    return relationship(
        process, service, relation="process-associated-with-service",
        strength=RelationStrength.CORRELATED,
        reason="cgroup matches the service but stable process identity is unavailable",
        proof="same-service-cgroup", evidence_ids=evidence_ids,
    )


def process_listener_edge(process: CausalNode, listener: CausalNode, *,
                          socket_owner_verified: bool, same_process_identity: bool,
                          evidence_ids: Iterable[str]) -> CausalEdge:
    if socket_owner_verified and same_process_identity:
        return relationship(
            process, listener, relation="process-owns-listener",
            strength=RelationStrength.PROVEN,
            reason="socket ownership is bound to the exact stable process identity",
            proof="verified-socket-owner", evidence_ids=evidence_ids,
        )
    if same_process_identity:
        return relationship(
            process, listener, relation="process-associated-with-listener",
            strength=RelationStrength.CORRELATED,
            reason="listener and process identifiers correlate but socket ownership is not independently verified",
            proof="same-process-listener", evidence_ids=evidence_ids,
        )
    return relationship(process, listener, relation="process-listener-relationship",
                        strength=RelationStrength.UNKNOWN,
                        reason="listener ownership is not established",
                        proof="listener-owner-unknown")


def recovery_state_edge(action: CausalNode, state: CausalNode, *,
                        same_transaction: bool, verified_receipt: bool,
                        evidence_ids: Iterable[str]) -> CausalEdge:
    if same_transaction and verified_receipt:
        return relationship(
            action, state, relation="recovery-produced-state",
            strength=RelationStrength.PROVEN,
            reason="verified recovery receipt binds the action and resulting state to the same transaction",
            proof="verified-recovery-receipt", evidence_ids=evidence_ids,
        )
    if same_transaction:
        return relationship(
            action, state, relation="recovery-correlates-with-state",
            strength=RelationStrength.CORRELATED,
            reason="action and state share a transaction identity but verification is incomplete",
            proof="shared-transaction-identity", evidence_ids=evidence_ids,
        )
    return relationship(action, state, relation="recovery-state-relationship",
                        strength=RelationStrength.UNKNOWN,
                        reason="no verified transaction identity links the recovery action to this state",
                        proof="recovery-relationship-unknown")
