#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_containment import ContainmentAuthority, ContainmentPlanState, ContainmentTarget, ProcessIdentity, plan_containment
from guardian_containment_adapter import execute_containment, release_containment

NOW = "2026-09-15T12:00:00Z"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def target() -> ContainmentTarget:
    return ContainmentTarget(
        package="maho-runtime",
        version="1.2.3-1",
        finding_id="finding-001",
        processes=(
            ProcessIdentity(201, 9001, "/usr/bin/maho-runtime"),
            ProcessIdentity(202, 9002, "/usr/bin/maho-runtime"),
        ),
    )


def authority(value: ContainmentTarget, *, verified: bool = True, digest: str | None = None, expires: str = "2026-09-15T12:05:00Z") -> ContainmentAuthority:
    return ContainmentAuthority(
        authority_id="contain-auth-001",
        issuer="guardian-policy",
        verified=verified,
        issued_at="2026-09-15T11:55:00Z",
        expires_at=expires,
        target_digest=digest or value.digest,
        evidence_ids=("incident:001", "causal-edge:001"),
        reversible=True,
    )


class FakeDriver:
    def __init__(self, mode: str = "exact") -> None:
        self.mode = mode
        self.releases: list[str] = []

    def freeze_exact(self, value: ContainmentTarget):
        rows = [item.__dict__ for item in value.processes]
        if self.mode == "subset":
            rows = rows[:1]
        return {"result": "contained", "session_id": "contain-test-session", "contained": rows, "failed": []}

    def release_exact(self, session_id: str, value: ContainmentTarget):
        self.releases.append(session_id)
        return {"result": "released", "released": [item.pid for item in value.processes], "failed": []}


def main() -> None:
    value = target()
    ready = plan_containment(value, authority(value), now=NOW)
    check("verified exact bounded authority produces ready plan", ready.state is ContainmentPlanState.READY)
    check("rollback action is explicitly reversible", ready.rollback_action == "resume-exact-session")

    unverified = plan_containment(value, authority(value, verified=False), now=NOW)
    check("unverified authority cannot contain", unverified.state is ContainmentPlanState.REFUSE)

    mismatch = plan_containment(value, authority(value, digest="0" * 64), now=NOW)
    check("authority for another target cannot contain", mismatch.state is ContainmentPlanState.REFUSE)

    expired = plan_containment(value, authority(value, expires="2026-09-15T11:59:59Z"), now=NOW)
    check("expired containment authority fails closed", expired.state is ContainmentPlanState.REFUSE)

    try:
        ContainmentTarget("maho-*", "1", "finding", (ProcessIdentity(201, 1, "/bin/x"),))
    except ValueError:
        broad_rejected = True
    else:
        broad_rejected = False
    check("wildcard containment targets are structurally rejected", broad_rejected)

    driver = FakeDriver()
    receipt = execute_containment(ready, driver)
    check("adapter executes only ready plan", receipt.result == "contained" and receipt.verified)
    check("receipt binds exact target digest", receipt.target_digest == value.digest)
    check("receipt carries exact rollback session", receipt.rollback.get("session_id") == "contain-test-session")
    released = release_containment(receipt, value, driver)
    check("bound receipt can release exact session", released["result"] == "released" and driver.releases == ["contain-test-session"])

    bad_driver = FakeDriver("subset")
    failed = execute_containment(ready, bad_driver)
    check("partial or broadened adapter result is not certified", failed.result == "verification-failed" and not failed.verified)
    check("failed exact verification requests rollback", bad_driver.releases == ["contain-test-session"])

    refused_receipt = execute_containment(unverified, FakeDriver())
    check("adapter cannot invent authority", refused_receipt.result == "refused")

    print("ALL GUARDIAN CONTAINMENT TESTS PASS")


if __name__ == "__main__":
    main()
