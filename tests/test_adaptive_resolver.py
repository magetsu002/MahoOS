#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_adaptive_proposal import Effect, create_proposal
from maho_adaptive_resolver import resolve_posture
from maho_adaptive_situation import build_situation

NOW = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)
OBSERVED = "2026-09-11T23:59:30Z"


def env(data, at=OBSERVED): return {"observed_at": at, "data": data}


def snap(*, stale_power=False, current=None):
    power_at = "2026-09-11T23:40:00Z" if stale_power else OBSERVED
    return build_situation({
        "power": env({"percentage": 18, "ac_online": False}, power_at),
        "thermal": env({"max_millidegree_c": 88000, "sustained_seconds": 180}),
        "workload": env({"probable_gaming": True, "interactive": True, "confidence": .95}),
        "network": env({"connectivity": "online", "stability": "stable", "default_route": True, "reachable": True}),
        "maintenance": env({"transaction_state": "PREPARED", "prepared": True}),
        "guardian": env({"active_incident": False, "severity_level": 0, "recovery_in_progress": False, "unresolved_reliability": False}),
        "user_intent": env({"power_mode": "performance", "foreground_performance": True, "dnd": False}),
        "adaptive_posture": {"effective_posture": current or {}, "active_leases": [], "source_policies": []},
    }, captured_at=NOW)


def prop(s, source, priority, effect, value, *, confidence=.9, disruption="A", evidence=("fresh",)):
    return create_proposal(
        source_policy=source, policy_version="1", situation_snapshot_id=s.snapshot_id,
        priority_domain=priority, disruption_class=disruption, confidence=confidence,
        reason=f"{source} requests {effect}={value}", supporting_evidence=evidence,
        requested_effects=[Effect(effect, value)], created_at=NOW,
    )


def field(result, key):
    return next(item for item in result.fields if item.effect == key)


def main() -> None:
    s = snap()
    battery = prop(s, "battery.low", "battery-survival", "maintenance", "suspended")
    thermal = prop(s, "thermal.hot", "thermal-protection", "maintenance", "suspended")
    gaming = prop(s, "gaming.foreground", "foreground-task-continuity", "foreground_performance", "preserve", confidence=.96)
    r = resolve_posture(s, [battery, gaming, thermal])
    assert dict(r.effective_posture)["maintenance"] == "suspended"
    assert field(r, "maintenance").winning_proposal_ids == (thermal.proposal_id,)
    assert dict(r.effective_posture)["foreground_performance"] == "preserve"
    assert resolve_posture(s, [thermal, battery, gaming]) == r

    background = prop(s, "battery.optimize", "background-efficiency", "foreground_performance", "balanced")
    intent = prop(s, "intent.performance", "explicit-user-intent", "foreground_performance", "preserve")
    assert dict(resolve_posture(s, [background, intent]).effective_posture)["foreground_performance"] == "preserve"

    user = prop(s, "intent.performance", "explicit-user-intent", "power_survival", "normal")
    safety = prop(s, "power.hardware-danger", "hardware-data-safety", "power_survival", "critical-review")
    assert dict(resolve_posture(s, [user, safety]).effective_posture)["power_survival"] == "critical-review"

    stale = snap(stale_power=True, current={"background_work": "normal"})
    stale_prop = prop(stale, "battery.low", "battery-survival", "background_work", "reduced")
    stale_result = resolve_posture(stale, [stale_prop])
    assert dict(stale_result.effective_posture)["background_work"] == "normal"
    assert stale_result.rejected == ((stale_prop.proposal_id, "evidence-stale"),)

    low = prop(s, "gaming.maybe", "foreground-task-continuity", "notifications", "quiet", confidence=.3)
    assert resolve_posture(s, [low]).rejected == ((low.proposal_id, "low-confidence"),)

    a = prop(s, "network.alpha", "background-efficiency", "network_background", "normal", evidence=("x",))
    b = prop(s, "network.bravo", "background-efficiency", "network_background", "suspended", evidence=("x",))
    ambiguous = resolve_posture(s, [a, b])
    assert field(ambiguous, "network_background").status == "ambiguous"
    assert "network_background" not in dict(ambiguous.effective_posture)

    kept = snap(current={"network_background": "normal"})
    a2 = prop(kept, "network.alpha", "background-efficiency", "network_background", "normal", evidence=("x",))
    b2 = prop(kept, "network.bravo", "background-efficiency", "network_background", "suspended", evidence=("x",))
    tied = resolve_posture(kept, [a2, b2])
    assert dict(tied.effective_posture)["network_background"] == "normal"
    assert field(tied, "network_background").status == "preserved"

    visible = prop(s, "battery.visible", "battery-survival", "display_brightness", "lower", disruption="C")
    destructive = prop(s, "power.destructive", "hardware-data-safety", "power_action", "shutdown-review", disruption="D")
    review = resolve_posture(s, [visible, destructive])
    assert not review.effective_posture
    assert len(review.review_required) == 2

    print("ALL ADAPTIVE RESOLVER TESTS PASS")


if __name__ == "__main__":
    main()
