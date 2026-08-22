#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from pathlib import Path

from security_probe import atomic_private, normalized_package_paths, package_record, read_process

SESSION_RE = re.compile(r"^contain-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")


def process_start_ticks(proc_root: Path, pid: int) -> int | None:
    try:
        raw = (proc_root / str(pid) / "stat").read_text(errors="replace")
        end = raw.rfind(")")
        if end < 0:
            return None
        rest = raw[end + 2 :].split()
        # rest[0] is field 3 (state); starttime is field 22.
        return int(rest[19])
    except (OSError, ValueError, IndexError):
        return None


def process_ppid(proc_root: Path, pid: int) -> int | None:
    try:
        raw = (proc_root / str(pid) / "stat").read_text(errors="replace")
        end = raw.rfind(")")
        if end < 0:
            return None
        rest = raw[end + 2 :].split()
        return int(rest[1])  # field 4, because rest[0] is field 3.
    except (OSError, ValueError, IndexError):
        return None


def ancestor_chain(proc_root: Path, pid: int) -> set[int]:
    seen = set()
    current = pid
    for _ in range(128):
        if current <= 1 or current in seen:
            break
        seen.add(current)
        parent = process_ppid(proc_root, current)
        if parent is None or parent <= 0:
            break
        current = parent
    return seen


def process_state(proc_root: Path, pid: int) -> str | None:
    try:
        for line in (proc_root / str(pid) / "status").read_text(errors="replace").splitlines():
            if line.startswith("State:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def visible_package_processes(db_root: Path, proc_root: Path, fs_root: Path, package: str, uid: int) -> tuple[dict | None, list[dict]]:
    record = package_record(db_root, package)
    if not record:
        return None, []
    package_paths = normalized_package_paths(record)
    rows = []
    if not proc_root.is_dir():
        return record, rows
    for proc in proc_root.iterdir():
        if not proc.name.isdigit() or not proc.is_dir():
            continue
        item = read_process(proc, fs_root)
        if not item or item.get("uid") != uid or item.get("relative_exe") not in package_paths:
            continue
        start = process_start_ticks(proc_root, item["pid"])
        if start is None:
            continue
        item["start_time_ticks"] = start
        rows.append(item)
    rows.sort(key=lambda x: x["pid"])
    return record, rows


def session_id() -> str:
    import datetime as dt
    import secrets

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"contain-{stamp}-{secrets.token_hex(4)}"


def freeze(args) -> dict:
    db_root = Path(args.db_root)
    proc_root = Path(args.proc_root)
    fs_root = Path(args.fs_root)
    state_root = Path(args.state_root) / "containment"
    record, processes = visible_package_processes(db_root, proc_root, fs_root, args.package, args.uid)
    if not record:
        return {
            "version": 1,
            "kind": "process-containment",
            "result": "package-not-installed",
            "package": args.package,
            "session_id": None,
            "contained": [],
            "failed": [],
        }
    if args.version and record["version"] != args.version:
        return {
            "version": 1,
            "kind": "process-containment",
            "result": "version-mismatch",
            "package": args.package,
            "installed_version": record["version"],
            "expected_version": args.version,
            "session_id": None,
            "contained": [],
            "failed": [],
        }

    protected = ancestor_chain(proc_root, os.getpid())
    contained = []
    failed = []
    for item in processes:
        pid = item["pid"]
        if pid in protected:
            failed.append({"pid": pid, "exe": item.get("exe"), "reason": "protected-ancestor"})
            continue
        try:
            os.kill(pid, signal.SIGSTOP)
            time.sleep(0.03)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            failed.append({"pid": pid, "exe": item.get("exe"), "reason": type(exc).__name__})
            continue
        state = process_state(proc_root, pid)
        if state is None:
            failed.append({"pid": pid, "exe": item.get("exe"), "reason": "process-disappeared"})
            continue
        if not state.startswith(("T", "t")):
            failed.append({"pid": pid, "exe": item.get("exe"), "reason": f"stop-not-verified:{state}"})
            continue
        contained.append(
            {
                "pid": pid,
                "exe": item.get("exe"),
                "name": item.get("name"),
                "start_time_ticks": item["start_time_ticks"],
            }
        )

    if not contained:
        return {
            "version": 1,
            "kind": "process-containment",
            "result": "no-targets",
            "package": args.package,
            "installed_version": record["version"],
            "session_id": None,
            "contained": [],
            "failed": failed,
        }

    sid = session_id()
    session = {
        "version": 1,
        "kind": "process-containment-session",
        "session_id": sid,
        "package": args.package,
        "installed_version": record["version"],
        "finding_id": args.finding_id,
        "processes": contained,
    }
    path = state_root / f"{sid}.json"
    atomic_private(path, (json.dumps(session, indent=2, sort_keys=True) + "\n").encode())
    return {
        "version": 1,
        "kind": "process-containment",
        "result": "contained" if not failed else "partial",
        "package": args.package,
        "installed_version": record["version"],
        "finding_id": args.finding_id,
        "session_id": sid,
        "session_path": str(path),
        "contained": contained,
        "failed": failed,
    }


def release(args) -> dict:
    if not SESSION_RE.fullmatch(args.session_id):
        raise SystemExit("invalid containment session id")
    proc_root = Path(args.proc_root)
    state_root = Path(args.state_root) / "containment"
    path = state_root / f"{args.session_id}.json"
    if not path.is_file():
        raise SystemExit(f"containment session does not exist: {args.session_id}")
    data = json.loads(path.read_text())
    if data.get("version") != 1 or data.get("kind") != "process-containment-session":
        raise SystemExit("unsupported containment session")

    released = []
    skipped = []
    for item in data.get("processes", []):
        pid = int(item["pid"])
        expected_start = int(item["start_time_ticks"])
        current_start = process_start_ticks(proc_root, pid)
        if current_start is None:
            skipped.append({"pid": pid, "reason": "process-gone"})
            continue
        if current_start != expected_start:
            skipped.append({"pid": pid, "reason": "pid-reused"})
            continue
        try:
            os.kill(pid, signal.SIGCONT)
            time.sleep(0.03)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            skipped.append({"pid": pid, "reason": type(exc).__name__})
            continue
        state = process_state(proc_root, pid)
        if state and state.startswith(("T", "t")):
            skipped.append({"pid": pid, "reason": f"resume-not-verified:{state}"})
            continue
        released.append({"pid": pid, "state": state})

    result = "released" if not skipped else ("partial" if released else "no-live-targets")
    return {
        "version": 1,
        "kind": "process-containment-release",
        "result": result,
        "session_id": args.session_id,
        "package": data.get("package"),
        "released": released,
        "skipped": skipped,
    }


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="security_containment.py")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("freeze")
    f.add_argument("package")
    f.add_argument("--version")
    f.add_argument("--finding-id", required=True)
    f.add_argument("--db-root", required=True)
    f.add_argument("--proc-root", default="/proc")
    f.add_argument("--fs-root", default="/")
    f.add_argument("--state-root", required=True)
    f.add_argument("--uid", type=int, required=True)

    r = sub.add_parser("release")
    r.add_argument("session_id")
    r.add_argument("--proc-root", default="/proc")
    r.add_argument("--state-root", required=True)

    return p


def main() -> int:
    args = parser().parse_args()
    if args.command == "freeze":
        result = freeze(args)
    else:
        result = release(args)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
