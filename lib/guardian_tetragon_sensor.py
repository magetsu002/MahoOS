#!/usr/bin/env python3
"""Normalize Tetragon observations into Maho-owned GuardianEvent records.

Tetragon is treated as an external observation mechanism. This adapter does not
import Tetragon code, invoke Tetragon enforcement, or grant mutation authority.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping

from guardian_evidence import parse_timestamp, utc_stamp
from guardian_event import (
    GuardianEvent,
    GuardianEventKind,
    GuardianProcessRef,
    canonical_digest,
    event_identity,
    process_identity,
    socket_identity,
)

PROVIDER_ID = "guardian.sensor.tetragon"
SOURCE = "tetragon-json"
AUTHORITY_BOUNDARY = "observation-only"

# Linux MAY_* masks used by security_file_permission().
MAY_EXEC = 0x01
MAY_WRITE = 0x02
MAY_READ = 0x04
MAY_APPEND = 0x08

_METRIC = re.compile(
    r"^(tetragon_observer_ringbuf_(?:events_lost|queue_events_lost|events_received)_total)\s+([0-9]+(?:\.[0-9]+)?)$"
)


@dataclass(frozen=True)
class TetragonCoverage:
    received: int
    lost: int
    queue_lost: int

    def __post_init__(self) -> None:
        if min(self.received, self.lost, self.queue_lost) < 0:
            raise ValueError("Tetragon coverage counters must be non-negative")

    def as_dict(self) -> dict[str, int]:
        return {
            "received": self.received,
            "lost": self.lost,
            "queue_lost": self.queue_lost,
        }


def _process_ref(payload: Mapping[str, Any], *, boot_id: str) -> GuardianProcessRef:
    source_identity = payload.get("exec_id")
    pid = payload.get("pid")
    if not isinstance(source_identity, str) or not source_identity:
        raise ValueError("Tetragon process event is missing stable exec_id")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 0:
        raise ValueError("Tetragon process PID is invalid")

    uid = payload.get("uid")
    if uid is not None and (not isinstance(uid, int) or isinstance(uid, bool) or uid < 0):
        raise ValueError("Tetragon process UID is invalid")

    binary = payload.get("binary")
    if binary is not None and (not isinstance(binary, str) or not binary):
        raise ValueError("Tetragon process binary is invalid")

    started_at = payload.get("start_time")
    if started_at is not None:
        if not isinstance(started_at, str):
            raise ValueError("Tetragon process start time is invalid")
        parse_timestamp(started_at)

    parent_source = payload.get("parent_exec_id")
    if parent_source is not None and (not isinstance(parent_source, str) or not parent_source):
        raise ValueError("Tetragon parent exec identity is invalid")

    return GuardianProcessRef(
        process_id=process_identity(boot_id=boot_id, source_identity=source_identity),
        source_identity=source_identity,
        pid=pid,
        uid=uid,
        binary=binary,
        started_at=started_at,
        parent_process_id=(
            process_identity(boot_id=boot_id, source_identity=parent_source)
            if parent_source
            else None
        ),
    )


def _event(
    raw: Mapping[str, Any],
    *,
    event_type: GuardianEventKind,
    observed_at: str,
    boot_id: str,
    source_event_type: str,
    process: GuardianProcessRef | None,
    target_kind: str | None = None,
    target: Mapping[str, Any] | None = None,
) -> GuardianEvent:
    # Never make the retained event identity depend on raw command arguments or
    # working directories. Tetragon can include both and they may contain
    # secrets. The digest is over the bounded observation Guardian actually
    # retains, not the complete upstream record.
    target_payload = dict(target or {})
    digest = canonical_digest({
        "source_event_type": source_event_type,
        "observed_at": observed_at,
        "process": process.as_dict() if process else None,
        "target_kind": target_kind,
        "target": target_payload,
    })
    return GuardianEvent(
        event_id=event_identity(
            provider_id=PROVIDER_ID,
            boot_id=boot_id,
            observation_digest=digest,
            event_type=event_type,
        ),
        event_type=event_type,
        observed_at=observed_at,
        boot_id=boot_id,
        provider_id=PROVIDER_ID,
        source=SOURCE,
        source_event_type=source_event_type,
        observation_digest=digest,
        authority_boundary=AUTHORITY_BOUNDARY,
        process=process,
        target_kind=target_kind,
        target=target_payload,
    )


def _observed_at(raw: Mapping[str, Any], body: Mapping[str, Any]) -> str:
    value = raw.get("time") or body.get("time")
    if not isinstance(value, str) or not value:
        raise ValueError("Tetragon event timestamp is missing")
    parse_timestamp(value)
    return value


def _find_arg(args: object, key: str) -> object | None:
    if not isinstance(args, list):
        return None
    for item in args:
        if isinstance(item, Mapping) and key in item:
            return item[key]
    return None


def normalize_tetragon_event(raw: Mapping[str, Any], *, boot_id: str) -> tuple[GuardianEvent, ...]:
    if not isinstance(raw, Mapping):
        raise ValueError("Tetragon event must be an object")

    event_keys = [
        key
        for key in ("process_exec", "process_exit", "process_kprobe")
        if key in raw
    ]
    if len(event_keys) != 1:
        return ()

    source_event_type = event_keys[0]
    body = raw.get(source_event_type)
    if not isinstance(body, Mapping):
        raise ValueError("Tetragon event body is invalid")
    observed_at = _observed_at(raw, body)

    if source_event_type in {"process_exec", "process_exit"}:
        process_payload = body.get("process")
        if not isinstance(process_payload, Mapping):
            raise ValueError("Tetragon process payload is missing")
        process = _process_ref(process_payload, boot_id=boot_id)
        event_type = (
            GuardianEventKind.PROCESS_EXEC
            if source_event_type == "process_exec"
            else GuardianEventKind.PROCESS_EXIT
        )
        return (
            _event(
                raw,
                event_type=event_type,
                observed_at=observed_at,
                boot_id=boot_id,
                source_event_type=source_event_type,
                process=process,
            ),
        )

    process_payload = body.get("process")
    if not isinstance(process_payload, Mapping):
        raise ValueError("Tetragon kprobe process payload is missing")
    process = _process_ref(process_payload, boot_id=boot_id)

    function_name = body.get("function_name")
    if function_name == "security_file_permission":
        file_arg = _find_arg(body.get("args"), "file_arg")
        mask = _find_arg(body.get("args"), "int_arg")
        if not isinstance(file_arg, Mapping) or not isinstance(mask, int) or isinstance(mask, bool):
            raise ValueError("Tetragon file-permission event arguments are invalid")
        raw_path = file_arg.get("path")
        path = raw_path if isinstance(raw_path, str) and raw_path else None

        # Ignore read/execute-only observations in the always-on normalization
        # path. Guardian's first ledger scope is mutation-oriented, not a full
        # record of every file read.
        if not (mask & (MAY_WRITE | MAY_APPEND)):
            return ()

        # security_file_permission also fires for unnamed pipes/FIFOs and
        # similar objects for which Tetragon cannot provide a pathname. Those
        # belong in a future high-fidelity IPC trace, not the bounded always-on
        # filesystem ledger.
        if path is None:
            return ()

        access: list[str] = []
        if mask & MAY_WRITE:
            access.append("write")
        if mask & MAY_APPEND:
            access.append("append")

        return (
            _event(
                raw,
                event_type=GuardianEventKind.FILE_WRITE_ACCESS,
                observed_at=observed_at,
                boot_id=boot_id,
                source_event_type=source_event_type,
                process=process,
                target_kind="file",
                target={
                    "path": path,
                    "path_known": path is not None,
                    "access": access,
                    "permission": (
                        file_arg.get("permission")
                        if isinstance(file_arg.get("permission"), str)
                        else None
                    ),
                },
            ),
        )

    if function_name == "tcp_connect":
        sock = _find_arg(body.get("args"), "sock_arg")
        if not isinstance(sock, Mapping):
            raise ValueError("Tetragon tcp_connect socket argument is invalid")

        cookie = sock.get("cookie")
        source_socket_identity = str(cookie) if cookie is not None else None
        socket_id = (
            socket_identity(boot_id=boot_id, source_identity=source_socket_identity)
            if source_socket_identity
            else None
        )

        def _optional_int(name: str) -> int | None:
            value = sock.get(name)
            if value is None:
                return None
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"Tetragon socket {name} is invalid")
            return value

        def _optional_text(name: str) -> str | None:
            value = sock.get(name)
            if value is None:
                return None
            if not isinstance(value, str) or not value:
                raise ValueError(f"Tetragon socket {name} is invalid")
            return value

        return (
            _event(
                raw,
                event_type=GuardianEventKind.NETWORK_CONNECT_ATTEMPT,
                observed_at=observed_at,
                boot_id=boot_id,
                source_event_type=source_event_type,
                process=process,
                target_kind="socket",
                target={
                    "socket_id": socket_id,
                    "family": _optional_text("family"),
                    "type": _optional_text("type"),
                    "protocol": _optional_text("protocol"),
                    "source_address": _optional_text("saddr"),
                    "destination_address": _optional_text("daddr"),
                    "source_port": _optional_int("sport"),
                    "destination_port": _optional_int("dport"),
                },
            ),
        )

    return ()


def parse_metrics(text: str) -> TetragonCoverage:
    values: dict[str, int] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _METRIC.fullmatch(line)
        if not match:
            continue
        name, raw_value = match.groups()
        value = float(raw_value)
        if not value.is_integer() or value < 0:
            raise ValueError(f"Tetragon metric {name} is not a non-negative counter")
        values[name] = int(value)

    required = {
        "tetragon_observer_ringbuf_events_received_total",
        "tetragon_observer_ringbuf_events_lost_total",
        "tetragon_observer_ringbuf_queue_events_lost_total",
    }
    if set(values) != required:
        missing = sorted(required - set(values))
        raise ValueError(f"Tetragon coverage metrics incomplete: {','.join(missing)}")

    return TetragonCoverage(
        received=values["tetragon_observer_ringbuf_events_received_total"],
        lost=values["tetragon_observer_ringbuf_events_lost_total"],
        queue_lost=values["tetragon_observer_ringbuf_queue_events_lost_total"],
    )


def coverage_events(
    previous: TetragonCoverage,
    current: TetragonCoverage,
    *,
    boot_id: str,
    observed_at: str,
) -> tuple[GuardianEvent, ...]:
    parse_timestamp(observed_at)

    if (
        current.received < previous.received
        or current.lost < previous.lost
        or current.queue_lost < previous.queue_lost
    ):
        raw = {
            "kind": "tetragon-counter-reset",
            "previous": previous.as_dict(),
            "current": current.as_dict(),
            "observed_at": observed_at,
        }
        return (
            _event(
                raw,
                event_type=GuardianEventKind.SENSOR_RESET,
                observed_at=observed_at,
                boot_id=boot_id,
                source_event_type="metrics",
                process=None,
                target_kind="sensor",
                target={
                    "reason": "coverage-counter-reset",
                    "previous": previous.as_dict(),
                    "current": current.as_dict(),
                    "continuity_proven": False,
                },
            ),
        )

    lost_delta = current.lost - previous.lost
    queue_delta = current.queue_lost - previous.queue_lost
    if lost_delta == 0 and queue_delta == 0:
        return ()

    raw = {
        "kind": "tetragon-observation-gap",
        "previous": previous.as_dict(),
        "current": current.as_dict(),
        "observed_at": observed_at,
    }
    return (
        _event(
            raw,
            event_type=GuardianEventKind.OBSERVATION_GAP,
            observed_at=observed_at,
            boot_id=boot_id,
            source_event_type="metrics",
            process=None,
            target_kind="sensor",
            target={
                "lost_events": lost_delta,
                "queue_lost_events": queue_delta,
                "received_events": current.received - previous.received,
                "continuity_proven": False,
            },
        ),
    )


def normalize_stream(lines: Iterable[str], *, boot_id: str) -> Iterable[GuardianEvent]:
    for line_number, line in enumerate(lines, start=1):
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Tetragon JSON on line {line_number}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError(f"Tetragon JSON line {line_number} is not an object")
        yield from normalize_tetragon_event(payload, boot_id=boot_id)


def _boot_id_from_proc(path: Path = Path("/proc/sys/kernel/random/boot_id")) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError("boot identity is unavailable")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guardian_tetragon_sensor.py")
    parser.add_argument("--boot-id")
    parser.add_argument("--input", type=Path)
    args = parser.parse_args(argv)

    boot_id = args.boot_id or _boot_id_from_proc()
    if args.input:
        handle = args.input.open("r", encoding="utf-8")
        close = True
    else:
        handle = sys.stdin
        close = False

    try:
        for event in normalize_stream(handle, boot_id=boot_id):
            print(json.dumps(event.as_dict(), sort_keys=True, separators=(",", ":")))
    finally:
        if close:
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
