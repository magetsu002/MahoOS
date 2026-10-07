#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_causality import RelationStrength
from guardian_event_projection import project_guardian_events
from guardian_tetragon_sensor import TetragonCoverage, coverage_events, normalize_tetragon_event

BOOT_ID = "12345678-1234-5678-9234-567812345678"
TIME = "2026-10-07T15:43:25.979229472Z"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def proc(exec_id: str, parent: str, pid: int, binary: str) -> dict:
    return {
        "exec_id": exec_id,
        "parent_exec_id": parent,
        "pid": pid,
        "uid": 1000,
        "binary": binary,
        "start_time": TIME,
        "arguments": "discard-me",
        "cwd": "/discard-me",
    }


def exec_raw(exec_id: str, parent: str, pid: int, binary: str) -> dict:
    return {
        "process_exec": {
            "process": proc(exec_id, parent, pid, binary),
        },
        "time": TIME,
        "node_name": "fixture",
    }


def kprobe_raw(process: dict, function_name: str, args: list[dict]) -> dict:
    return {
        "process_kprobe": {
            "process": process,
            "function_name": function_name,
            "args": args,
            "policy_name": "guardian-observe",
        },
        "time": TIME,
        "node_name": "fixture",
    }


def main() -> None:
    parent_raw = exec_raw("exec-parent", "exec-grandparent", 4000, "/usr/bin/parent")
    child_raw = exec_raw("exec-child", "exec-parent", 4242, "/usr/bin/child")
    child_process = child_raw["process_exec"]["process"]

    file_raw = kprobe_raw(
        child_process,
        "security_file_permission",
        [
            {"file_arg": {"path": "/tmp/example.txt", "permission": "-rw-------"}},
            {"int_arg": 2},
        ],
    )
    network_raw = kprobe_raw(
        child_process,
        "tcp_connect",
        [{
            "sock_arg": {
                "family": "AF_INET",
                "type": "SOCK_STREAM",
                "protocol": "IPPROTO_TCP",
                "saddr": "127.0.0.1",
                "daddr": "127.0.0.1",
                "sport": 41000,
                "dport": 8443,
                "cookie": "123456789",
            },
        }],
    )

    events = []
    for raw in (parent_raw, child_raw, file_raw, network_raw):
        events.extend(normalize_tetragon_event(raw, boot_id=BOOT_ID))

    gap = coverage_events(
        TetragonCoverage(100, 0, 0),
        TetragonCoverage(120, 2, 0),
        boot_id=BOOT_ID,
        observed_at=TIME,
    )[0]
    events.append(gap)

    graph = project_guardian_events(events)
    payload = graph.as_dict()

    check("all projected edges are backed by direct evidence",
          payload["counts"]["proven"] == 4
          and payload["counts"]["correlated"] == 0
          and payload["counts"]["unknown"] == 0)

    relations = {edge["relation"]: edge for edge in payload["edges"]}
    check("kernel process parentage becomes a proven relationship",
          "process-parent-of-process" in relations
          and relations["process-parent-of-process"]["strength"] == "proven")

    file_edge = relations["process-requested-file-write-access"]
    check("file hook proves write-access activity",
          file_edge["proof"] == "kernel-observed-file-write-access"
          and file_edge["strength"] == RelationStrength.PROVEN.value)
    check("file hook does not claim completed mutation",
          "not a completed content mutation" in file_edge["reason"]
          and "process-wrote-file" not in relations)

    network_edge = relations["process-attempted-network-connect"]
    check("tcp hook proves only the connect attempt",
          network_edge["proof"] == "kernel-observed-network-connect-attempt"
          and "not successful session establishment" in network_edge["reason"])

    check("coverage gap is timeline evidence not fake causality",
          all(edge["proof"] != "sensor.observation-gap" for edge in payload["edges"]))

    process_nodes = [node for node in payload["nodes"] if node["kind"] == "process"]
    parent = next(node for node in process_nodes if node["attributes"].get("pid") == 4000)
    check("parent placeholder is enriched by its own process event",
          parent["attributes"]["details_known"] is True
          and parent["attributes"]["binary"] == "/usr/bin/parent")

    child = next(node for node in process_nodes if node["attributes"].get("pid") == 4242)
    check("stable process identity carries multiple evidence records",
          len(child["evidence_ids"]) >= 3)

    # Conflicting sensor identity must fail rather than silently merge two
    # different processes under one stable ID.
    conflict_raw = exec_raw("exec-child", "exec-parent", 9999, "/usr/bin/other")
    conflict = normalize_tetragon_event(conflict_raw, boot_id=BOOT_ID)[0]
    try:
        project_guardian_events((*events, conflict))
    except ValueError:
        pass
    else:
        raise AssertionError("conflicting stable process identity was accepted")
    check("conflicting stable process identity fails closed", True)

    print("ALL GUARDIAN EVENT PROJECTION TESTS PASS")


if __name__ == "__main__":
    main()
