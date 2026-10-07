#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_event import GuardianEventKind
from guardian_event_ledger import GuardianEventLedger, ledger_path
from guardian_tetragon_sensor import normalize_tetragon_event

BOOT_ID = "12345678-1234-5678-9234-567812345678"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def process(exec_id: str, parent: str, pid: int, binary: str, started_at: str) -> dict:
    return {
        "exec_id": exec_id,
        "parent_exec_id": parent,
        "pid": pid,
        "uid": 1000,
        "binary": binary,
        "start_time": started_at,
        "arguments": "discard-me",
        "cwd": "/discard-me",
    }


def exec_event(exec_id: str, parent: str, pid: int, binary: str, time: str):
    raw = {
        "process_exec": {
            "process": process(exec_id, parent, pid, binary, time),
        },
        "time": time,
    }
    return normalize_tetragon_event(raw, boot_id=BOOT_ID)[0]


def file_event(proc: dict, path: str, time: str):
    raw = {
        "process_kprobe": {
            "process": proc,
            "function_name": "security_file_permission",
            "args": [
                {"file_arg": {"path": path, "permission": "-rw-------"}},
                {"int_arg": 2},
            ],
        },
        "time": time,
    }
    return normalize_tetragon_event(raw, boot_id=BOOT_ID)[0]


def main() -> None:
    t1 = "2026-10-07T15:43:25.100000Z"
    t2 = "2026-10-07T15:43:26.200000Z"
    t3 = "2026-10-07T15:43:27.300000Z"
    t4 = "2026-10-07T15:43:28.400000Z"

    parent = exec_event("parent", "grandparent", 4000, "/usr/bin/parent", t1)
    child = exec_event("child", "parent", 4242, "/usr/bin/child", t2)
    child_proc = process("child", "parent", 4242, "/usr/bin/child", t2)
    write_one = file_event(child_proc, "/tmp/one", t3)
    write_two = file_event(child_proc, "/tmp/two", t4)

    with tempfile.TemporaryDirectory() as tmp:
        state_root = Path(tmp)
        path = ledger_path(state_root)
        with GuardianEventLedger(path) as ledger:
            inserted = ledger.append((parent, child, write_one, write_two))
            check("batch append stores all new events", inserted == 4)
            check("duplicate event IDs are idempotent",
                  ledger.append((child, write_one)) == 0)

            round_trip = ledger.get(write_one.event_id)
            check("event round trip preserves identity",
                  round_trip is not None
                  and round_trip.as_dict() == write_one.as_dict())

            process_rows = ledger.query(process_id=child.process.process_id)
            check("process query returns its lifecycle and file activity",
                  len(process_rows) == 3
                  and {event.event_type for event in process_rows}
                  == {GuardianEventKind.PROCESS_EXEC, GuardianEventKind.FILE_WRITE_ACCESS})

            file_rows = ledger.query(event_types=(GuardianEventKind.FILE_WRITE_ACCESS,))
            check("event-type query is indexed and bounded",
                  len(file_rows) == 2
                  and all(event.event_type is GuardianEventKind.FILE_WRITE_ACCESS
                          for event in file_rows))

            window = ledger.query(since=t2, until=t3)
            check("time-window query is inclusive", [e.event_id for e in window] == [
                child.event_id, write_one.event_id
            ])

            newest = ledger.query(limit=2, newest_first=True)
            check("newest-first query orders by observation time",
                  [e.event_id for e in newest] == [write_two.event_id, write_one.event_id])

            stats = ledger.stats()
            check("ledger stats expose bounded historical counts",
                  stats["event_count"] == 4
                  and stats["boot_count"] == 1
                  and stats["process_count"] == 2)

            removed = ledger.prune(max_events=2)
            check("count retention keeps only newest events", removed == 2)
            check("count retention result is queryable",
                  [e.event_id for e in ledger.query()] == [
                      write_one.event_id, write_two.event_id
                  ])

            removed = ledger.prune(before=t4)
            check("time retention prunes events strictly before cutoff", removed == 1)
            check("retention preserves cutoff event",
                  [e.event_id for e in ledger.query()] == [write_two.event_id])

        dir_mode = stat.S_IMODE(path.parent.stat().st_mode)
        file_mode = stat.S_IMODE(path.stat().st_mode)
        check("ledger directory is private", dir_mode == 0o700)
        check("ledger database is private", file_mode == 0o600)

    print("ALL GUARDIAN EVENT LEDGER TESTS PASS")


if __name__ == "__main__":
    main()
