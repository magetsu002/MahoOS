#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_event import GuardianEventKind
from guardian_event_ledger import GuardianEventLedger, ledger_path
from guardian_tetragon_sensor import TetragonCoverage, coverage_events, normalize_tetragon_event
from guardian_trace import TraceCoverage, trace_around_event

BOOT_ID = "12345678-1234-5678-9234-567812345678"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def proc(exec_id: str, parent: str, pid: int, binary: str, time: str) -> dict:
    return {
        "exec_id": exec_id,
        "parent_exec_id": parent,
        "pid": pid,
        "uid": 1000,
        "binary": binary,
        "start_time": time,
    }


def exec_event(exec_id: str, parent: str, pid: int, binary: str, time: str):
    return normalize_tetragon_event({
        "process_exec": {
            "process": proc(exec_id, parent, pid, binary, time),
        },
        "time": time,
    }, boot_id=BOOT_ID)[0]


def write_event(process: dict, path: str, time: str):
    return normalize_tetragon_event({
        "process_kprobe": {
            "process": process,
            "function_name": "security_file_permission",
            "args": [
                {"file_arg": {"path": path, "permission": "-rw-------"}},
                {"int_arg": 2},
            ],
        },
        "time": time,
    }, boot_id=BOOT_ID)[0]


def network_event(process: dict, time: str):
    return normalize_tetragon_event({
        "process_kprobe": {
            "process": process,
            "function_name": "tcp_connect",
            "args": [{
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
        },
        "time": time,
    }, boot_id=BOOT_ID)[0]


def main() -> None:
    t0 = "2026-10-07T15:43:20.000000Z"
    t1 = "2026-10-07T15:43:21.000000Z"
    t2 = "2026-10-07T15:43:22.000000Z"
    t3 = "2026-10-07T15:43:23.000000Z"
    t4 = "2026-10-07T15:43:24.000000Z"
    t5 = "2026-10-07T15:43:25.000000Z"

    parent = exec_event("parent", "grandparent", 4000, "/usr/bin/parent", t0)
    child = exec_event("child", "parent", 4100, "/usr/bin/child", t1)
    sibling = exec_event("sibling", "parent", 4200, "/usr/bin/sibling", t1)
    grandchild = exec_event("grandchild", "child", 4300, "/usr/bin/grandchild", t2)

    child_proc = proc("child", "parent", 4100, "/usr/bin/child", t1)
    grandchild_proc = proc("grandchild", "child", 4300, "/usr/bin/grandchild", t2)
    sibling_proc = proc("sibling", "parent", 4200, "/usr/bin/sibling", t1)

    child_write = write_event(child_proc, "/tmp/child.txt", t3)
    grandchild_net = network_event(grandchild_proc, t4)
    sibling_write = write_event(sibling_proc, "/tmp/sibling.txt", t3)

    gap = coverage_events(
        TetragonCoverage(100, 0, 0),
        TetragonCoverage(150, 1, 0),
        boot_id=BOOT_ID,
        observed_at=t5,
    )[0]

    with tempfile.TemporaryDirectory() as tmp:
        state_root = Path(tmp)
        with GuardianEventLedger(ledger_path(state_root)) as ledger:
            ledger.append((
                parent,
                child,
                sibling,
                grandchild,
                child_write,
                sibling_write,
                grandchild_net,
                gap,
            ))

            trace = trace_around_event(
                ledger,
                child_write.event_id,
                before_seconds=10,
                after_seconds=10,
            )
            payload = trace.as_dict()

            check("trace includes anchor", payload["anchor_event_id"] == child_write.event_id)
            check("trace includes seed parent ancestry",
                  parent.process.process_id in trace.process_ids)
            check("trace includes seed descendants",
                  grandchild.process.process_id in trace.process_ids)
            check("trace does not pull sibling activity through common parent",
                  sibling.process.process_id not in trace.process_ids)

            event_ids = {event.event_id for event in trace.events}
            check("trace includes child write activity", child_write.event_id in event_ids)
            check("trace includes descendant network activity", grandchild_net.event_id in event_ids)
            check("trace excludes sibling file activity", sibling_write.event_id not in event_ids)

            relations = {edge["relation"] for edge in payload["graph"]["edges"]}
            check("trace graph reconstructs process lineage",
                  "process-parent-of-process" in relations)
            check("trace graph reconstructs file interaction",
                  "process-requested-file-write-access" in relations)
            check("trace graph reconstructs network attempt",
                  "process-attempted-network-connect" in relations)

            check("sensor gap makes trace explicitly incomplete",
                  trace.coverage is TraceCoverage.INCOMPLETE
                  and gap.event_id in trace.coverage_event_ids)

            trace_again = trace_around_event(
                ledger,
                child_write.event_id,
                before_seconds=10,
                after_seconds=10,
            )
            check("trace identity is deterministic", trace.trace_id == trace_again.trace_id)

            no_gap = trace_around_event(
                ledger,
                child_write.event_id,
                before_seconds=4,
                after_seconds=1,
            )
            check("absence of a gap does not invent complete coverage",
                  no_gap.coverage is TraceCoverage.UNKNOWN)

            small = trace_around_event(
                ledger,
                child_write.event_id,
                before_seconds=10,
                after_seconds=10,
                max_window_events=2,
            )
            check("bounded query reports possible truncation", small.truncated is True)

            try:
                trace_around_event(ledger, "gev-" + "0" * 32)
            except KeyError:
                pass
            else:
                raise AssertionError("missing trace anchor was accepted")
            check("missing trace anchor fails explicitly", True)

    print("ALL GUARDIAN TRACE TESTS PASS")


if __name__ == "__main__":
    main()
