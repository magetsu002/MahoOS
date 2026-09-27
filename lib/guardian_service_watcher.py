#!/usr/bin/env python3
"""Event-driven Guardian watcher for certified delegated service recovery."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

ROOT = Path(os.environ.get("MAHO_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "lib"))

from guardian_evidence import ProviderHealth  # noqa: E402
from guardian_journal_stream import (  # noqa: E402
    CursorProbe, StreamContinuity, begin_stream, load_stream, mark_dropped,
    mark_event, mark_failed, persist_stream,
)
from guardian_provider_state import record_heartbeat  # noqa: E402
from guardian_recovery_registry import certified_service_recovery, certified_service_units  # noqa: E402
from guardian_session_incident import reconcile_service_session  # noqa: E402
from guardian_service_incident import (  # noqa: E402
    ServiceIncidentStore,
    ServiceSnapshot,
    _atomic_private,
    normalize_journal_event,
)

SERVICE_RECONCILE_SECONDS = 30.0

def state_root() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "maho/security"

def snapshot(unit: str) -> ServiceSnapshot:
    argv = ["systemctl", "--user", "show", unit, "--property=LoadState", "--property=ActiveState", "--property=SubState", "--property=Result", "--property=InvocationID", "--property=Restart", "--property=ControlGroup"]
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
    return ServiceSnapshot(unit=unit, load_state=values.get("LoadState", "unknown"), active_state=values.get("ActiveState", "unknown"), sub_state=values.get("SubState", "unknown"), result=values.get("Result", "unknown"), invocation_id=values.get("InvocationID", ""), restart=values.get("Restart", "unknown"), health_check=health_check, health_ok=health_ok, health_evidence=health_evidence, boot_id=_boot_id())

def _service_health(contract, control_group: str) -> tuple[bool, tuple[str, ...]]:
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
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()

def _cursor_path(root: Path) -> Path:
    return root / "guardian" / "service-events" / "journal.cursor"

def _journal_base() -> list[str]:
    argv = ["journalctl", "--user"]
    for unit in certified_service_units():
        argv.extend(["--unit", unit])
    return argv

def _journal_argv(cursor: str) -> list[str]:
    argv = ["journalctl", "--user", "--follow", "--output=json", "--no-pager"]
    for unit in certified_service_units():
        argv.extend(["--unit", unit])
    argv.append(f"--after-cursor={cursor}" if cursor else "--lines=0")
    return argv

def _journal_probe_argv(cursor: str) -> list[str]:
    argv = ["journalctl", "--user", "--output=json", "--no-pager"]
    for unit in certified_service_units():
        argv.extend(["--unit", unit])
    argv.extend([f"--after-cursor={cursor}", "--lines=0"])
    return argv

def _journal_bootstrap_argv() -> list[str]:
    argv = _journal_base()
    argv.extend(["--lines=0", "--show-cursor", "--no-pager"])
    return argv

def _parse_show_cursor(stdout: str) -> str:
    prefix = "-- cursor: "
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            value = line[len(prefix):].strip()
            return value if value and not any(ch.isspace() for ch in value) else ""
    return ""

def _bootstrap_cursor() -> tuple[str, CursorProbe]:
    try:
        result = subprocess.run(
            _journal_bootstrap_argv(), check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "", CursorProbe.SOURCE_FAILED
    if result.returncode != 0:
        return "", CursorProbe.SOURCE_FAILED
    cursor = _parse_show_cursor(result.stdout)
    return (cursor, CursorProbe.VALID) if cursor else ("", CursorProbe.MISSING)

def _classify_cursor_probe(cursor: str, *, returncode: int | None = None, stderr: str = "", source_error: bool = False) -> CursorProbe:
    if not cursor:
        return CursorProbe.MISSING
    if source_error:
        return CursorProbe.SOURCE_FAILED
    if returncode == 0:
        return CursorProbe.VALID
    message = stderr.lower()
    if "cursor" in message or "seek" in message or "invalid argument" in message:
        return CursorProbe.INVALID
    return CursorProbe.SOURCE_FAILED

def _probe_cursor(cursor: str) -> CursorProbe:
    if not cursor:
        return CursorProbe.MISSING
    try:
        result = subprocess.run(_journal_probe_argv(cursor), check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return CursorProbe.SOURCE_FAILED
    return _classify_cursor_probe(cursor, returncode=result.returncode, stderr=result.stderr)

def _decode_chunk_health(buffer: bytes, chunk: bytes) -> tuple[bytes, list[dict], int]:
    parts = (buffer + chunk).split(b"\n")
    remainder = parts.pop()
    rows: list[dict] = []
    dropped = 0
    for line in parts:
        if not line:
            continue
        try:
            raw = json.loads(line)
        except (UnicodeDecodeError, ValueError):
            dropped += 1
            continue
        if isinstance(raw, dict):
            rows.append(raw)
        else:
            dropped += 1
    return remainder, rows, dropped

def _decode_chunk(buffer: bytes, chunk: bytes) -> tuple[bytes, list[dict]]:
    remainder, rows, _ = _decode_chunk_health(buffer, chunk)
    return remainder, rows

def _reconcile_service_state(
    store: ServiceIncidentStore, boot_id: str, *, now: float | None = None
) -> None:
    """Reconcile certified service truth even when no new journal event arrives."""
    moment = time.time() if now is None else now
    for unit in certified_service_units():
        current = snapshot(unit)
        contract = certified_service_recovery(unit)
        if contract is None:
            continue
        if (
            current.load_state == "loaded"
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
            store.process({**base, "kind": "failed"}, now=moment)
            store.process({**base, "kind": "recovering"}, now=moment)
        elif (
            current.load_state == "loaded"
            and current.active_state == contract.healthy_active_state
            and current.sub_state == contract.healthy_sub_state
            and current.restart == contract.expected_restart
            and current.health_check == contract.health_check
            and current.health_ok is True
            and len(current.invocation_id) == 32
        ):
            store.arm_supersession(
                unit=unit,
                boot_id=current.boot_id or boot_id,
                invocation_id=current.invocation_id,
                now=moment,
            )

def _verify_due(store: ServiceIncidentStore, root: Path, *, now: float | None = None) -> None:
    moment = time.time() if now is None else now
    for state in store.due_verifications(moment):
        store.verify(state, snapshot(str(state["unit"])))
    reconcile_service_session(root, now=moment)

def _provider_heartbeat(root: Path, provider_id: str, *, success: bool, health: ProviderHealth, boot_id: str, errors: tuple[str, ...] = (), details: dict | None = None) -> bool:
    try:
        record_heartbeat(root, provider_id=provider_id, domain="guardian", source="systemd-user-journal", authority_boundary="read-only-observer", success=success, health=health, errors=errors, boot_id=boot_id, details=details or {})
        return True
    except (OSError, ValueError, json.JSONDecodeError):
        return False

def _record_stream_health(root: Path, stream, boot_id: str) -> None:
    _provider_heartbeat(root, "guardian.watch", success=True, health=ProviderHealth.HEALTHY, boot_id=boot_id, details={"continuity": stream.continuity.value})
    if stream.continuity is StreamContinuity.CONTINUOUS:
        health = ProviderHealth.HEALTHY; success = True; errors = ()
    elif stream.continuity is StreamContinuity.FAILED:
        health = ProviderHealth.FAILED; success = False; errors = (stream.reason,)
    else:
        health = ProviderHealth.UNKNOWN; success = False; errors = (stream.reason,)
    _provider_heartbeat(root, "guardian.service-events", success=success, health=health, boot_id=boot_id, errors=errors, details={"continuity": stream.continuity.value, "dropped_events": stream.dropped_events, "last_cursor": stream.last_cursor})

def watch(root: Path) -> int:
    store = ServiceIncidentStore(root)
    cursor_path = _cursor_path(root)
    try:
        cursor = cursor_path.read_text().strip() if cursor_path.is_file() else ""
    except OSError:
        cursor = ""
    previous_invalid = False
    try:
        previous = load_stream(root)
    except (OSError, ValueError, json.JSONDecodeError):
        previous = None; previous_invalid = True
    boot_id = _boot_id()
    if cursor:
        probe = _probe_cursor(cursor)
    else:
        cursor, probe = _bootstrap_cursor()
    stream = begin_stream(previous, cursor=cursor or None, probe=probe, boot_id=boot_id, now=datetime.now(timezone.utc))
    if previous_invalid:
        stream = mark_failed(stream, reason="historical_stream_state_invalid")
    persist_stream(root, stream)
    if probe is CursorProbe.VALID and cursor:
        _atomic_private(cursor_path, cursor + "\n")
    _record_stream_health(root, stream, boot_id)
    _reconcile_service_state(store, boot_id)
    reconcile_service_session(root)
    next_service_reconcile = time.time() + SERVICE_RECONCILE_SECONDS
    resume_cursor = cursor if probe is CursorProbe.VALID else ""
    process = subprocess.Popen(_journal_argv(resume_cursor), stdout=subprocess.PIPE, stderr=sys.stderr, bufsize=0)
    if process.stdout is None:
        stream = persist_stream(root, mark_failed(stream, reason="event_source_stdout_unavailable")); _record_stream_health(root, stream, boot_id); return 1
    buffer = b""
    try:
        while True:
            now = time.time()
            deadline = store.next_deadline()
            wake_at = next_service_reconcile if deadline is None else min(deadline, next_service_reconcile)
            timeout = max(0.0, min(30.0, wake_at - now))
            ready, _, _ = select.select([process.stdout], [], [], timeout)
            if not ready:
                now = time.time()
                _verify_due(store, root, now=now)
                if now >= next_service_reconcile:
                    _reconcile_service_state(store, boot_id, now=now)
                    next_service_reconcile = now + SERVICE_RECONCILE_SECONDS
                    _verify_due(store, root, now=now)
                if process.poll() is not None:
                    stream = persist_stream(root, mark_failed(stream, reason="event_source_exited")); _record_stream_health(root, stream, boot_id); return process.returncode or 1
                _record_stream_health(root, stream, boot_id)
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                stream = persist_stream(root, mark_failed(stream, reason="event_source_eof")); _record_stream_health(root, stream, boot_id); return process.wait() or 1
            buffer, rows, dropped = _decode_chunk_health(buffer, chunk)
            if dropped:
                stream = persist_stream(root, mark_dropped(stream, count=dropped, reason="journal_records_unparseable"))
            for raw in rows:
                observed = datetime.now(timezone.utc)
                event_cursor = raw.get("__CURSOR")
                cursor_value = event_cursor if isinstance(event_cursor, str) and event_cursor else None
                stream = persist_stream(root, mark_event(stream, cursor=cursor_value, now=observed))
                if cursor_value:
                    _atomic_private(cursor_path, cursor_value + "\n")
                event = normalize_journal_event(raw)
                if event is not None:
                    observed_at = observed.timestamp()
                    store.process(event, now=observed_at)
                    reconcile_service_session(root, now=observed_at)
            now = time.time()
            deadline = store.next_deadline()
            if deadline is not None and deadline <= now:
                _verify_due(store, root, now=now)
            if now >= next_service_reconcile:
                _reconcile_service_state(store, boot_id, now=now)
                next_service_reconcile = now + SERVICE_RECONCILE_SECONDS
                _verify_due(store, root, now=now)
            _record_stream_health(root, stream, boot_id)
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
        contract = certified_service_recovery(unit); current = snapshot(unit)
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
