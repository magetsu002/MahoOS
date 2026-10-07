#!/usr/bin/env python3
"""Ingest Tetragon observations into Guardian's private event ledger."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Iterable, TextIO

from guardian_evidence import ProviderHealth, utc_stamp
from guardian_event_ledger import GuardianEventLedger, ledger_path
from guardian_provider_state import record_heartbeat
from guardian_tetragon_sensor import (
    AUTHORITY_BOUNDARY,
    PROVIDER_ID,
    SOURCE,
    TetragonCoverage,
    coverage_events,
    normalize_tetragon_event,
    parse_metrics,
)


@dataclass(frozen=True)
class TetragonIngestResult:
    raw_records: int
    normalized_events: int
    filtered_records: int
    inserted_events: int
    duplicate_events: int
    coverage_events: int
    provider_health: ProviderHealth
    coverage: str

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["provider_health"] = self.provider_health.value
        return payload


def _flush(ledger: GuardianEventLedger, batch: list) -> tuple[int, int]:
    if not batch:
        return 0, 0
    inserted = ledger.append(batch)
    duplicates = len(batch) - inserted
    batch.clear()
    return inserted, duplicates


def ingest_tetragon(
    lines: Iterable[str],
    *,
    ledger: GuardianEventLedger,
    boot_id: str,
    previous_coverage: TetragonCoverage | None = None,
    current_coverage: TetragonCoverage | None = None,
    observed_at: str | None = None,
    batch_size: int = 256,
) -> TetragonIngestResult:
    if batch_size < 1 or batch_size > 10000:
        raise ValueError("Tetragon ingest batch size must be 1..10000")
    if (previous_coverage is None) != (current_coverage is None):
        raise ValueError("coverage snapshots must be supplied as a pair")

    raw_records = 0
    normalized_events = 0
    filtered_records = 0
    inserted_events = 0
    duplicate_events = 0
    batch = []

    for line_number, line in enumerate(lines, start=1):
        text = line.strip()
        if not text:
            continue
        raw_records += 1
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Tetragon JSON on line {line_number}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Tetragon JSON line {line_number} is not an object")

        events = normalize_tetragon_event(payload, boot_id=boot_id)
        if not events:
            filtered_records += 1
            continue

        normalized_events += len(events)
        batch.extend(events)
        if len(batch) >= batch_size:
            inserted, duplicates = _flush(ledger, batch)
            inserted_events += inserted
            duplicate_events += duplicates

    inserted, duplicates = _flush(ledger, batch)
    inserted_events += inserted
    duplicate_events += duplicates

    coverage_event_count = 0
    health = ProviderHealth.UNKNOWN
    coverage_state = "unverified"

    if previous_coverage is not None and current_coverage is not None:
        stamp = observed_at or utc_stamp(datetime.now(timezone.utc))
        gap_events = coverage_events(
            previous_coverage,
            current_coverage,
            boot_id=boot_id,
            observed_at=stamp,
        )
        coverage_event_count = len(gap_events)
        if gap_events:
            inserted = ledger.append(gap_events)
            inserted_events += inserted
            duplicate_events += len(gap_events) - inserted
            health = ProviderHealth.DEGRADED
            coverage_state = "incomplete"
        else:
            health = ProviderHealth.HEALTHY
            coverage_state = "continuous"

    return TetragonIngestResult(
        raw_records=raw_records,
        normalized_events=normalized_events,
        filtered_records=filtered_records,
        inserted_events=inserted_events,
        duplicate_events=duplicate_events,
        coverage_events=coverage_event_count,
        provider_health=health,
        coverage=coverage_state,
    )


def _read_coverage(path: Path) -> TetragonCoverage:
    return parse_metrics(path.read_text(encoding="utf-8"))


def _boot_id(path: Path = Path("/proc/sys/kernel/random/boot_id")) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError("boot identity is unavailable")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guardian_tetragon_ingest.py")
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--boot-id")
    parser.add_argument("--metrics-before", type=Path)
    parser.add_argument("--metrics-after", type=Path)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args(argv)

    if (args.metrics_before is None) != (args.metrics_after is None):
        raise SystemExit("--metrics-before and --metrics-after must be supplied together")

    boot_id = args.boot_id or _boot_id()
    previous = _read_coverage(args.metrics_before) if args.metrics_before else None
    current = _read_coverage(args.metrics_after) if args.metrics_after else None

    handle: TextIO
    close = False
    if args.input:
        handle = args.input.open("r", encoding="utf-8")
        close = True
    else:
        handle = sys.stdin

    now = datetime.now(timezone.utc)
    try:
        with GuardianEventLedger(ledger_path(args.state_root)) as ledger:
            result = ingest_tetragon(
                handle,
                ledger=ledger,
                boot_id=boot_id,
                previous_coverage=previous,
                current_coverage=current,
                observed_at=utc_stamp(now),
                batch_size=args.batch_size,
            )
            stats = ledger.stats()
    except Exception as exc:
        record_heartbeat(
            args.state_root,
            provider_id=PROVIDER_ID,
            domain="system-observation",
            source=SOURCE,
            authority_boundary=AUTHORITY_BOUNDARY,
            success=False,
            health=ProviderHealth.FAILED,
            errors=(type(exc).__name__,),
            boot_id=boot_id,
            details={"error": str(exc)[:512]},
            now=now,
        )
        raise
    finally:
        if close:
            handle.close()

    heartbeat_errors: tuple[str, ...] = ()
    if result.coverage == "unverified":
        heartbeat_errors = ("coverage_metrics_missing",)
    elif result.coverage == "incomplete":
        heartbeat_errors = ("sensor_event_loss_observed",)

    record_heartbeat(
        args.state_root,
        provider_id=PROVIDER_ID,
        domain="system-observation",
        source=SOURCE,
        authority_boundary=AUTHORITY_BOUNDARY,
        success=True,
        health=result.provider_health,
        errors=heartbeat_errors,
        boot_id=boot_id,
        details={
            **result.as_dict(),
            "ledger_event_count": stats["event_count"],
        },
        now=now,
    )

    print(json.dumps({
        "result": result.as_dict(),
        "ledger": stats,
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
