#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import guardian_live_response as live  # noqa: E402
from guardian_live_state import LivePaths, live_status  # noqa: E402
from security_containment import process_state  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
def wait_state(pid: int, stopped: bool, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = process_state(Path("/proc"), pid)
        if state is None:
            return False
        is_stopped = state.startswith(("T", "t"))
        if is_stopped == stopped:
            return True
        time.sleep(0.02)
    return False


def main() -> None:
    sleeper = shutil.which("sleep")
    if sleeper is None:
        raise AssertionError("sleep executable unavailable")
    executable = Path(os.path.realpath(sleeper))
    rel_executable = str(executable.relative_to("/"))
    target_proc = subprocess.Popen([str(executable), "120"])
    unrelated_proc = subprocess.Popen([str(executable), "120"])
    processes = (target_proc, unrelated_proc)
    try:
        time.sleep(0.1)
        for proc in processes:
            check(f"sacrificial process {proc.pid} started", proc.poll() is None)

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "security"
            db = root / "db"
            pkg = db / "alpha-1.0-1"
            pkg.mkdir(parents=True)
            pkg.joinpath("desc").write_text(
                "%NAME%\nalpha\n\n%VERSION%\n1.0-1\n\n%FILES%\n"
                + rel_executable
                + "\n\n",
                encoding="utf-8",
            )

            incident_id = "inc-real-live-response"
            source = {
                "kind": "security-incident",
                "incident_id": incident_id,
                "status": "active",
                "subject": {"type": "package", "id": "alpha"},
                "risk": "critical",
                "confidence": "confirmed",
                "containment_eligible": True,
                "response_reversible": True,
                "runtime_pids": [target_proc.pid],
                "signals": [
                    {
                        "kind": "confirmed-finding",
                        "source": "integration-test",
                        "details": {
                            "finding_id": "finding-real-001",
                            "installed_version": "1.0-1",
                            "summary": "Sacrificial package is confirmed affected.",
                        },
                    },
                    {
                        "kind": "runtime-executable",
                        "source": "procfs",
                        "details": {
                            "observations": [
                                {"pid": target_proc.pid, "exe": str(executable)}
                            ]
                        },
                    },
                ],
            }
            assessment = {
                "kind": "guardian-assessment",
                "incident_id": incident_id,
                "source_kind": "security-incident",
                "status": "active",
                "subject": {"type": "package", "id": "alpha"},
                "decision": {
                    "severity": {
                        "level": 3,
                        "label": "severe",
                        "reason": "real-process fixture",
                    }
                },
            }
            write_json(state / "incidents/active" / f"{incident_id}.json", source)
            write_json(state / "guardian/active" / f"{incident_id}.json", assessment)

            paths = LivePaths(
                state,
                root / "state",
                root / "update",
                root / "recovery",
                root / "runtime",
                Path("/proc"),
                root / "signed-boot",
            )
            before = live_status(paths)
            baseline_trust = before["world_state"]["guardian"]["trust"]
            baseline_self = before["world_state"]["guardian"]["self_health"]

            reconciled = live.reconcile(
                state,
                db_root=db,
                proc_root=Path("/proc"),
                fs_root=Path("/"),
                uid=os.getuid(),
            )
            check(
                "real process produces authorization-required response",
                reconciled["state"] == "authorization-required",
            )
            active = live._read_object(live._active_path(state, incident_id))
            assert active is not None
            proposal_id = str(active["proposal_id"])
            denied = live.authorize_containment(
                state,
                incident_id,
                proposal_id,
                confirm="DENY",
            )
            check("denied authorization does not stop target", denied["result"] == "denied")
            check("target remains running before authorization", wait_state(target_proc.pid, False))
            check("unrelated process remains running before authorization", wait_state(unrelated_proc.pid, False))

            authority = live.authorize_containment(
                state,
                incident_id,
                proposal_id,
                confirm=f"AUTHORIZE-CONTAIN:{proposal_id}",
            )
            result = live.execute_authorized(
                state,
                authority["authority_id"],
                db_root=db,
                proc_root=Path("/proc"),
                fs_root=Path("/"),
                uid=os.getuid(),
            )
            check("real SIGSTOP containment is verified", result["result"] == "contained" and result["verified"])
            check("target process is actually stopped", wait_state(target_proc.pid, True))
            check("unrelated process was not stopped", wait_state(unrelated_proc.pid, False))
            during = live_status(paths)
            check("canonical live status reports contained", during["containment"]["state"] == "contained")
            check("manual containment does not elevate trust", during["world_state"]["guardian"]["trust"] == baseline_trust)
            check("manual containment does not mask Guardian self-health", during["world_state"]["guardian"]["self_health"] == baseline_self)

            active = live._read_object(live._active_path(state, incident_id))
            assert active is not None
            receipt_id = str(active["receipt_id"])
            release_auth = live.authorize_release(
                state,
                incident_id,
                receipt_id,
                confirm=f"AUTHORIZE-RELEASE:{receipt_id}",
            )
            released = live.execute_release(
                state,
                release_auth["authority_id"],
                db_root=db,
                proc_root=Path("/proc"),
                fs_root=Path("/"),
                uid=os.getuid(),
            )
            check("receipt-bound release is verified", released["result"] == "released" and released["verified"])
            check("target process is actually resumed", wait_state(target_proc.pid, False))
            check("unrelated process remains running after release", wait_state(unrelated_proc.pid, False))
            after = live_status(paths)
            check("canonical live status returns to none", after["containment"]["state"] == "none")
            history = list((state / "guardian/live-response/history").glob("*.json"))
            check("real response lifecycle retains history", len(history) >= 6)

        print("ALL GUARDIAN LIVE RESPONSE REAL-PROCESS TESTS PASS")
    finally:
        for proc in processes:
            try:
                os.kill(proc.pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
            if proc.poll() is None:
                proc.terminate()
        for proc in processes:
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)


if __name__ == "__main__":
    main()
