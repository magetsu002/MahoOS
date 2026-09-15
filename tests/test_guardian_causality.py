#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_causality import (
    CausalGraph, CausalNode, RelationStrength, authority_change_edge,
    file_process_edge, package_file_edge, process_listener_edge,
    process_service_edge, recovery_state_edge, relationship,
)
from guardian_intent import (
    AuthorizedOperation, ChangeExpectation, ChangeObservation,
    OperationKind, OperationState, correlate_change,
)
from guardian_evidence import utc_stamp

NOW = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def node(name: str, kind: str = "test") -> CausalNode:
    return CausalNode(name, kind, name, (f"ev:{name}",))


def main() -> None:
    auth, change = node("op", "operation"), node("file", "file")
    operation = AuthorizedOperation(
        operation_id="op",
        kind=OperationKind.MAHO_UPDATE,
        state=OperationState.ACTIVE,
        authority="update-authority",
        authority_verified=True,
        started_at=utc_stamp(NOW - timedelta(minutes=1)),
        expires_at=utc_stamp(NOW + timedelta(minutes=1)),
        expected_changes=(ChangeExpectation("file-write", "/usr/bin/maho"),),
        source="update",
        evidence_ids=("authority:1",),
    )
    observed = ChangeObservation("file-write", "/usr/bin/maho", utc_stamp(NOW), "fanotify")
    correlation = correlate_change(observed, (operation,))
    edge = authority_change_edge(auth, change, correlation, evidence_ids=("authority:1", "change:1"))
    check("exact authorized change becomes proven", edge.strength is RelationStrength.PROVEN)

    unrelated = ChangeObservation("file-write", "/etc/ssh/sshd_config", utc_stamp(NOW), "fanotify")
    edge = authority_change_edge(auth, change, correlate_change(unrelated, (operation,)), evidence_ids=("change:2",))
    check("unrelated active update does not prove causality", edge.strength is RelationStrength.UNKNOWN)

    package, file_node = node("pkg", "package"), CausalNode("bin", "file", "/usr/bin/maho")
    edge = package_file_edge(package, file_node, package_identity="pkg", observed_package="pkg",
                             file_path="/usr/bin/maho", evidence_id="mtree:1")
    check("exact package metadata proves file ownership", edge.strength is RelationStrength.PROVEN)
    edge = package_file_edge(package, file_node, package_identity="pkg", observed_package="other",
                             file_path="/usr/bin/maho", evidence_id="mtree:2")
    check("package mismatch remains unknown", edge.strength is RelationStrength.UNKNOWN)

    process = node("proc", "process")
    edge = file_process_edge(file_node, process, file_path="/usr/bin/maho", process_exe="/usr/bin/maho",
                             executable_identity_verified=False, process_identity_stable=False,
                             evidence_ids=("proc:1",))
    check("path-only file process relation is correlated", edge.strength is RelationStrength.CORRELATED)
    edge = file_process_edge(file_node, process, file_path="/usr/bin/maho", process_exe="/usr/bin/maho",
                             executable_identity_verified=True, process_identity_stable=True,
                             evidence_ids=("hash:1", "proc-start:1"))
    check("stable process and executable identity prove execution", edge.strength is RelationStrength.PROVEN)

    service = node("svc", "service")
    edge = process_service_edge(process, service, observed_cgroup="/user.slice/maho.service",
                                expected_cgroup="/user.slice/maho.service", process_identity_stable=False,
                                evidence_ids=("cgroup:1",))
    check("cgroup without stable process identity is correlated", edge.strength is RelationStrength.CORRELATED)
    edge = process_service_edge(process, service, observed_cgroup="/user.slice/maho.service",
                                expected_cgroup="/user.slice/maho.service", process_identity_stable=True,
                                evidence_ids=("cgroup:1", "proc-start:1"))
    check("stable cgroup membership proves service ownership", edge.strength is RelationStrength.PROVEN)

    listener = node("listen", "listener")
    edge = process_listener_edge(process, listener, socket_owner_verified=False,
                                 same_process_identity=True, evidence_ids=("net:1",))
    check("PID correlation alone does not prove listener ownership", edge.strength is RelationStrength.CORRELATED)
    edge = process_listener_edge(process, listener, socket_owner_verified=True,
                                 same_process_identity=True, evidence_ids=("socket:1", "proc-start:1"))
    check("verified socket owner proves listener ownership", edge.strength is RelationStrength.PROVEN)

    action, state = node("recovery", "recovery-action"), node("state", "system-state")
    edge = recovery_state_edge(action, state, same_transaction=True, verified_receipt=False,
                               evidence_ids=("tx:1",))
    check("shared recovery transaction alone is correlated", edge.strength is RelationStrength.CORRELATED)
    edge = recovery_state_edge(action, state, same_transaction=True, verified_receipt=True,
                               evidence_ids=("receipt:1",))
    check("verified recovery receipt proves resulting transition", edge.strength is RelationStrength.PROVEN)

    try:
        relationship(auth, change, relation="happened-near", strength=RelationStrength.CORRELATED,
                     reason="same timestamp", proof="time-proximity", evidence_ids=("clock:1",))
    except ValueError:
        pass
    else:
        raise AssertionError("timestamp-only causality was accepted")
    check("timestamp-only causality is rejected", True)

    graph = CausalGraph((auth, change), (authority_change_edge(
        auth, change, correlation, evidence_ids=("authority:1",)),))
    payload = graph.as_dict()
    check("graph preserves explainable edge strength", payload["edges"][0]["strength"] == "proven")
    check("graph reports counts not a score", payload["counts"]["proven"] == 1 and "score" not in payload)
    print("ALL GUARDIAN CAUSALITY TESTS PASS")


if __name__ == "__main__":
    main()
