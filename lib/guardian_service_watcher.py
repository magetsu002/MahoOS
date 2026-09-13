#!/usr/bin/env python3
"""Event-driven Guardian watcher for certified delegated service recovery."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

ROOT = Path(os.environ.get("MAHO_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "lib"))

from guardian_recovery_registry import certified_service_recovery, certified_service_units  # noqa: E402
from guardian_session_incident import reconcile_service_session  # noqa: E402
from guardian_service_incident import (  # noqa: E402
    ServiceIncidentStore,
    ServiceSnapshot,
    _atomic_private,
    normalize_journal_event,
)


def state_root() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "maho/security"


def snapshot(unit: str) -> ServiceSnapshot:
    argv = [
        "systemctl", "--user", "show", unit,
        "--property=LoadState", "--property=ActiveState", "--property=SubState",
        "--property=Result", "--property=InvocationID", "--property=Restart", "--property=ControlGroup",
    ]
    result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=10)
    values = {}
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
    contract = certified_service_recovery(unit)
    health_check = contract.health_check if contract is not None else "uncertified"
    health_ok, health_evidence = _service_health(contract, values.get("ControlGroup", ""))
    return ServiceSnapshot(
        unit=unit,
        load_state=values.get("LoadState", "unknown"),
        active_state=values.get("ActiveState", "unknown"),
        sub_state=values.get("SubState", "unknown"),
        result=values.get("Result", "unknown"),
        invocation_id=values.get("InvocationID", ""),
        restart=values.get("Restart", "unknown"),
        health_check=health_check,
        health_ok=health_ok,
        health_evidence=health_evidence,
        boot_id=_boot_id(),
    )



def _service_health(contract, control_group: str) -> tuple[bool, tuple[str, ...]]:
    """Verify the certified runtime identity inside the unit's own cgroup."""
    if contract is None or not control_group.startswith("/"):
        return False, ()
    procs = Path("/sys/fs/cgroup") / control_group.lstrip("/") / "cgroup.procs"
    try:
        pids = sorted({int(row) for row in procs.read_text().split() if row.isdigit()})
    except OSError:
        return False, ()
    evidence: list[str] = []
    for pid in pids:
        try:
            args = [os.fsdecode(part) for part in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if part]
        except OSError:
            continue
        if args:
            evidence.append(" ".join(args))
    joined = "\n".join(evidence)
    ok = bool(evidence) and all(pattern in joined for pattern in contract.health_process_patterns)
    return ok, tuple(evidence)

def _boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip().replace("-", "")


def _cursor_path(root: Path) -> Path:
    return root / "guardian" / "service-events" / "journal.cursor"


def _journal_argv(cursor: str) -> list[str]:
    argv = ["journalctl", "--user", "--follow", "--output=json", "--no-pager"]
    for unit in certified_service_units():
        argv.extend(["--unit", unit])
    argv.append(f"--after-cursor={cursor}" if cursor else "--lines=0")
    return argv


def _decode_chunk(buffer: bytes, chunk: bytes) -> tuple[bytes, list[dict]]:
    """Drain every complete JSON line already delivered by journalctl."""
    parts = (buffer + chunk).split(b"\n")
    remainder = parts.pop()
    rows = []
    for line in parts:
        try:
            raw = json.loads(line)
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return remainder, rows


def _startup_reconcile(store: ServiceIncidentStore, boot_id: str) -> None:
    now = time.time()
    for unit in certified_service_units():
        current = snapshot(unit)
        contract = certified_service_recovery(unit)
        if (
            contract is not None
            and current.load_state == "loaded"
            and current.active_state == "activating"
            and current.sub_state == "auto-restart"
            and current.result not in {"", "success"}
            and len(current.invocation_id) == 32
        ):
            base = {
                "unit": unit,
                "boot_id": boot_id,
                "invocation_id": current.invocation_id,
                "result": current.result,
                "timestamp_usec": "0",
                "cursor": "",
            }
            store.process({**base, "kind": "failed"}, now=now)
            store.process({**base, "kind": "recovering"}, now=now)
        elif (
            contract is not None
            and current.load_state == "loaded"
            and current.active_state == contract.healthy_active_state
            and current.sub_state == contract.healthy_sub_state
            and current.restart == contract.expected_restart
            and current.health_check == contract.health_check
            and current.health_ok is True
            and len(current.invocation_id) == 32
        ):
            store.arm_supersession(
                unit=unit,
                boot_id=boot_id,
                invocation_id=current.invocation_id,
                now=now,
            )


def _verify_due(store: ServiceIncidentStore, root: Path) -> None:
    now = time.time()
    for state in store.due_verifications(now):
        store.verify(state, snapshot(str(state["unit"])))
    reconcile_service_session(root, now=now)


def watch(root: Path) -> int:
    store = ServiceIncidentStore(root)
    cursor_path = _cursor_path(root)
    cursor = cursor_path.read_text().strip() if cursor_path.is_file() else ""
    _startup_reconcile(store, _boot_id())
    reconcile_service_session(root)
    process = subprocess.Popen(
        _journal_argv(cursor), stdout=subprocess.PIPE, stderr=sys.stderr,
        bufsize=0,
    )
    if process.stdout is None:
        return 1
    buffer = b""
    try:
        while True:
            deadline = store.next_deadline()
            timeout = 30.0 if deadline is None else max(0.0, min(30.0, deadline - time.time()))
            ready, _, _ = select.select([process.stdout], [], [], timeout)
            if not ready:
                _verify_due(store, root)
                if process.poll() is not None:
                    return process.returncode or 1
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                return process.wait() or 1
            buffer, rows = _decode_chunk(buffer, chunk)
            for raw in rows:
                event = normalize_journal_event(raw)
                if event is not None:
                    observed_at = time.time()
                    store.process(event, now=observed_at)
                    reconcile_service_session(root, now=observed_at)
                event_cursor = raw.get("__CURSOR")
                if isinstance(event_cursor, str) and event_cursor:
                    _atomic_private(cursor_path, event_cursor + "\n")
    finally:
        if process.poll() is None:
            process.terminate()


def doctor() -> int:
    failed = False
    print("Maho Guardian delegated recovery watcher")
    journal_available = shutil_which("journalctl") is not None
    print("PASS  event source journalctl structured follow" if journal_available else "FAIL  event source journalctl unavailable")
    failed = failed or not journal_available
    for unit in certified_service_units():
        contract = certified_service_recovery(unit)
        current = snapshot(unit)
        valid = contract is not None and current.load_state == "loaded" and current.restart == contract.expected_restart
        print(("PASS  " if valid else "FAIL  ") + f"delegated contract {unit}")
        failed = failed or not valid
    print("INFO  Guardian issues no restart for delegated systemd-user recovery")
    return 1 if failed else 0


def shutil_which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(prog="maho-guardian-watch")
    parser.add_argument("command", choices=("watch", "doctor"))
    parser.add_argument("--state-root", type=Path, default=state_root())
    args = parser.parse_args()
    return watch(args.state_root) if args.command == "watch" else doctor()


if __name__ == "__main__":
    raise SystemExit(main())
