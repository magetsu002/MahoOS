#!/usr/bin/env python3
"""Project normalized GuardianEvent observations into Guardian's causal graph.

The projector only creates PROVEN edges for relationships directly carried by
kernel-observation evidence. It deliberately distinguishes write-access from a
verified file mutation and connect-attempt from a verified established socket.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable

from guardian_causality import CausalEdge, CausalGraph, CausalNode, RelationStrength, relationship
from guardian_event import GuardianEvent, GuardianEventKind, GuardianProcessRef


def _path_node_id(path: str) -> str:
    return "gfile-" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:32]


def _connection_node_id(event: GuardianEvent) -> str:
    socket_id = event.target.get("socket_id")
    if isinstance(socket_id, str) and socket_id:
        return socket_id
    return "gconn-" + hashlib.sha256(event.event_id.encode("utf-8")).hexdigest()[:32]


def _process_attributes(process: GuardianProcessRef, *, details_known: bool = True) -> dict[str, Any]:
    return {
        "stable_identity": True,
        "details_known": details_known,
        "pid": process.pid,
        "uid": process.uid,
        "binary": process.binary,
        "started_at": process.started_at,
        "parent_process_id": process.parent_process_id,
        "source_identity": process.source_identity,
    }


def _process_node(process: GuardianProcessRef, evidence_ids: Iterable[str]) -> CausalNode:
    return CausalNode(
        node_id=process.process_id,
        kind="process",
        subject=process.process_id,
        evidence_ids=tuple(evidence_ids),
        attributes=_process_attributes(process),
    )


def _placeholder_process_node(process_id: str, evidence_ids: Iterable[str]) -> CausalNode:
    return CausalNode(
        node_id=process_id,
        kind="process",
        subject=process_id,
        evidence_ids=tuple(evidence_ids),
        attributes={
            "stable_identity": True,
            "details_known": False,
        },
    )


def _merge_nodes(existing: CausalNode, incoming: CausalNode) -> CausalNode:
    if existing.node_id != incoming.node_id or existing.kind != incoming.kind:
        raise ValueError("cannot merge different causal nodes")

    attributes = dict(existing.attributes)
    incoming_attributes = dict(incoming.attributes)

    for key, value in incoming_attributes.items():
        if key in attributes:
            previous = attributes[key]
            # Placeholder values may be replaced by real process detail.
            if key == "details_known":
                attributes[key] = bool(previous) or bool(value)
                continue
            if previous is not None and value is not None and previous != value:
                raise ValueError(f"conflicting causal node attribute: {key}")
            if previous is None and value is not None:
                attributes[key] = value
        else:
            attributes[key] = value

    subject = existing.subject
    if existing.subject != incoming.subject:
        # Process placeholders and full process nodes intentionally use the
        # stable process identity as subject, so any mismatch is suspicious.
        raise ValueError("conflicting causal node subject")

    return CausalNode(
        node_id=existing.node_id,
        kind=existing.kind,
        subject=subject,
        evidence_ids=tuple(set(existing.evidence_ids) | set(incoming.evidence_ids)),
        attributes=attributes,
    )


def project_guardian_events(events: Iterable[GuardianEvent]) -> CausalGraph:
    nodes: dict[str, CausalNode] = {}
    edges: dict[str, CausalEdge] = {}

    def add_node(node: CausalNode) -> None:
        previous = nodes.get(node.node_id)
        nodes[node.node_id] = node if previous is None else _merge_nodes(previous, node)

    def add_edge(edge: CausalEdge) -> None:
        previous = edges.get(edge.edge_id)
        if previous is not None and previous != edge:
            raise ValueError("causal edge identity collision")
        edges[edge.edge_id] = edge

    event_list = tuple(events)

    # First establish all process nodes so parent references can be enriched by
    # other events in the same projection rather than remaining placeholders.
    for event in event_list:
        if event.process is not None:
            add_node(_process_node(event.process, (event.event_id,)))

    for event in event_list:
        process = event.process

        if event.event_type is GuardianEventKind.PROCESS_EXEC and process is not None:
            parent_id = process.parent_process_id
            if parent_id and parent_id != process.process_id:
                if parent_id not in nodes:
                    add_node(_placeholder_process_node(parent_id, (event.event_id,)))
                edge = relationship(
                    nodes[parent_id],
                    nodes[process.process_id],
                    relation="process-parent-of-process",
                    strength=RelationStrength.PROVEN,
                    reason=(
                        "kernel observation carries an exact parent exec identity "
                        "for this stable process instance"
                    ),
                    proof="kernel-observed-process-parentage",
                    evidence_ids=(event.event_id,),
                )
                add_edge(edge)
            continue

        if event.event_type is GuardianEventKind.FILE_WRITE_ACCESS and process is not None:
            path = event.target.get("path")
            if not isinstance(path, str) or not path:
                # The always-on Tetragon normalizer should have filtered this.
                # Refuse to invent a file identity if a malformed event arrives.
                raise ValueError("file write-access event lacks an exact path")
            file_node = CausalNode(
                node_id=_path_node_id(path),
                kind="file",
                subject=path,
                evidence_ids=(event.event_id,),
                attributes={
                    "path": path,
                    "permission": event.target.get("permission"),
                },
            )
            add_node(file_node)
            add_edge(relationship(
                nodes[process.process_id],
                nodes[file_node.node_id],
                relation="process-requested-file-write-access",
                strength=RelationStrength.PROVEN,
                reason=(
                    "kernel sensor observed this stable process at the file "
                    "permission hook with MAY_WRITE/MAY_APPEND; this proves "
                    "write access activity, not a completed content mutation"
                ),
                proof="kernel-observed-file-write-access",
                evidence_ids=(event.event_id,),
            ))
            continue

        if event.event_type is GuardianEventKind.NETWORK_CONNECT_ATTEMPT and process is not None:
            connection_id = _connection_node_id(event)
            destination_address = event.target.get("destination_address")
            destination_port = event.target.get("destination_port")
            subject = (
                f"{destination_address}:{destination_port}"
                if destination_address is not None and destination_port is not None
                else connection_id
            )
            connection_node = CausalNode(
                node_id=connection_id,
                kind="network-connection-attempt",
                subject=subject,
                evidence_ids=(event.event_id,),
                attributes=dict(event.target),
            )
            add_node(connection_node)
            add_edge(relationship(
                nodes[process.process_id],
                nodes[connection_node.node_id],
                relation="process-attempted-network-connect",
                strength=RelationStrength.PROVEN,
                reason=(
                    "kernel sensor observed tcp_connect for this stable process "
                    "instance; this proves a connection attempt, not successful "
                    "session establishment"
                ),
                proof="kernel-observed-network-connect-attempt",
                evidence_ids=(event.event_id,),
            ))
            continue

        # Process exits and sensor coverage events are still valuable timeline
        # evidence, but they do not create additional causal edges here.

    return CausalGraph(
        nodes=tuple(sorted(nodes.values(), key=lambda node: node.node_id)),
        edges=tuple(sorted(edges.values(), key=lambda edge: edge.edge_id)),
    )
