#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

import guardian_incident  # noqa: E402
import guardian_live_recovery as recovery  # noqa: E402
import guardian_live_response as response  # noqa: E402
import security_incident  # noqa: E402
from maho_runtime_release import verify_release  # noqa: E402
from test_guardian_live_recovery import RotatingRecoveryDriver  # noqa: E402
from test_guardian_runtime_recovery import make_release, make_tree_writable  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def runtime_fixture(base: Path) -> dict:
    runtime = base / "runtime"
    releases = runtime / "releases"
    releases.mkdir(parents=True)
    current = make_release(releases, "1" * 40)
    previous = make_release(releases, "2" * 40)
    (runtime / "current").symlink_to(current)
    (runtime / "previous").symlink_to(previous)
    return {
        "root": runtime,
        "releases": releases,
        "current": current,
        "previous": previous,
        "current_link": runtime / "current",
        "previous_link": runtime / "previous",
    }


def reconcile_security(state: Path, runtime: Path, base: Path) -> tuple[dict, dict]:
    db = base / "db"
    proc = base / "proc"
    fs = base / "fs"
    for path in (db, proc, fs):
        path.mkdir(parents=True, exist_ok=True)
    args = SimpleNamespace(
        state_root=str(state),
        db_root=str(db),
        proc_root=str(proc),
        fs_root=str(fs),
        runtime_root=str(runtime),
        uid=os.getuid(),
        prevention_mode="shadow",
        autonomy_level="guard",
    )
    raw = security_incident.reconcile(args)
    guardian = guardian_incident.reconcile_security(state, raw)
    return raw, guardian


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-runtime-integrity-") as raw:
        base = Path(raw)
        try:
            state = base / "state"
            runtime = runtime_fixture(base)

            healthy, guardian_healthy = reconcile_security(state, runtime["root"], base)
            check("healthy immutable runtime produces no runtime-integrity incident", not healthy["created"])
            check("healthy runtime leaves Guardian incident set empty", guardian_healthy["active"] == 0)

            probe = runtime["current"] / "bin/probe"
            os.chmod(probe, 0o644)
            probe.write_text("runtime-corrupted-after-activation\n", encoding="utf-8")
            os.chmod(probe, 0o444)
            current_verification = verify_release(runtime["current_link"], runtime["releases"])
            check(
                "fixture current immutable runtime is identified but fails exact verification",
                current_verification.verified is False
                and "payload_content_identity_mismatch" in current_verification.reasons,
            )

            detected, guardian_detected = reconcile_security(state, runtime["root"], base)
            check("runtime corruption creates one durable security incident", len(detected["created"]) == 1)
            incident = detected["created"][0]
            check(
                "runtime corruption is first-class runtime:maho-runtime evidence",
                incident["subject"] == {"type": "runtime", "id": "maho-runtime"}
                and incident["confidence"] == "confirmed",
            )
            check(
                "runtime incident is exact verifier evidence, not fake process containment evidence",
                incident["containment_eligible"] is False
                and incident["runtime_pids"] == []
                and any(
                    row["kind"] == "runtime-integrity-drift"
                    and row["source"] == "maho-runtime-verifier"
                    for row in incident["signals"]
                ),
            )
            check("Guardian normalizes runtime ownership as Maho component", guardian_detected["active"] == 1)
            assessment = guardian_detected["created"][0]
            check(
                "Guardian runtime incident stays durable and component-scoped",
                assessment["normalized"]["incident"]["ownership"] == "maho"
                and assessment["normalized"]["incident"]["scope"] == "component"
                and assessment["normalized"]["incident"]["persistent"] is True,
            )

            incident_id = incident["incident_id"]
            containment = response.plan_incident(
                state,
                incident_id,
                db_root=base / "db",
                proc_root=base / "proc",
                fs_root=base / "fs",
                uid=os.getuid(),
            )
            check(
                "runtime integrity incident never fabricates a process-containment target",
                containment["state"] == "none"
                and containment["reason"] == "incident-not-containment-eligible",
            )

            proposed = recovery.reconcile_runtime_recovery(
                state,
                db_root=base / "db",
                runtime_root=runtime["root"],
                proc_root=base / "proc",
                fs_root=base / "fs",
                uid=os.getuid(),
            )
            check("always-on recovery coordinator discovers runtime-integrity incident", proposed["state"] == "authorization-required")
            proposal = recovery.plan_runtime_recovery(
                state,
                incident_id,
                db_root=base / "db",
                runtime_root=runtime["root"],
                proc_root=base / "proc",
                fs_root=base / "fs",
                uid=os.getuid(),
            )
            check(
                "runtime corruption recovery binds direct immutable-runtime evidence",
                proposal["trigger"]["kind"] == "immutable-runtime-integrity"
                and proposal["containment_proposal_id"] is None
                and proposal["automatic_authority"] is False,
            )
            check(
                "recovery proposal binds corrupt current plus verified exact previous runtime",
                proposal["runtime"]["current"]["verified"] is False
                and proposal["runtime"]["previous"]["verified"] is True
                and proposal["runtime"]["previous"]["path"] == str(runtime["previous"]),
            )

            authority = recovery.authorize_runtime_recovery(
                state,
                incident_id,
                proposal["proposal_id"],
                confirm=f"AUTHORIZE-RUNTIME-RECOVERY:{proposal['proposal_id']}",
            )
            driver = RotatingRecoveryDriver(runtime)
            result = recovery.execute_runtime_recovery(
                state,
                authority["authority_id"],
                db_root=base / "db",
                runtime_root=runtime["root"],
                proc_root=base / "proc",
                fs_root=base / "fs",
                uid=os.getuid(),
                driver=driver,
            )
            check(
                "authorized recovery promotes verified previous runtime and quarantines corrupt old current",
                result["result"] == "recovered"
                and runtime["current_link"].resolve() == runtime["previous"]
                and runtime["previous_link"].resolve() == runtime["current"],
            )
            after_current = verify_release(runtime["current_link"], runtime["releases"])
            after_previous = verify_release(runtime["previous_link"], runtime["releases"])
            check("post-recovery current runtime is independently verified", after_current.verified is True)
            check("post-recovery previous pointer preserves corrupt generation without trusting it", after_previous.verified is False)

            resolved, guardian_resolved = reconcile_security(state, runtime["root"], base)
            check(
                "runtime-integrity incident resolves when verified runtime becomes current",
                len(resolved["resolved"]) == 1
                and resolved["resolved"][0]["incident_id"] == incident_id,
            )
            check("Guardian removes resolved runtime incident from active severity", guardian_resolved["active"] == 0)
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-runtime-integrity-bad-previous-") as raw:
        base = Path(raw)
        try:
            state = base / "state"
            runtime = runtime_fixture(base)
            for path in (runtime["current"] / "bin/probe", runtime["previous"] / "bin/probe"):
                os.chmod(path, 0o644)
                path.write_text("corrupt\n", encoding="utf-8")
                os.chmod(path, 0o444)
            detected, _ = reconcile_security(state, runtime["root"], base)
            incident_id = detected["created"][0]["incident_id"]
            proposal = recovery.plan_runtime_recovery(
                state,
                incident_id,
                db_root=base / "db",
                runtime_root=runtime["root"],
                proc_root=base / "proc",
                fs_root=base / "fs",
                uid=os.getuid(),
            )
            check(
                "corrupt previous runtime blocks recovery authority instead of guessing",
                proposal["state"] == "none"
                and "previous Maho runtime is not independently verified" in proposal["reason"],
            )
        finally:
            make_tree_writable(base)

    print("ALL GUARDIAN RUNTIME INTEGRITY INCIDENT TESTS PASS")


if __name__ == "__main__":
    main()
