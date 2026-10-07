#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path
from typing import Any


FILE_WORDS = re.compile(r"(open|write|rename|unlink|chmod|symlink|link|truncate|file)", re.I)
NETWORK_WORDS = re.compile(r"(connect|bind|listen|accept|socket)", re.I)
EXEC_WORDS = re.compile(r"(process_exec|sched_process_exec|execve)", re.I)
EXIT_WORDS = re.compile(r"(process_exit|sched_process_exit|exit_group)", re.I)


def load_json_events(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None

    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]

    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def event_type(candidate: str, row: dict[str, Any]) -> str:
    if candidate == "tracee":
        return str(row.get("name") or row.get("id") or "unknown")
    if candidate == "tetragon":
        for key in row:
            if key.startswith("process_"):
                return key
    return str(row.get("name") or row.get("event_type") or "unknown")

def serialized(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"))


def has_stable_identity(candidate: str, row: dict[str, Any]) -> bool:
    if candidate == "tetragon":
        for key, value in row.items():
            if not key.startswith("process_") or not isinstance(value, dict):
                continue
            process = value.get("process")
            if isinstance(process, dict) and process.get("exec_id"):
                return True
    if candidate == "tracee":
        workload = row.get("workload")
        process = workload.get("process") if isinstance(workload, dict) else None
        thread = process.get("thread") if isinstance(process, dict) else None
        if isinstance(thread, dict) and (thread.get("unique_id") or thread.get("start_time")):
            return True
    return False


def has_parentage(candidate: str, row: dict[str, Any]) -> bool:
    if candidate == "tetragon":
        value = row.get("process_exec")
        if isinstance(value, dict):
            process = value.get("process")
            if isinstance(process, dict) and process.get("parent_exec_id"):
                return True
            if isinstance(value.get("parent"), dict):
                return True
    if candidate == "tracee":
        workload = row.get("workload")
        process = workload.get("process") if isinstance(workload, dict) else None
        ancestors = process.get("ancestors") if isinstance(process, dict) else None
        return isinstance(ancestors, list) and bool(ancestors)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", choices=("tetragon", "tracee", "generic-json"), required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    token = str(manifest["token"])
    marker = str(manifest["marker"])
    root = str(manifest["root"])
    file_paths = [str(value) for value in manifest["expected"]["file_paths"]]

    events = load_json_events(args.events)
    hist = collections.Counter(event_type(args.candidate, row) for row in events)

    relevant = []
    for row in events:
        blob = serialized(row)
        if token in blob or marker in blob or root in blob:
            relevant.append(row)

    relevant_types = collections.Counter(event_type(args.candidate, row) for row in relevant)
    relevant_blobs = [serialized(row) for row in relevant]
    relevant_type_text = "\n".join(relevant_types)
    semantic_text = relevant_type_text + "\n" + "\n".join(relevant_blobs)

    file_hits = {
        path: any(path in blob for blob in relevant_blobs)
        for path in file_paths
    }

    result = {
        "candidate": args.candidate,
        "events_total": len(events),
        "events_workload_related": len(relevant),
        "event_types": dict(hist.most_common()),
        "workload_event_types": dict(relevant_types.most_common()),
        "observed": {
            "process_exec": bool(EXEC_WORDS.search(relevant_type_text)),
            "process_exit": bool(EXIT_WORDS.search(relevant_type_text)),
            "stable_process_identity": any(has_stable_identity(args.candidate, row) for row in relevant),
            "parentage": any(has_parentage(args.candidate, row) for row in relevant),
            "filesystem_event": bool(FILE_WORDS.search(semantic_text)),
            "network_event": bool(NETWORK_WORDS.search(semantic_text)),
            "file_path_hits": file_hits,
        },
        "limits": [
            "This analyzer reports captured evidence only.",
            "It does not promote temporal proximity to causality.",
            "Sensor-loss accounting must be measured separately.",
        ],
    }

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
