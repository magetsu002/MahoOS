from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from statistics import median
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

import guardian_incident  # noqa: E402
import guardian_live_recovery as recovery  # noqa: E402
import security_incident  # noqa: E402
from guardian_evidence import ProviderHealth  # noqa: E402
from guardian_provider_state import record_heartbeat  # noqa: E402
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
    current_link = runtime / "current"
    previous_link = runtime / "previous"
    current_link.symlink_to(current)
    previous_link.symlink_to(previous)
    return {
        "root": runtime,
        "releases": releases,
        "current": current,
        "previous": previous,
        "current_link": current_link,
        "previous_link": previous_link,
    }


def paths(base: Path) -> tuple[Path, Path, Path, Path]:
    db, proc, fs = base / "db", base / "proc", base / "fs"
    for item in (db, proc, fs):
        item.mkdir(parents=True, exist_ok=True)
    boot = proc / "sys/kernel/random"
    boot.mkdir(parents=True, exist_ok=True)
    (boot / "boot_id").write_text("fixture-boot", encoding="utf-8")
    return db, proc, fs, base / "state"


def reconcile_security(ctx: dict) -> tuple[dict, dict]:
    args = SimpleNamespace(
        state_root=str(ctx["state"]),
        db_root=str(ctx["db"]),
        proc_root=str(ctx["proc"]),
        fs_root=str(ctx["fs"]),
        runtime_root=str(ctx["runtime"]["root"]),
        uid=os.getuid(),
        prevention_mode="shadow",
        autonomy_level="guard",
    )
    raw = security_incident.reconcile(args)
    guardian = guardian_incident.reconcile_security(ctx["state"], raw)
    return raw, guardian


def damage(runtime: dict, kind: str = "replace", *, text: str = "runtime-corrupted\n") -> None:
    probe = runtime["current"] / "bin/probe"
    if kind == "replace":
        os.chmod(probe, 0o644)
        probe.write_text(text, encoding="utf-8")
        os.chmod(probe, 0o444)
    elif kind == "delete":
        parent = probe.parent
        os.chmod(parent, 0o755)
        probe.unlink()
        os.chmod(parent, 0o555)
    else:
        raise ValueError(kind)
    observed = verify_release(runtime["current_link"], runtime["releases"])
    if observed.verified:
        raise AssertionError("damage fixture did not invalidate current runtime")


def fixture(base: Path, *, damage_kind: str = "replace") -> dict:
    db, proc, fs, state = paths(base)
    ctx = {
        "db": db,
        "proc": proc,
        "fs": fs,
        "state": state,
        "uid": os.getuid(),
        "runtime": runtime_fixture(base),
    }
    reconcile_security(ctx)
    damage(ctx["runtime"], damage_kind)
    raw, guardian = reconcile_security(ctx)
    if len(raw["created"]) != 1 or guardian["active"] != 1:
        raise AssertionError(f"runtime incident fixture failed: {raw} {guardian}")
    ctx["incident_id"] = raw["created"][0]["incident_id"]
    return ctx


def provider_observation(
    state: Path,
    *,
    at: datetime | None = None,
    omit: set[str] | None = None,
    stale: set[str] | None = None,
    degraded: set[str] | None = None,
    boot_overrides: dict[str, str] | None = None,
) -> None:
    current = at or datetime.now(timezone.utc)
    omitted = omit or set()
    stale_ids = stale or set()
    degraded_ids = degraded or set()
    boot_ids = boot_overrides or {}
    for provider_id, max_age in recovery.AUTO_PROVIDER_MAX_AGE.items():
        if provider_id in omitted:
            continue
        observed = current
        if provider_id in stale_ids:
            observed = current - timedelta(seconds=max_age + 30)
        health = ProviderHealth.DEGRADED if provider_id in degraded_ids else ProviderHealth.HEALTHY
        record_heartbeat(
            state,
            provider_id=provider_id,
            domain="guardian" if provider_id.startswith("guardian.") else "security",
            source="guardian-hostile-fixture",
            authority_boundary="read-only-observer",
            success=True,
            health=health,
            boot_id=boot_ids.get(provider_id, "fixture-boot"),
            details={"fixture": True},
            now=observed,
        )


def plan(ctx: dict) -> dict:
    return recovery.plan_runtime_recovery(
        ctx["state"],
        ctx["incident_id"],
        db_root=ctx["db"],
        runtime_root=ctx["runtime"]["root"],
        proc_root=ctx["proc"],
        fs_root=ctx["fs"],
        uid=ctx["uid"],
    )


def auto_execute(ctx: dict, proposal: dict, driver) -> dict:
    return recovery.execute_automatic_runtime_recovery(
        ctx["state"],
        ctx["incident_id"],
        db_root=ctx["db"],
        runtime_root=ctx["runtime"]["root"],
        proc_root=ctx["proc"],
        fs_root=ctx["fs"],
        uid=ctx["uid"],
        driver=driver,
        expected_proposal_id=proposal["proposal_id"],
    )


def finish_verification(ctx: dict) -> dict:
    reconcile_security(ctx)
    post = datetime.now(timezone.utc) + timedelta(seconds=2)
    provider_observation(ctx["state"], at=post)
    return recovery.verify_automatic_runtime_recovery(
        ctx["state"],
        ctx["incident_id"],
        runtime_root=ctx["runtime"]["root"],
        proc_root=ctx["proc"],
        now=post + timedelta(seconds=1),
    )


def success_case(base: Path, damage_kind: str, timings: list[dict[str, float]]) -> None:
    total_start = time.perf_counter()
    detect_start = time.perf_counter()
    ctx = fixture(base, damage_kind=damage_kind)
    detect_ms = (time.perf_counter() - detect_start) * 1000.0

    provider_observation(ctx["state"])
    proposal_start = time.perf_counter()
    proposal = plan(ctx)
    decision = recovery.automatic_recovery_policy(ctx["state"], proposal, proc_root=ctx["proc"])
    decision_ms = (time.perf_counter() - proposal_start) * 1000.0
    check(f"{damage_kind}: strict automatic predicate accepts exact runtime incident", decision["allowed"] is True)

    driver = RotatingRecoveryDriver(ctx["runtime"])
    recovery_start = time.perf_counter()
    started = auto_execute(ctx, proposal, driver)
    recovery_ms = (time.perf_counter() - recovery_start) * 1000.0
    check(f"{damage_kind}: exact recovery reaches independent verification stage", started["result"] == "verifying")
    projection = recovery.response_projection(ctx["state"])
    check(
        f"{damage_kind}: wheel spins only for real VERIFYING backend state",
        projection["backend_state"] == "VERIFYING" and projection["wheel_spinning"] is True,
    )

    duplicate = recovery.execute_automatic_runtime_recovery(
        ctx["state"],
        ctx["incident_id"],
        db_root=ctx["db"],
        runtime_root=ctx["runtime"]["root"],
        proc_root=ctx["proc"],
        fs_root=ctx["fs"],
        uid=ctx["uid"],
        driver=driver,
    )
    check(f"{damage_kind}: duplicate execution never mutates twice", duplicate["result"] == "verifying" and driver.calls == 1)

    verify_start = time.perf_counter()
    completed = finish_verification(ctx)
    verify_ms = (time.perf_counter() - verify_start) * 1000.0
    check(f"{damage_kind}: recovered means final reobservation verified", completed["result"] == "recovered" and completed["verified"] is True)
    final_projection = recovery.response_projection(ctx["state"])
    check(
        f"{damage_kind}: recovered projection is truthful and idle",
        final_projection["backend_state"] == "RECOVERED"
        and final_projection["wheel_spinning"] is False
        and final_projection["outcome"] == "recovered",
    )
    check(
        f"{damage_kind}: exposure semantics remain honest",
        (final_projection.get("exposure") or {}).get("state") == "unknown",
    )
    receipt = recovery._recovery_receipt_valid(ctx["state"], str(completed["receipt_id"]))
    check(
        f"{damage_kind}: one exact durable receipt contains final verification",
        receipt is not None
        and receipt["verified"] is True
        and receipt["automatic_authority"] is True
        and receipt["verification"]["incident_resolved"] is True,
    )
    evidence_files = list((ctx["state"] / "guardian/live-recovery/evidence").glob("*.json"))
    check(f"{damage_kind}: evidence snapshot exists before/through mutation", len(evidence_files) == 1)
    notification_files = list((ctx["state"] / "guardian/live-recovery/notifications").glob("*.json"))
    check(f"{damage_kind}: notifications are deduplicated to start and result", len(notification_files) == 2)

    timings.append({
        "detection_to_incident_ms": detect_ms,
        "correlation_to_decision_ms": decision_ms,
        "recovery_ms": recovery_ms,
        "verification_ms": verify_ms,
        "total_ms": (time.perf_counter() - total_start) * 1000.0,
    })


class CrashOnceDriver:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, proposal: dict) -> dict:
        self.calls += 1
        raise RuntimeError("simulated coordinator interruption")


def main() -> None:
    timings: list[dict[str, float]] = []

    for damage_kind in ("replace", "delete"):
        with tempfile.TemporaryDirectory(prefix=f"maho-auto-{damage_kind}-") as raw:
            base = Path(raw)
            try:
                success_case(base, damage_kind, timings)
            finally:
                make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-auto-drift-") as raw:
        base = Path(raw)
        try:
            ctx = fixture(base)
            provider_observation(ctx["state"])
            proposal = plan(ctx)
            damage(ctx["runtime"], "replace", text="changed-again-after-proposal\n")
            driver = RotatingRecoveryDriver(ctx["runtime"])
            refused = auto_execute(ctx, proposal, driver)
            check(
                "artifact mutation after proposal invalidates stale authority before recovery",
                refused["result"] == "refused"
                and "no-longer-matches-current-release" in refused["reason"]
                and driver.calls == 0,
            )
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-auto-stale-") as raw:
        base = Path(raw)
        try:
            ctx = fixture(base)
            provider_observation(ctx["state"], stale={"security.integrity"})
            proposal = plan(ctx)
            driver = RotatingRecoveryDriver(ctx["runtime"])
            refused = auto_execute(ctx, proposal, driver)
            reasons = (refused.get("automatic_decision") or {}).get("reasons", [])
            check(
                "stale provider evidence blocks automatic mutation",
                refused["result"] == "refused"
                and any(reason.startswith("provider-stale:security.integrity") for reason in reasons)
                and driver.calls == 0,
            )
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-auto-missing-provider-") as raw:
        base = Path(raw)
        try:
            ctx = fixture(base)
            provider_observation(ctx["state"], omit={"guardian.service-events"})
            proposal = plan(ctx)
            driver = RotatingRecoveryDriver(ctx["runtime"])
            refused = auto_execute(ctx, proposal, driver)
            reasons = (refused.get("automatic_decision") or {}).get("reasons", [])
            check(
                "missing provider blocks automatic mutation",
                refused["result"] == "refused"
                and "provider-missing:guardian.service-events" in reasons
                and driver.calls == 0,
            )
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-auto-prior-boot-") as raw:
        base = Path(raw)
        try:
            ctx = fixture(base)
            provider_observation(
                ctx["state"],
                boot_overrides={"security.runtime": "previous-boot"},
            )
            proposal = plan(ctx)
            driver = RotatingRecoveryDriver(ctx["runtime"])
            refused = auto_execute(ctx, proposal, driver)
            reasons = (refused.get("automatic_decision") or {}).get("reasons", [])
            check(
                "fresh heartbeat from prior boot cannot authorize automatic mutation",
                refused["result"] == "refused"
                and "provider-boot-mismatch:security.runtime" in reasons
                and driver.calls == 0,
            )
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-auto-degraded-guardian-") as raw:
        base = Path(raw)
        try:
            ctx = fixture(base)
            provider_observation(ctx["state"], degraded={"guardian.watch"})
            proposal = plan(ctx)
            driver = RotatingRecoveryDriver(ctx["runtime"])
            refused = auto_execute(ctx, proposal, driver)
            reasons = (refused.get("automatic_decision") or {}).get("reasons", [])
            check(
                "degraded Guardian action health blocks automatic mutation",
                refused["result"] == "refused"
                and "provider-unhealthy:guardian.watch:degraded" in reasons
                and driver.calls == 0,
            )
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-auto-no-known-good-") as raw:
        base = Path(raw)
        try:
            ctx = fixture(base)
            previous_probe = ctx["runtime"]["previous"] / "bin/probe"
            os.chmod(previous_probe, 0o644)
            previous_probe.write_text("corrupt-known-good\n", encoding="utf-8")
            os.chmod(previous_probe, 0o444)
            provider_observation(ctx["state"])
            driver = RotatingRecoveryDriver(ctx["runtime"])
            result = recovery.execute_automatic_runtime_recovery(
                ctx["state"],
                ctx["incident_id"],
                db_root=ctx["db"],
                runtime_root=ctx["runtime"]["root"],
                proc_root=ctx["proc"],
                fs_root=ctx["fs"],
                uid=ctx["uid"],
                driver=driver,
            )
            check(
                "missing independently verified replacement is RECOVERY_UNAVAILABLE/no mutation",
                result["result"] == "refused"
                and "previous Maho runtime is not independently verified" in result["reason"]
                and driver.calls == 0,
            )
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-auto-verification-fail-") as raw:
        base = Path(raw)
        try:
            ctx = fixture(base)
            provider_observation(ctx["state"])
            proposal = plan(ctx)
            lying = RotatingRecoveryDriver(ctx["runtime"], claim_ok=False, rotate=True)
            result = auto_execute(ctx, proposal, lying)
            projection = recovery.response_projection(ctx["state"])
            check(
                "deliberate recovery verification failure remains unresolved",
                result["result"] == "verification-failed"
                and projection["backend_state"] == "VERIFICATION_FAILED"
                and projection["wheel_spinning"] is False,
            )
            active_incident = ctx["state"] / "incidents/active" / f"{ctx['incident_id']}.json"
            check("verification failure does not erase incident evidence", active_incident.exists())
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-auto-reboot-resume-") as raw:
        base = Path(raw)
        try:
            ctx = fixture(base)
            provider_observation(ctx["state"])
            proposal = plan(ctx)
            crash = CrashOnceDriver()
            interrupted = False
            try:
                auto_execute(ctx, proposal, crash)
            except RuntimeError as exc:
                interrupted = "simulated coordinator interruption" in str(exc)
            check("reboot-resume fixture reaches durable RECOVERING before mutation", interrupted and crash.calls == 1)
            (ctx["proc"] / "sys/kernel/random/boot_id").write_text("new-boot", encoding="utf-8")
            driver = RotatingRecoveryDriver(ctx["runtime"])
            blocked = recovery.execute_automatic_runtime_recovery(
                ctx["state"],
                ctx["incident_id"],
                db_root=ctx["db"],
                runtime_root=ctx["runtime"]["root"],
                proc_root=ctx["proc"],
                fs_root=ctx["fs"],
                uid=ctx["uid"],
                driver=driver,
            )
            projection = recovery.response_projection(ctx["state"])
            check(
                "reboot invalidates pre-reboot automatic mutation authority",
                blocked["result"] == "evidence-insufficient"
                and projection["backend_state"] == "EVIDENCE_INSUFFICIENT"
                and projection["wheel_spinning"] is False
                and driver.calls == 0,
            )
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-auto-claim-interruption-") as raw:
        base = Path(raw)
        try:
            ctx = fixture(base)
            provider_observation(ctx["state"])
            proposal = plan(ctx)
            decision = recovery.automatic_recovery_policy(ctx["state"], proposal, proc_root=ctx["proc"])
            evidence = recovery._preserve_automatic_evidence(ctx["state"], proposal, decision)
            operation_id = recovery._automatic_operation_id(proposal, evidence)
            claimed, _ = recovery._claim_automatic_operation(
                ctx["state"],
                operation_id,
                incident_id=ctx["incident_id"],
                proposal_id=proposal["proposal_id"],
                evidence_snapshot_digest=evidence["evidence_snapshot_digest"],
            )
            check("fixture simulates crash after operation claim before RECOVERING", claimed is True)
            driver = RotatingRecoveryDriver(ctx["runtime"])
            resumed = auto_execute(ctx, proposal, driver)
            check(
                "claimed operation reconstructs RECOVERING and resumes after preparation crash",
                resumed["result"] == "verifying" and driver.calls == 1,
            )
            completed = finish_verification(ctx)
            check("preparation-crash recovery still reaches verified result", completed["result"] == "recovered")
            receipts = list((ctx["state"] / "guardian/live-recovery/receipts").glob("*.json"))
            check("preparation-crash recovery keeps one deterministic receipt identity", len(receipts) == 1)
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-auto-interruption-") as raw:
        base = Path(raw)
        try:
            ctx = fixture(base)
            provider_observation(ctx["state"])
            proposal = plan(ctx)
            crash = CrashOnceDriver()
            interrupted = False
            try:
                auto_execute(ctx, proposal, crash)
            except RuntimeError as exc:
                interrupted = "simulated coordinator interruption" in str(exc)
            active = recovery._read(recovery._active_path(ctx["state"], ctx["incident_id"]))
            projection = recovery.response_projection(ctx["state"])
            check(
                "interruption after durable claim leaves resumable RECOVERING state",
                interrupted and crash.calls == 1 and active is not None and active["state"] == "recovering",
            )
            check(
                "RECOVERING projection spins only because backend is actually recovering",
                projection["backend_state"] == "RECOVERING" and projection["wheel_spinning"] is True,
            )
            resumed_driver = RotatingRecoveryDriver(ctx["runtime"])
            resumed = recovery.execute_automatic_runtime_recovery(
                ctx["state"],
                ctx["incident_id"],
                db_root=ctx["db"],
                runtime_root=ctx["runtime"]["root"],
                proc_root=ctx["proc"],
                fs_root=ctx["fs"],
                uid=ctx["uid"],
                driver=resumed_driver,
            )
            check(
                "coordinator restart resumes one deterministic operation",
                resumed["result"] == "verifying" and resumed_driver.calls == 1,
            )
            completed = finish_verification(ctx)
            check("interrupted operation can finish verified", completed["result"] == "recovered")
        finally:
            make_tree_writable(base)

    keys = (
        "detection_to_incident_ms",
        "correlation_to_decision_ms",
        "recovery_ms",
        "verification_ms",
        "total_ms",
    )
    report = {
        key: {
            "median": round(median(row[key] for row in timings), 3),
            "worst": round(max(row[key] for row in timings), 3),
        }
        for key in keys
    }
    print("TIMING", json.dumps(report, sort_keys=True))
    print("ALL GUARDIAN AUTOMATIC RUNTIME RESPONSE TESTS PASS")


if __name__ == "__main__":
    main()
