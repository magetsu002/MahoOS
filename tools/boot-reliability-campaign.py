#!/usr/bin/env python3
"""Record and verify repeated graphical-login boots without inventing visibility."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_login_diagnostic import collect_login_diagnostic  # noqa: E402

_MONO = re.compile(r"^\[\s*([0-9]+(?:\.[0-9]+)?)\]")
_BOOT_LINE = re.compile(r"^\s*(-?\d+)\s+([0-9a-f]{32})\s+")


def _run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _first_time(text: str, needle: str) -> float | None:
    for line in text.splitlines():
        if needle not in line:
            continue
        match = _MONO.match(line)
        if match:
            return float(match.group(1))
    return None


def _boot_ids() -> list[str]:
    result = _run(("journalctl", "--list-boots", "--no-pager"))
    if result.returncode != 0:
        return []
    indexed: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        match = _BOOT_LINE.match(line)
        if match:
            indexed.append((int(match.group(1)), match.group(2)))
    return [boot_id for _, boot_id in sorted(indexed)]


def _current_boot_id() -> str:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text().strip().replace("-", "")
    except OSError as exc:
        raise RuntimeError(f"cannot read current boot ID: {exc}") from exc
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise RuntimeError("current boot ID is malformed")
    return value


def _relevant_warnings() -> list[str]:
    result = _run(("journalctl", "-b", "-p", "warning..alert", "--no-pager", "-o", "short-monotonic"))
    if result.returncode != 0:
        return [f"journal unavailable: {result.stderr.strip() or result.returncode}"]
    pattern = re.compile(r"sddm|display|drm|nvidia|i915|hyprland|seat|tty|vt", re.IGNORECASE)
    return [line for line in result.stdout.splitlines() if pattern.search(line)][-50:]


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid JSONL record {number}: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"record {number} is not an object")
        records.append(value)
    return records


def record(path: Path, visible: str) -> int:
    boot_id = _current_boot_id()
    existing = _read_records(path)
    if any(item.get("boot_id") == boot_id for item in existing):
        raise RuntimeError(f"boot {boot_id} is already recorded")

    diagnostic = collect_login_diagnostic()
    journal = _run(("journalctl", "-b", "-o", "short-monotonic", "--no-pager"))
    graphical_time = _first_time(journal.stdout, "Reached target Graphical Interface")
    structural_pass = diagnostic.get("state") == "PASS" and graphical_time is not None
    entry = {
        "schema_version": 1,
        "kind": "maho-boot-reliability-record",
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "boot_id": boot_id,
        "structural_result": "PASS" if structural_pass else "FAIL",
        "visible_confirmation": visible,
        "display_manager_start_monotonic": diagnostic.get("display_manager_start_monotonic"),
        "greeter_start_monotonic": diagnostic.get("greeter_start_monotonic"),
        "graphical_target_monotonic": graphical_time,
        "nvidia_drm_ready_monotonic": diagnostic.get("nvidia_drm_ready_monotonic"),
        "display_manager_restarts": diagnostic.get("display_manager_restarts"),
        "seat": diagnostic.get("seat"),
        "vt": diagnostic.get("vt"),
        "failed_checks": diagnostic.get("failed_checks", []),
        "runtime_source_revision": diagnostic.get("runtime_source_revision"),
        "relevant_warnings": _relevant_warnings(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps(entry, indent=2, sort_keys=True))
    return 0 if structural_pass and visible != "no" else 1


def report(path: Path, minimum: int) -> int:
    records = _read_records(path)
    selected = records[-minimum:]
    ids = [str(item.get("boot_id", "")) for item in selected]
    known = _boot_ids()
    consecutive = len(selected) >= minimum and bool(known) and ids == known[-minimum:]
    structural = len(selected) >= minimum and all(item.get("structural_result") == "PASS" for item in selected)
    visible_yes = len(selected) >= minimum and all(item.get("visible_confirmation") == "yes" for item in selected)
    no_restarts = len(selected) >= minimum and all(item.get("display_manager_restarts") in (0, 1) for item in selected)
    result = {
        "schema_version": 1,
        "kind": "maho-boot-reliability-report",
        "minimum_boots": minimum,
        "recorded_boots": len(records),
        "evaluated_boots": len(selected),
        "journal_consecutive": consecutive,
        "all_structural_contracts_pass": structural,
        "all_visible_confirmations_yes": visible_yes,
        "all_restart_counts_bounded": no_restarts,
        "boot_ids": ids,
        "result": "PASS" if consecutive and structural and visible_yes and no_restarts else "INCOMPLETE",
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["result"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record one result after each reboot, then require consecutive structural and visible success.",
    )
    parser.add_argument("--output", type=Path, required=True, help="append-only JSONL evidence file")
    subparsers = parser.add_subparsers(dest="command", required=True)
    recorder = subparsers.add_parser("record", help="record the current boot once")
    recorder.add_argument("--visible", choices=("yes", "no", "not-checked"), required=True)
    reporter = subparsers.add_parser("report", help="verify the newest recorded boots")
    reporter.add_argument("--minimum", type=int, default=10)
    args = parser.parse_args()
    if args.command == "record":
        return record(args.output, args.visible)
    if args.minimum < 1:
        parser.error("--minimum must be at least 1")
    return report(args.output, args.minimum)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
