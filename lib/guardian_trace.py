#!/usr/bin/env python3
"""Reconstruct bounded Guardian traces from normalized historical events."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Iterable

from guardian_evidence import parse_timestamp
from guardian_event import GuardianEvent, GuardianEventKind
from guardian_event_ledger import GuardianEventLedger, ledger_path
from guardian_event_projection import project_guardian_events


class TraceCoverage(str, Enum):
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class GuardianTrace:
    trace_id: str
    anchor_event_id: str
    boot_id: str
    window_start: str
    window_end: str
    coverage: TraceCoverage
    coverage_event_ids: tuple[str, ...]
    truncated: bool
    process_ids: tuple[str, ...]
    events: tuple[GuardianEvent, ...]

    def as_dict(self) -> dict[str, object]:
        graph = project_guardian_events(self.events)
        return {
            "schema_version": 1,
            "kind": "guardian-trace",
            "trace_id": self.trace_id,
            "anchor_event_id": self.anchor_event_id,
            "boot_id": self.boot_id,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "coverage": self.coverage.value,
            "coverage_event_ids": list(self.coverage_event_ids),
            "truncated": self.truncated,
            "process_ids": list(self.process_ids),
            "event_count": len(self.events),
            "events": [event.as_dict() for event in self.events],
            "graph": graph.as_dict(),
        }


def _stamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _trace_id(
    anchor_event_id: str,
    window_start: str,
    window_end: str,
    event_ids: Iterable[str],
) -> str:
    material = "\0".join(
        (anchor_event_id, window_start, window_end, *sorted(event_ids))
    ).encode("utf-8")
    return "gtrace-" + hashlib.sha256(material).hexdigest()[:32]


def _related_process_ids(
    events: tuple[GuardianEvent, ...],
    seed_process_id: str,
) -> set[str]:
    parent_by_child: dict[str, str] = {}
    children_by_parent: dict[str, set[str]] = {}

    for event in events:
        process = event.process
        if (
            event.event_type is not GuardianEventKind.PROCESS_EXEC
            or process is None
            or not process.parent_process_id
            or process.parent_process_id == process.process_id
        ):
            continue
        parent_by_child[process.process_id] = process.parent_process_id
        children_by_parent.setdefault(process.parent_process_id, set()).add(
            process.process_id
        )

    related = {seed_process_id}

    # Walk ancestors only along the seed's own lineage. Do not add siblings
    # merely because an ancestor launched other processes in the same window.
    cursor = seed_process_id
    seen: set[str] = set()
    while cursor not in seen:
        seen.add(cursor)
        parent = parent_by_child.get(cursor)
        if parent is None:
            break
        related.add(parent)
        cursor = parent

    # Walk descendants only from the seed. Ancestors are context, not new
    # roots for descendant expansion.
    pending = [seed_process_id]
    visited: set[str] = set()
    while pending:
        parent = pending.pop()
        if parent in visited:
            continue
        visited.add(parent)
        for child in children_by_parent.get(parent, ()):
            if child not in related:
                related.add(child)
            pending.append(child)

    return related


def trace_around_event(
    ledger: GuardianEventLedger,
    event_id: str,
    *,
    before_seconds: float = 30.0,
    after_seconds: float = 30.0,
    max_window_events: int = 10000,
) -> GuardianTrace:
    if before_seconds < 0 or after_seconds < 0:
        raise ValueError("trace window cannot be negative")
    if max_window_events < 1 or max_window_events > 10000:
        raise ValueError("trace window event limit must be 1..10000")

    anchor = ledger.get(event_id)
    if anchor is None:
        raise KeyError(f"Guardian event not found: {event_id}")

    observed = parse_timestamp(anchor.observed_at)
    if observed is None:
        raise ValueError("anchor event timestamp is missing")

    window_start = _stamp(observed - timedelta(seconds=before_seconds))
    window_end = _stamp(observed + timedelta(seconds=after_seconds))

    window = ledger.query(
        boot_id=anchor.boot_id,
        since=window_start,
        until=window_end,
        limit=max_window_events,
    )
    truncated = len(window) == max_window_events

    coverage_events = tuple(
        event
        for event in window
        if event.event_type in {
            GuardianEventKind.OBSERVATION_GAP,
            GuardianEventKind.SENSOR_RESET,
        }
    )
    coverage = (
        TraceCoverage.INCOMPLETE
        if coverage_events
        else TraceCoverage.UNKNOWN
    )

    if anchor.process is None:
        selected = tuple(
            event
            for event in window
            if event.event_id == anchor.event_id
            or event.event_type in {
                GuardianEventKind.OBSERVATION_GAP,
                GuardianEventKind.SENSOR_RESET,
            }
        )
        process_ids: set[str] = set()
    else:
        process_ids = _related_process_ids(window, anchor.process.process_id)
        selected = tuple(
            event
            for event in window
            if (
                event.process is not None
                and event.process.process_id in process_ids
            )
            or event.event_type in {
                GuardianEventKind.OBSERVATION_GAP,
                GuardianEventKind.SENSOR_RESET,
            }
        )

    # The anchor is a hard invariant even if a future query implementation
    # changes its filtering behavior.
    if all(event.event_id != anchor.event_id for event in selected):
        selected = tuple(sorted(
            (*selected, anchor),
            key=lambda event: (parse_timestamp(event.observed_at), event.event_id),
        ))

    trace_id = _trace_id(
        anchor.event_id,
        window_start,
        window_end,
        (event.event_id for event in selected),
    )

    return GuardianTrace(
        trace_id=trace_id,
        anchor_event_id=anchor.event_id,
        boot_id=anchor.boot_id,
        window_start=window_start,
        window_end=window_end,
        coverage=coverage,
        coverage_event_ids=tuple(event.event_id for event in coverage_events),
        truncated=truncated,
        process_ids=tuple(sorted(process_ids)),
        events=selected,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guardian_trace.py")
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--before-seconds", type=float, default=30.0)
    parser.add_argument("--after-seconds", type=float, default=30.0)
    parser.add_argument("--max-window-events", type=int, default=10000)
    args = parser.parse_args(argv)

    with GuardianEventLedger(ledger_path(args.state_root)) as ledger:
        trace = trace_around_event(
            ledger,
            args.event_id,
            before_seconds=args.before_seconds,
            after_seconds=args.after_seconds,
            max_window_events=args.max_window_events,
        )
    print(json.dumps(trace.as_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
