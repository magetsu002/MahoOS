#!/usr/bin/env python3
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_evidence import ProviderHealth
from guardian_event import GuardianEventKind
from guardian_event_ledger import GuardianEventLedger, ledger_path
from guardian_provider_state import load_heartbeat
from guardian_tetragon_ingest import ingest_tetragon, main as ingest_main
from guardian_tetragon_sensor import TetragonCoverage

BOOT_ID = "12345678-1234-5678-9234-567812345678"
TIME = "2026-10-07T15:43:25.979229Z"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def process() -> dict:
    return {
        "exec_id": "exec-child",
        "parent_exec_id": "exec-parent",
        "pid": 4242,
        "uid": 1000,
        "binary": "/usr/bin/example",
        "start_time": TIME,
        "arguments": "discard-secret",
        "cwd": "/discard/private",
    }


def exec_raw() -> dict:
    return {
        "process_exec": {"process": process()},
        "time": TIME,
    }


def read_only_raw() -> dict:
    return {
        "process_kprobe": {
            "process": process(),
            "function_name": "security_file_permission",
            "args": [
                {"file_arg": {"path": "/etc/example", "permission": "-r--r--r--"}},
                {"int_arg": 4},
            ],
        },
        "time": TIME,
    }


def metrics(received: int, lost: int, queue_lost: int) -> str:
    return f"""
tetragon_observer_ringbuf_events_received_total {received}
tetragon_observer_ringbuf_events_lost_total {lost}
tetragon_observer_ringbuf_queue_events_lost_total {queue_lost}
"""


def main() -> None:
    lines = [
        json.dumps(exec_raw()),
        json.dumps(read_only_raw()),
        json.dumps(exec_raw()),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        state_root = Path(tmp)
        with GuardianEventLedger(ledger_path(state_root)) as ledger:
            result = ingest_tetragon(
                lines,
                ledger=ledger,
                boot_id=BOOT_ID,
                previous_coverage=TetragonCoverage(100, 0, 0),
                current_coverage=TetragonCoverage(120, 0, 0),
                observed_at=TIME,
                batch_size=2,
            )
            check("ingest counts raw records", result.raw_records == 3)
            check("ingest reports filtered bounded-scope records", result.filtered_records == 1)
            check("duplicate normalized events are idempotent",
                  result.normalized_events == 2
                  and result.inserted_events == 1
                  and result.duplicate_events == 1)
            check("zero loss marks coverage continuous",
                  result.provider_health is ProviderHealth.HEALTHY
                  and result.coverage == "continuous")
            check("ledger stores normalized event once", ledger.stats()["event_count"] == 1)

            degraded = ingest_tetragon(
                (),
                ledger=ledger,
                boot_id=BOOT_ID,
                previous_coverage=TetragonCoverage(120, 0, 0),
                current_coverage=TetragonCoverage(150, 2, 1),
                observed_at=TIME,
            )
            check("sensor loss degrades provider result",
                  degraded.provider_health is ProviderHealth.DEGRADED
                  and degraded.coverage == "incomplete"
                  and degraded.coverage_events == 1)
            gaps = ledger.query(event_types=(GuardianEventKind.OBSERVATION_GAP,))
            check("sensor loss becomes durable observation-gap evidence",
                  len(gaps) == 1
                  and gaps[0].target["lost_events"] == 2
                  and gaps[0].target["queue_lost_events"] == 1)

            unknown = ingest_tetragon(
                (),
                ledger=ledger,
                boot_id=BOOT_ID,
            )
            check("missing coverage proof remains unknown",
                  unknown.provider_health is ProviderHealth.UNKNOWN
                  and unknown.coverage == "unverified")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        input_path = root / "input.jsonl"
        before = root / "before.prom"
        after = root / "after.prom"
        input_path.write_text(json.dumps(exec_raw()) + "\n", encoding="utf-8")
        before.write_text(metrics(10, 0, 0), encoding="utf-8")
        after.write_text(metrics(20, 0, 0), encoding="utf-8")

        rc = ingest_main([
            "--state-root", str(root / "state"),
            "--input", str(input_path),
            "--boot-id", BOOT_ID,
            "--metrics-before", str(before),
            "--metrics-after", str(after),
        ])
        check("CLI ingest succeeds", rc == 0)
        heartbeat = load_heartbeat(root / "state", "guardian.sensor.tetragon")
        check("successful covered ingest records healthy provider heartbeat",
              heartbeat is not None
              and heartbeat.health is ProviderHealth.HEALTHY
              and heartbeat.last_success_at is not None
              and heartbeat.details["coverage"] == "continuous")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bad = root / "bad.jsonl"
        bad.write_text("{not-json}\n", encoding="utf-8")
        try:
            ingest_main([
                "--state-root", str(root / "state"),
                "--input", str(bad),
                "--boot-id", BOOT_ID,
            ])
        except ValueError:
            pass
        else:
            raise AssertionError("malformed sensor input was accepted")
        heartbeat = load_heartbeat(root / "state", "guardian.sensor.tetragon")
        check("failed ingest records failed provider health",
              heartbeat is not None
              and heartbeat.health is ProviderHealth.FAILED
              and heartbeat.last_success_at is None)

    print("ALL GUARDIAN TETRAGON INGEST TESTS PASS")


if __name__ == "__main__":
    main()
