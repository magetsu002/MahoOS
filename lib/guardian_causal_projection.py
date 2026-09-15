#!/usr/bin/env python3
"""Read-only causal projection from existing durable security incidents."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from guardian_causality import (
    CausalEdge,
    CausalGraph,
    CausalNode,
    RelationStrength,
    file_process_edge,
    package_file_edge,
    process_listener_edge,
    relationship,
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _clean_exe(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("/"):
        return None
    return value[:-10] if value.endswith(" (deleted)") else value


def load_active_security_incidents(
    security_root: Path,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    active = security_root / "incidents/active"
    if not active.is_dir():
        return [], ()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(active.glob("inc-*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            errors.append(path.name)
            continue
        if not isinstance(value, dict) or not isinstance(value.get("incident_id"), str):
            errors.append(path.name)
            continue
        rows.append(value)
    return rows, tuple(errors)


def project_security_causality(
    incidents: Iterable[Mapping[str, Any]],
) -> CausalGraph:
    nodes: dict[str, CausalNode] = {}
    edges: dict[str, CausalEdge] = {}

    def add_node(node: CausalNode) -> CausalNode:
        existing = nodes.get(node.node_id)
        if existing is None:
            nodes[node.node_id] = node
            return node
        return existing

    def add_edge(edge: CausalEdge) -> None:
        edges.setdefault(edge.edge_id, edge)

    for incident in incidents:
        iid = str(incident.get("incident_id") or "")
        if not iid:
            continue
        subject = _mapping(incident.get("subject"))
        subject_type = str(subject.get("type") or "unknown")
        subject_id = str(subject.get("id") or "unknown")
        subject_node = add_node(CausalNode(
            f"subject:{subject_type}:{subject_id}",
            subject_type,
            subject_id,
            (f"incident:{iid}:subject",),
            {"incident_id": iid},
        ))

        raw_signals = incident.get("signals")
        signals = raw_signals if isinstance(raw_signals, list) else []
        process_nodes: dict[int, CausalNode] = {}

        for sidx, raw_signal in enumerate(signals):
            signal = _mapping(raw_signal)
            kind = str(signal.get("kind") or "")
            source = str(signal.get("source") or "unknown")
            details = _mapping(signal.get("details"))
            evidence_id = f"incident:{iid}:signal:{sidx}:{kind}"

            if kind == "integrity-drift" and subject_type == "package" and source == "pacman-mtree":
                items = details.get("items") if isinstance(details.get("items"), list) else []
                for idx, raw_item in enumerate(items):
                    item = _mapping(raw_item)
                    path = item.get("path")
                    package = item.get("package")
                    if not isinstance(path, str) or not path.startswith("/"):
                        continue
                    if not isinstance(package, str):
                        continue
                    item_evidence = f"{evidence_id}:item:{idx}"
                    file_node = add_node(CausalNode(
                        f"file:{path}", "file", path, (item_evidence,),
                        {"integrity_class": item.get("class"), "package": package},
                    ))
                    add_edge(package_file_edge(
                        subject_node,
                        file_node,
                        package_identity=subject_id,
                        observed_package=package,
                        file_path=path,
                        evidence_id=item_evidence,
                    ))

            if kind in {"runtime-executable", "affected-package-process"}:
                observations = details.get("observations")
                if not isinstance(observations, list):
                    observations = details.get("processes") if isinstance(details.get("processes"), list) else []
                for idx, raw_proc in enumerate(observations):
                    proc = _mapping(raw_proc)
                    pid = proc.get("pid")
                    exe = _clean_exe(proc.get("exe"))
                    if not isinstance(pid, int) or exe is None:
                        continue
                    proc_evidence = f"{evidence_id}:process:{idx}"
                    proc_node = add_node(CausalNode(
                        f"process:pid:{pid}:{exe}", "process", f"pid={pid}",
                        (proc_evidence,),
                        {"pid": pid, "exe": exe, "stable_identity": False},
                    ))
                    process_nodes[pid] = proc_node
                    file_node = add_node(CausalNode(
                        f"file:{exe}", "file", exe, (proc_evidence,),
                    ))
                    add_edge(file_process_edge(
                        file_node,
                        proc_node,
                        file_path=exe,
                        process_exe=exe,
                        executable_identity_verified=False,
                        process_identity_stable=False,
                        evidence_ids=(proc_evidence,),
                    ))
                    if subject_type == "package":
                        add_edge(relationship(
                            subject_node,
                            proc_node,
                            relation="package-associated-with-process",
                            strength=RelationStrength.CORRELATED,
                            reason="incident correlation mapped this executable path to the package, but stable process identity is absent",
                            proof="same-package-path",
                            evidence_ids=(proc_evidence,),
                        ))

            if kind == "network-exposure":
                listeners = details.get("listeners") if isinstance(details.get("listeners"), list) else []
                for idx, raw_listener in enumerate(listeners):
                    listener = _mapping(raw_listener)
                    pid = listener.get("pid")
                    address = listener.get("address") or listener.get("local") or listener.get("endpoint")
                    if not isinstance(address, str) or not address:
                        address = f"listener:{idx}"
                    listener_evidence = f"{evidence_id}:listener:{idx}"
                    listener_node = add_node(CausalNode(
                        f"listener:{iid}:{idx}:{address}",
                        "listener",
                        address,
                        (listener_evidence,),
                        dict(listener),
                    ))
                    proc_node = process_nodes.get(pid) if isinstance(pid, int) else None
                    if proc_node is None and isinstance(pid, int):
                        exe = _clean_exe(listener.get("exe")) or "unknown"
                        proc_node = add_node(CausalNode(
                            f"process:pid:{pid}:{exe}", "process", f"pid={pid}",
                            (listener_evidence,),
                            {"pid": pid, "exe": exe, "stable_identity": False},
                        ))
                    if proc_node is not None:
                        add_edge(process_listener_edge(
                            proc_node,
                            listener_node,
                            socket_owner_verified=False,
                            same_process_identity=True,
                            evidence_ids=(listener_evidence,),
                        ))
                    elif subject_type == "package":
                        add_edge(relationship(
                            subject_node,
                            listener_node,
                            relation="package-listener-relationship",
                            strength=RelationStrength.UNKNOWN,
                            reason="network exposure is present but exact socket/process ownership is unavailable",
                            proof="listener-owner-unknown",
                        ))

            if kind == "persistence-drift":
                for change_class in ("added", "changed", "removed"):
                    values = details.get(change_class) if isinstance(details.get(change_class), list) else []
                    for idx, raw_item in enumerate(values):
                        item = _mapping(raw_item)
                        path = item.get("path")
                        if not isinstance(path, str) or not path.startswith("/"):
                            continue
                        persistence = add_node(CausalNode(
                            f"persistence:{path}", "persistence", path,
                            (f"{evidence_id}:{change_class}:{idx}",),
                            {"change": change_class, **dict(item)},
                        ))
                        add_edge(relationship(
                            subject_node,
                            persistence,
                            relation="subject-persistence-relationship",
                            strength=RelationStrength.UNKNOWN,
                            reason="persistence drift is observed, but this subject is not proven to have caused it",
                            proof="persistence-cause-unknown",
                        ))

    return CausalGraph(
        tuple(sorted(nodes.values(), key=lambda node: node.node_id)),
        tuple(sorted(edges.values(), key=lambda edge: edge.edge_id)),
    )
