#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_event import GuardianEventKind
from guardian_tetragon_sensor import (
    TetragonCoverage,
    coverage_events,
    normalize_tetragon_event,
    normalize_stream,
    parse_metrics,
)

BOOT_ID = "12345678-1234-5678-9234-567812345678"
TIME = "2026-10-07T15:43:25.979229472Z"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def process(
    *,
    exec_id: str = "exec-child",
    parent_exec_id: str = "exec-parent",
    binary: str = "/usr/bin/example",
    pid: int = 4242,
) -> dict:
    return {
        "exec_id": exec_id,
        "parent_exec_id": parent_exec_id,
        "pid": pid,
        "uid": 1000,
        "binary": binary,
        "start_time": TIME,
        "arguments": "--password super-secret-token",
        "cwd": "/home/user/private-project",
    }


def process_event(kind: str) -> dict:
    return {
        kind: {
            "process": process(),
            "parent": process(
                exec_id="exec-parent",
                parent_exec_id="exec-grandparent",
                binary="/usr/bin/parent",
                pid=4000,
            ),
        },
        "node_name": "example-host",
        "time": TIME,
    }


def kprobe(function_name: str, args: list[dict]) -> dict:
    return {
        "process_kprobe": {
            "process": process(),
            "function_name": function_name,
            "args": args,
            "policy_name": "guardian-observe",
        },
        "node_name": "example-host",
        "time": TIME,
    }


def main() -> None:
    exec_raw = process_event("process_exec")
    first = normalize_tetragon_event(exec_raw, boot_id=BOOT_ID)
    second = normalize_tetragon_event(exec_raw, boot_id=BOOT_ID)
    check("process exec normalizes to one event", len(first) == 1)
    event = first[0]
    check("process exec kind is preserved", event.event_type is GuardianEventKind.PROCESS_EXEC)
    check("event identity is deterministic", event.event_id == second[0].event_id)
    check("stable provider identity becomes a Guardian process identity",
          event.process is not None and event.process.process_id.startswith("gproc-"))
    check("parent identity is preserved independently",
          event.process is not None and event.process.parent_process_id is not None
          and event.process.parent_process_id != event.process.process_id)
    check("sensor event is observation-only", event.authority_boundary == "observation-only")

    serialized = json.dumps(event.as_dict(), sort_keys=True)
    check("command arguments are not retained", "super-secret-token" not in serialized)
    check("working directory is not retained", "private-project" not in serialized)

    changed_secret = process_event("process_exec")
    changed_secret["process_exec"]["process"]["arguments"] = "--password another-secret"
    changed_secret["process_exec"]["process"]["cwd"] = "/home/user/another-private-path"
    changed_event = normalize_tetragon_event(changed_secret, boot_id=BOOT_ID)[0]
    check("event identity does not fingerprint discarded secrets",
          changed_event.event_id == event.event_id
          and changed_event.source_record_digest == event.source_record_digest)

    exit_event = normalize_tetragon_event(process_event("process_exit"), boot_id=BOOT_ID)[0]
    check("process exit kind is normalized", exit_event.event_type is GuardianEventKind.PROCESS_EXIT)

    write_raw = kprobe(
        "security_file_permission",
        [
            {"file_arg": {"path": "/tmp/example.txt", "permission": "-rw-------"}},
            {"int_arg": 2},
        ],
    )
    write_event = normalize_tetragon_event(write_raw, boot_id=BOOT_ID)[0]
    check("file write is normalized", write_event.event_type is GuardianEventKind.FILE_WRITE_ACCESS)
    check("file target is retained", write_event.target["path"] == "/tmp/example.txt")
    check("write mask is named", write_event.target["access"] == ["write"])

    append_raw = kprobe(
        "security_file_permission",
        [
            {"file_arg": {"path": "/tmp/example.txt", "permission": "-rw-------"}},
            {"int_arg": 8},
        ],
    )
    append_event = normalize_tetragon_event(append_raw, boot_id=BOOT_ID)[0]
    check("append permission is mutation evidence", append_event.target["access"] == ["append"])

    unknown_path_raw = kprobe(
        "security_file_permission",
        [
            {"file_arg": {"permission": "prw-------"}},
            {"int_arg": 2},
        ],
    )
    check("pathless pipe/FIFO writes stay out of the bounded always-on ledger",
          normalize_tetragon_event(unknown_path_raw, boot_id=BOOT_ID) == ())

    read_raw = kprobe(
        "security_file_permission",
        [
            {"file_arg": {"path": "/etc/example", "permission": "-r--r--r--"}},
            {"int_arg": 4},
        ],
    )
    check("read-only file activity is excluded from always-on ledger",
          normalize_tetragon_event(read_raw, boot_id=BOOT_ID) == ())

    network_raw = kprobe(
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
                "cookie": "18446600000000000000",
            },
        }],
    )
    network_event = normalize_tetragon_event(network_raw, boot_id=BOOT_ID)[0]
    check("TCP connection is normalized",
          network_event.event_type is GuardianEventKind.NETWORK_CONNECT_ATTEMPT)
    check("socket identity is Maho-owned not raw provider cookie",
          network_event.target["socket_id"].startswith("gsock-")
          and "184466" not in network_event.target["socket_id"])
    check("network destination is retained",
          network_event.target["destination_address"] == "127.0.0.1"
          and network_event.target["destination_port"] == 8443)

    check("unknown kprobe is ignored rather than invented",
          normalize_tetragon_event(kprobe("unknown_hook", []), boot_id=BOOT_ID) == ())

    try:
        broken = process_event("process_exec")
        del broken["process_exec"]["process"]["exec_id"]
        normalize_tetragon_event(broken, boot_id=BOOT_ID)
    except ValueError:
        pass
    else:
        raise AssertionError("missing stable process identity was accepted")
    check("missing stable process identity fails closed", True)

    stream = "\n".join((json.dumps(exec_raw), json.dumps(write_raw), ""))
    normalized = list(normalize_stream(stream.splitlines(), boot_id=BOOT_ID))
    check("stream normalization preserves bounded events", len(normalized) == 2)

    metrics = """
# HELP tetragon_observer_ringbuf_events_lost_total lost
tetragon_observer_ringbuf_events_lost_total 0
tetragon_observer_ringbuf_events_received_total 250
tetragon_observer_ringbuf_queue_events_lost_total 0
"""
    coverage = parse_metrics(metrics)
    check("coverage metrics parse", coverage == TetragonCoverage(250, 0, 0))
    check("no loss produces no fake gap",
          coverage_events(TetragonCoverage(200, 0, 0), coverage,
                          boot_id=BOOT_ID, observed_at=TIME) == ())

    gap = coverage_events(
        TetragonCoverage(250, 1, 2),
        TetragonCoverage(400, 4, 3),
        boot_id=BOOT_ID,
        observed_at=TIME,
    )[0]
    check("loss counters become explicit observation gap",
          gap.event_type is GuardianEventKind.OBSERVATION_GAP)
    check("gap records exact lost-event deltas",
          gap.target["lost_events"] == 3 and gap.target["queue_lost_events"] == 1)
    check("gap never claims continuity",
          gap.target["continuity_proven"] is False)

    reset = coverage_events(
        TetragonCoverage(400, 4, 3),
        TetragonCoverage(10, 0, 0),
        boot_id=BOOT_ID,
        observed_at=TIME,
    )[0]
    check("counter reset is not mistaken for healthy continuity",
          reset.event_type is GuardianEventKind.SENSOR_RESET
          and reset.target["continuity_proven"] is False)

    try:
        parse_metrics("tetragon_observer_ringbuf_events_lost_total 0\n")
    except ValueError:
        pass
    else:
        raise AssertionError("incomplete sensor coverage metrics were accepted")
    check("missing coverage metrics fail closed", True)

    print("ALL GUARDIAN TETRAGON SENSOR TESTS PASS")


if __name__ == "__main__":
    main()
