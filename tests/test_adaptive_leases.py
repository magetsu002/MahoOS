#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_adaptive_leases import LeaseBook, active_posture, book_from_dict, reconcile_leases, verify_shadow
from maho_adaptive_proposal import Effect, ExpiryCondition, create_proposal
from maho_adaptive_resolver import resolve_posture
from maho_adaptive_situation import build_situation

T0 = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)
OBS = "2026-09-11T23:59:30Z"


def situation(current=None):
    env = lambda data: {"observed_at": OBS, "data": data}
    return build_situation({
        "power": env({"percentage": 15, "ac_online": False}),
        "thermal": env({"max_millidegree_c": 88000, "sustained_seconds": 300}),
        "adaptive_posture": {"effective_posture": current or {}, "active_leases": [], "source_policies": []},
    }, captured_at=T0)


def proposal(s, source="thermal.hot", priority="thermal-protection", value="reduced", dwell=10, residency=20, cooldown=30):
    return create_proposal(
        source_policy=source, policy_version="1", situation_snapshot_id=s.snapshot_id,
        priority_domain=priority, disruption_class="A", confidence=.95,
        reason="sustained condition", supporting_evidence=["sustained"],
        requested_effects=[Effect("background_work", value)],
        minimum_dwell_seconds=dwell, minimum_residency_seconds=residency,
        cooldown_seconds=cooldown, expiry_condition=ExpiryCondition("condition-clears", source),
        created_at=T0,
    )


def main() -> None:
    s = situation(current={"background_work": "normal"})
    p = proposal(s)
    resolved = resolve_posture(s, [p])
    book = reconcile_leases(LeaseBook(), resolved, [p], condition_state={p.proposal_id: True}, previous_posture={"background_work": "normal"}, now=T0)
    assert len(book.leases) == 1 and book.leases[0].state == "PROPOSED"
    assert active_posture(book) == {}

    same = reconcile_leases(book, resolved, [p], condition_state={p.proposal_id: True}, now=T0 + timedelta(seconds=5))
    assert len(same.leases) == 1 and same.leases[0].state == "PROPOSED"

    active = reconcile_leases(same, resolved, [p], condition_state={p.proposal_id: True}, now=T0 + timedelta(seconds=11))
    assert len(active.leases) == 1 and active.leases[0].state == "ACTIVE_SHADOW"
    assert active_posture(active) == {"background_work": "reduced"}
    verified = verify_shadow(active, active.leases[0].lease_id)
    assert verified.leases[0].state == "VERIFIED_SHADOW"
    assert book_from_dict(verified.as_dict()) == verified

    # A confirmed clear before minimum residency preserves the active lease.
    early_clear = reconcile_leases(verified, resolved, [p], condition_state={p.proposal_id: False}, now=T0 + timedelta(seconds=15))
    assert early_clear.leases[0].state == "VERIFIED_SHADOW"

    expired = reconcile_leases(early_clear, resolved, [p], condition_state={p.proposal_id: False}, now=T0 + timedelta(seconds=25))
    assert expired.leases[0].state == "EXPIRED"
    assert active_posture(expired) == {}
    assert expired.leases[0].previous_state == "normal"
    # Previous state is recorded for explanation only; it is not blindly restored.
    assert "background_work" not in active_posture(expired)

    # Cooldown blocks immediate re-entry and later permits a new lease.
    blocked = reconcile_leases(expired, resolved, [p], condition_state={p.proposal_id: True}, now=T0 + timedelta(seconds=40))
    assert len(blocked.leases) == 1
    reentered = reconcile_leases(expired, resolved, [p], condition_state={p.proposal_id: True}, now=T0 + timedelta(seconds=60))
    assert len(reentered.leases) == 2
    assert reentered.leases[-1].lease_id != expired.leases[0].lease_id

    # Higher-priority coherent ownership supersedes through the resolver.
    s2 = situation(current={"background_work": "reduced"})
    low = proposal(s2, source="battery.low", priority="battery-survival", value="reduced", dwell=0, residency=100)
    high = proposal(s2, source="thermal.hot", priority="thermal-protection", value="suspended", dwell=0, residency=0)
    rlow = resolve_posture(s2, [low])
    b = reconcile_leases(LeaseBook(), rlow, [low], condition_state={low.proposal_id: True}, previous_posture={"background_work": "reduced"}, now=T0)
    rhigh = resolve_posture(s2, [low, high])
    b2 = reconcile_leases(b, rhigh, [low, high], condition_state={low.proposal_id: True, high.proposal_id: True}, now=T0 + timedelta(seconds=1))
    assert b2.leases[0].state == "EXPIRED"
    assert b2.leases[0].superseded_by == b2.leases[1].lease_id
    assert active_posture(b2)["background_work"] == "suspended"
    assert all(lease.mode == "shadow" for lease in b2.leases)
    assert all("EXECUTABLE" not in lease.state for lease in b2.leases)

    # Backward time jump does not satisfy dwell.
    jumped = reconcile_leases(LeaseBook(), resolved, [p], condition_state={p.proposal_id: True}, previous_posture={"background_work": "normal"}, now=T0)
    jumped = reconcile_leases(jumped, resolved, [p], condition_state={p.proposal_id: True}, now=T0 - timedelta(hours=1))
    assert jumped.leases[0].state == "PROPOSED"

    print("ALL ADAPTIVE LEASE TESTS PASS")


if __name__ == "__main__":
    main()
