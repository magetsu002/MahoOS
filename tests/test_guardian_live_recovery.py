#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

import guardian_live_recovery as recovery  # noqa: E402
import guardian_live_response as response  # noqa: E402
from test_guardian_live_response import FakeDriver, fixture as containment_fixture  # noqa: E402
from test_guardian_runtime_recovery import make_release, make_tree_writable  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def _rewrite_runtime_subject(ctx: dict) -> None:
    desc = next(ctx["db"].glob("*/desc"))
    text = desc.read_text(encoding="utf-8").replace("%NAME%\nalpha\n", "%NAME%\nmaho-runtime\n")
    desc.write_text(text, encoding="utf-8")
    source = json.loads(ctx["source_path"].read_text(encoding="utf-8"))
    source["subject"] = {"type": "package", "id": "maho-runtime"}
    source["signals"].append({
        "kind": "integrity-drift",
        "source": "pacman-mtree",
        "details": {"path": "/usr/bin/alpha"},
    })
    ctx["source_path"].write_text(json.dumps(source, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assessment_path = ctx["state"] / "guardian/active" / f"{ctx['incident_id']}.json"
    assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
    assessment["subject"] = {"type": "package", "id": "maho-runtime"}
    assessment_path.write_text(json.dumps(assessment, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _runtime_fixture(base: Path) -> dict:
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


def _contain(ctx: dict) -> dict:
    proposal = response.plan_incident(
        ctx["state"],
        ctx["incident_id"],
        db_root=ctx["db"],
        proc_root=ctx["proc"],
        fs_root=ctx["fs"],
        uid=ctx["uid"],
    )
    if proposal.get("state") != "authorization-required":
        raise AssertionError(f"containment proposal unavailable: {proposal}")
    response.reconcile(
        ctx["state"],
        db_root=ctx["db"],
        proc_root=ctx["proc"],
        fs_root=ctx["fs"],
        uid=ctx["uid"],
    )
    authority = response.authorize_containment(
        ctx["state"],
        ctx["incident_id"],
        proposal["proposal_id"],
        confirm=f"AUTHORIZE-CONTAIN:{proposal['proposal_id']}",
    )
    driver = FakeDriver()
    original = response._driver
    response._driver = lambda **_kwargs: driver
    try:
        result = response.execute_authorized(
            ctx["state"],
            authority["authority_id"],
            db_root=ctx["db"],
            proc_root=ctx["proc"],
            fs_root=ctx["fs"],
            uid=ctx["uid"],
        )
    finally:
        response._driver = original
    if result.get("result") != "contained":
        raise AssertionError(f"containment failed: {result}")
    return response._read_object(response._active_path(ctx["state"], ctx["incident_id"])) or {}


class RotatingRecoveryDriver:
    def __init__(self, runtime: dict, *, claim_ok: bool = True, rotate: bool = True) -> None:
        self.runtime = runtime
        self.claim_ok = claim_ok
        self.rotate = rotate
        self.calls = 0

    def execute(self, proposal: dict) -> dict:
        self.calls += 1
        if self.rotate:
            current = self.runtime["current_link"]
            previous = self.runtime["previous_link"]
            old_current = current.resolve()
            old_previous = previous.resolve()
            current.unlink()
            current.symlink_to(old_previous)
            previous.unlink()
            previous.symlink_to(old_current)
        return {
            "ok": self.claim_ok,
            "managed_wiring_verified": self.claim_ok,
            "daemon_reload_verified": self.claim_ok,
            "services_verified": self.claim_ok,
        }


def _plan(ctx: dict, runtime: dict) -> dict:
    return recovery.plan_runtime_recovery(
        ctx["state"],
        ctx["incident_id"],
        db_root=ctx["db"],
        runtime_root=runtime["root"],
        proc_root=ctx["proc"],
        fs_root=ctx["fs"],
        uid=ctx["uid"],
    )


def _execute(ctx: dict, runtime: dict, authority: dict, driver) -> dict:
    return recovery.execute_runtime_recovery(
        ctx["state"],
        authority["authority_id"],
        db_root=ctx["db"],
        runtime_root=runtime["root"],
        proc_root=ctx["proc"],
        fs_root=ctx["fs"],
        uid=ctx["uid"],
        driver=driver,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-live-recovery-") as raw:
        base = Path(raw)
        try:
            ctx = containment_fixture(base / "security")
            _rewrite_runtime_subject(ctx)
            runtime = _runtime_fixture(base / "runtime-fixture")

            missing_containment = _plan(ctx, runtime)
            check(
                "runtime recovery cannot be proposed before exact containment",
                missing_containment.get("reason") == "exact-containment-not-active",
            )

            contained = _contain(ctx)
            check("fixture reached exact contained state", contained.get("state") == "contained")

            proposal = _plan(ctx, runtime)
            check(
                "contained causally proven Maho runtime yields separate recovery proposal",
                proposal.get("state") == "authorization-required",
            )
            check(
                "runtime recovery reuses certified provider and stays manually authorized",
                proposal["handoff"]["provider"] == "maho-runtime"
                and proposal["handoff"]["action"] == "rollback-previous"
                and proposal["automatic_authority"] is False,
            )
            check(
                "runtime recovery binds exact current and independently verified previous releases",
                proposal["runtime"]["current"]["path"] == str(runtime["current"])
                and proposal["runtime"]["previous"]["path"] == str(runtime["previous"])
                and proposal["runtime"]["previous"]["verified"] is True,
            )

            denied = recovery.authorize_runtime_recovery(
                ctx["state"],
                ctx["incident_id"],
                proposal["proposal_id"],
                confirm="no",
            )
            check("runtime recovery requires explicit confirmation token", denied["result"] == "denied")

            authority = recovery.authorize_runtime_recovery(
                ctx["state"],
                ctx["incident_id"],
                proposal["proposal_id"],
                confirm=f"AUTHORIZE-RUNTIME-RECOVERY:{proposal['proposal_id']}",
            )
            check(
                "runtime recovery authority is explicit bounded and separate from containment",
                authority.get("user_authorized") is True
                and authority.get("action") == "rollback-previous"
                and authority.get("authority_id", "").startswith("recovery-auth-"),
            )

            driver = RotatingRecoveryDriver(runtime)
            completed = _execute(ctx, runtime, authority, driver)
            check(
                "authorized runtime recovery rotates exact generation pair and verifies it",
                completed.get("result") == "recovered"
                and completed.get("verified") is True
                and runtime["current_link"].resolve() == runtime["previous"]
                and runtime["previous_link"].resolve() == runtime["current"],
            )
            check("runtime recovery authority is single-use", _execute(ctx, runtime, authority, driver)["result"] == "refused")
            check("runtime recovery adapter executes exactly once", driver.calls == 1)
            status = recovery.recovery_status(ctx["state"])
            check("canonical live recovery state reports recovered", status["state"] == "recovered" and status["automatic_authority"] is False)
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-live-recovery-lying-") as raw:
        base = Path(raw)
        try:
            ctx = containment_fixture(base / "security")
            _rewrite_runtime_subject(ctx)
            runtime = _runtime_fixture(base / "runtime-fixture")
            _contain(ctx)
            proposal = _plan(ctx, runtime)
            authority = recovery.authorize_runtime_recovery(
                ctx["state"],
                ctx["incident_id"],
                proposal["proposal_id"],
                confirm=f"AUTHORIZE-RUNTIME-RECOVERY:{proposal['proposal_id']}",
            )
            lying = RotatingRecoveryDriver(runtime, claim_ok=True, rotate=False)
            result = _execute(ctx, runtime, authority, lying)
            check(
                "driver cannot claim recovery without coordinator-observed pointer rotation",
                result.get("result") == "verification-failed" and result.get("verified") is False,
            )
            check(
                "failed recovery remains visible rather than falsely resolved",
                recovery.recovery_status(ctx["state"])["state"] == "verification-failed",
            )
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-live-recovery-drift-") as raw:
        base = Path(raw)
        try:
            ctx = containment_fixture(base / "security")
            _rewrite_runtime_subject(ctx)
            runtime = _runtime_fixture(base / "runtime-fixture")
            _contain(ctx)
            proposal = _plan(ctx, runtime)
            authority = recovery.authorize_runtime_recovery(
                ctx["state"],
                ctx["incident_id"],
                proposal["proposal_id"],
                confirm=f"AUTHORIZE-RUNTIME-RECOVERY:{proposal['proposal_id']}",
            )
            replacement = make_release(runtime["releases"], "3" * 40)
            runtime["previous_link"].unlink()
            runtime["previous_link"].symlink_to(replacement)
            driver = RotatingRecoveryDriver(runtime)
            refused = _execute(ctx, runtime, authority, driver)
            check(
                "runtime pointer drift after authorization invalidates recovery before mutation",
                refused.get("result") == "refused" and driver.calls == 0,
            )
        finally:
            make_tree_writable(base)

    with tempfile.TemporaryDirectory(prefix="maho-live-recovery-unverified-") as raw:
        base = Path(raw)
        try:
            ctx = containment_fixture(base / "security")
            _rewrite_runtime_subject(ctx)
            runtime = _runtime_fixture(base / "runtime-fixture")
            _contain(ctx)
            os.chmod(runtime["previous"] / "bin/probe", 0o644)
            proposal = _plan(ctx, runtime)
            check(
                "unverified previous runtime cannot become live recovery authority",
                proposal.get("state") == "none" and "previous Maho runtime is not independently verified" in proposal.get("reason", ""),
            )
        finally:
            make_tree_writable(base)

    print("ALL GUARDIAN LIVE RUNTIME RECOVERY TESTS PASS")


if __name__ == "__main__":
    main()
