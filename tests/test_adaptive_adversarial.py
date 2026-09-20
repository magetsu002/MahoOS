#!/usr/bin/env python3
from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_adaptive_battery import assess_battery, battery_proposals
from maho_adaptive_integrations import guardian_proposals
from maho_adaptive_leases import LeaseBook, active_posture, book_from_dict, reconcile_leases
from maho_adaptive_maintenance import assess_maintenance, maintenance_proposals, recheck_before_mutation
from maho_adaptive_network import network_proposals
from maho_adaptive_observers import ProcessEvidence, SessionEvidence, WindowEvidence, classify_workload
from maho_adaptive_proposal import Effect, create_proposal, proposal_from_dict
from maho_adaptive_resolver import resolve_posture
from maho_adaptive_situation import UNKNOWN, build_situation
from maho_adaptive_thermal import thermal_proposals
from maho_adaptive_workload import workload_proposals

T0 = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)
FRESH = "2026-09-11T23:59:30Z"
STALE = "2026-09-11T23:40:00Z"
SEEN: set[str] = set()

def mark(name: str) -> None:
    SEEN.add(name)

def env(data, at=FRESH):
    return {"observed_at": at, "data": data}

def snapshot(*, captured=T0, observed=FRESH, **patches):
    base = {
        "power": {"battery_present": True, "percentage": 80, "ac_online": True,
                  "charging_state": "charging", "drain_trend": "stable", "ac_stable_seconds": 600},
        "thermal": {"max_millidegree_c": 70000, "sustained_seconds": 600, "trend": "stable"},
        "session": {"locked": True, "lock_dwell_seconds": 1800, "idle_seconds": 1800,
                    "recent_input_seconds": 1800, "inhibitors": []},
        "workload": {"fullscreen": False, "probable_gaming": False, "probable_compile": False,
                     "probable_rendering": False, "probable_media": False, "interactive": False,
                     "high_background_cpu": False, "gpu_activity": False, "confidence": .95, "evidence": []},
        "network": {"connectivity": "online", "default_route": True, "reachable": True,
                    "stability": "stable", "stability_seconds": 600},
        "maintenance": {"transaction_state": "PREPARED", "pending": True, "staged": True,
                        "prepared": True, "recovery_prerequisites": True, "in_critical_section": False,
                        "interruption_safe": True, "enough_disk": True},
        "guardian": {"active_incident": False, "severity_level": 0,
                     "recovery_in_progress": False, "unresolved_reliability": False},
        "user_intent": {"power_mode": "balanced", "foreground_performance": False,
                        "dnd": False, "explicit_maintenance": False, "adaptation_opt_outs": []},
    }
    times = {key: observed for key in base}
    for domain, patch in patches.items():
        if domain.endswith("_observed"):
            times[domain.removesuffix("_observed")] = patch
        else:
            base[domain].update(patch)
    observations = {key: env(value, times[key]) for key, value in base.items()}
    observations["adaptive_posture"] = {"effective_posture": {}, "active_leases": [], "source_policies": []}
    return build_situation(observations, captured_at=captured)

def effects(proposals):
    return {(effect.key, effect.value) for proposal in proposals for effect in proposal.requested_effects}

def proposal(s, source, priority, key, value, *, confidence=.95, disruption="A", created=T0):
    return create_proposal(
        source_policy=source, policy_version="1", situation_snapshot_id=s.snapshot_id,
        priority_domain=priority, disruption_class=disruption, confidence=confidence,
        reason=f"{source} requests {key}={value}", supporting_evidence=["deterministic-test"],
        requested_effects=[Effect(key, value)], minimum_dwell_seconds=0,
        minimum_residency_seconds=0, cooldown_seconds=0, created_at=created,
    )

def raises(callable_, text: str) -> None:
    try:
        callable_()
    except ValueError as exc:
        assert text in str(exc), (text, str(exc))
    else:
        raise AssertionError(f"expected ValueError containing {text!r}")

def battery_cases() -> None:
    low = snapshot(power={"percentage": 34, "ac_online": False, "charging_state": "discharging", "drain_trend": "falling", "ac_stable_seconds": 600})
    ps = battery_proposals(low, created_at=T0)
    assert ("maintenance", "suspended") in effects(ps)
    lease = reconcile_leases(LeaseBook(), resolve_posture(low, ps), list(ps),
                             condition_state={p.proposal_id: True for p in ps}, now=T0)
    assert not active_posture(lease)
    lease = reconcile_leases(lease, resolve_posture(low, ps), list(ps),
                             condition_state={p.proposal_id: True for p in ps}, now=T0 + timedelta(seconds=20))
    assert not active_posture(lease)
    mark("battery crosses threshold briefly")
    cleared = snapshot(power={"percentage": 36, "ac_online": False, "charging_state": "discharging", "ac_stable_seconds": 600})
    assert battery_proposals(cleared, created_at=T0) == ()
    expired = reconcile_leases(lease, resolve_posture(cleared, ()), list(ps),
                               condition_state={p.proposal_id: False for p in ps}, now=T0 + timedelta(seconds=21))
    assert not active_posture(expired)
    blocked = reconcile_leases(expired, resolve_posture(low, ps), list(ps),
                               condition_state={p.proposal_id: True for p in ps}, now=T0 + timedelta(seconds=25))
    assert len(blocked.leases) == len(expired.leases)
    mark("battery oscillates around threshold")

    flap = snapshot(power={"percentage": 8, "ac_online": True, "charging_state": "charging", "ac_stable_seconds": 2})
    assert assess_battery(flap).band == "UNKNOWN" and battery_proposals(flap, created_at=T0) == ()
    mark("charger flaps")
    stable = snapshot(power={"percentage": 8, "ac_online": True, "charging_state": "charging", "ac_stable_seconds": 30})
    assert assess_battery(stable).band == "NORMAL" and battery_proposals(stable, created_at=T0) == ()
    mark("charger reconnects")

    game = snapshot(power={"percentage": 15, "ac_online": False, "charging_state": "discharging"},
                    workload={"probable_gaming": True, "interactive": True, "confidence": .99})
    assert ("foreground_performance", "preserve") in effects(battery_proposals(game, created_at=T0))
    mark("low battery + gaming")
    perf = snapshot(power={"percentage": 15, "ac_online": False, "charging_state": "discharging"},
                    user_intent={"power_mode": "performance", "foreground_performance": True})
    assert ("foreground_performance", "preserve") in effects(battery_proposals(perf, created_at=T0))
    mark("low battery + explicit Performance")
    idle = snapshot(power={"percentage": 15, "ac_online": False, "charging_state": "discharging"})
    assert ("background_work", "reduced") in effects(battery_proposals(idle, created_at=T0))
    mark("low battery + idle")
    stale = snapshot(power={"percentage": 5, "ac_online": False}, power_observed=STALE)
    assert battery_proposals(stale, created_at=T0) == ()
    mark("stale battery observation")

def thermal_cases() -> None:
    assert thermal_proposals(snapshot(thermal={"max_millidegree_c": 86000, "sustained_seconds": 5}), created_at=T0) == ()
    mark("short thermal spike")
    hot = thermal_proposals(snapshot(thermal={"max_millidegree_c": 86000, "sustained_seconds": 90, "trend": "rising"}), created_at=T0)
    assert ("maintenance", "suspended") in effects(hot)
    mark("sustained heat")
    for temp, dwell in ((84900, 300), (85100, 2), (84800, 400), (85200, 20)):
        assert thermal_proposals(snapshot(thermal={"max_millidegree_c": temp, "sustained_seconds": dwell}), created_at=T0) == ()
    mark("thermal oscillation")
    missing = snapshot(thermal={"max_millidegree_c": None, "sustained_seconds": None})
    assert missing.thermal.level == UNKNOWN and thermal_proposals(missing, created_at=T0) == ()
    mark("missing thermal sensor")
    absurd = snapshot(thermal={"max_millidegree_c": 9999999, "sustained_seconds": 500})
    assert absurd.thermal.maximum_millidegree_c == UNKNOWN and thermal_proposals(absurd, created_at=T0) == ()
    mark("absurd sensor value")
    recovered = snapshot(thermal={"max_millidegree_c": 76000, "sustained_seconds": 10, "trend": "falling"})
    assert thermal_proposals(recovered, created_at=T0) == ()
    mark("thermal recovery")

def workload_cases() -> None:
    sess = SessionEvidence(locked=False, idle_seconds=1, recent_input_seconds=1)
    steam = ProcessEvidence(10, 1, "steam", "/usr/bin/steam", 500, 2)
    c = classify_workload([steam], WindowEvidence(False, 10, "Steam", "steam"), sess)
    assert c.probable_gaming is False
    mark("Steam open but no game")
    game = ProcessEvidence(20, 10, "gamescope", "/usr/bin/gamescope", 120, 10, foreground=True, gpu=True)
    c = classify_workload([steam, game], WindowEvidence(True, 20, "Game", "game"), sess)
    assert c.probable_gaming is True
    mark("actual fullscreen game evidence")
    video = ProcessEvidence(30, 1, "mpv", "/usr/bin/mpv", 120, 3, foreground=True)
    c = classify_workload([video], WindowEvidence(True, 30, "Video", "mpv"), sess, audio_active=True)
    assert c.probable_media is True and c.probable_gaming is False
    mark("fullscreen video")
    brief = ProcessEvidence(41, 40, "gcc", "/usr/bin/gcc", 2, .4)
    assert classify_workload([brief], WindowEvidence(False, None), sess).probable_compile is False
    mark("compile process exists briefly")
    make = ProcessEvidence(40, 1, "make", "/usr/bin/make", 30, 5)
    gcc = ProcessEvidence(41, 40, "gcc", "/usr/bin/gcc", 25, 6)
    compiled = classify_workload([make, gcc], WindowEvidence(False, None), sess)
    assert compiled.probable_compile is True and compiled.respected_background_job
    mark("sustained compile")

    locked_compile = snapshot(workload={"probable_compile": True, "confidence": .99})
    assert not assess_maintenance(locked_compile).eligible
    mark("locked while compiling")
    locked_render = snapshot(workload={"probable_rendering": True, "confidence": .99})
    assert not assess_maintenance(locked_render).eligible
    mark("render job while locked")

def maintenance_cases() -> None:
    assert not assess_maintenance(snapshot(session={"lock_dwell_seconds": 1})).eligible
    mark("lock for 1 second")
    for dwell in (1, 5, 0, 7):
        assert not assess_maintenance(snapshot(session={"locked": dwell > 0, "lock_dwell_seconds": dwell})).eligible
    mark("repeated lock/unlock")
    assert not assess_maintenance(snapshot(session={"locked": True, "lock_dwell_seconds": 3600,
                                                    "idle_seconds": 3600, "recent_input_seconds": 1})).eligible
    mark("long lock but user activity continues")
    assert not assess_maintenance(snapshot(session={"locked": False, "lock_dwell_seconds": 0,
                                                    "idle_seconds": 3600, "recent_input_seconds": 3600})).eligible
    mark("idle but unlocked")
    good = snapshot()
    assert assess_maintenance(good).eligible and maintenance_proposals(good, created_at=T0)
    mark("lock + AC + cool + idle")
    assert not recheck_before_mutation(snapshot(session={"locked": False, "lock_dwell_seconds": 0,
                                                            "idle_seconds": 0, "recent_input_seconds": 0})).eligible
    mark("eligibility disappears immediately before mutation")

    critical = snapshot(maintenance={"in_critical_section": True, "interruption_safe": False})
    assessed = assess_maintenance(critical)
    assert not assessed.eligible and assessed.must_finish_bounded_critical_section
    mark("unlock during hypothetical critical section")

def network_cases() -> None:
    offline = snapshot(network={"connectivity": "offline", "default_route": False,
                                "reachable": False, "stability": "unstable", "stability_seconds": 0})
    ps = network_proposals(offline, created_at=T0)
    assert ("update_downloads", "deferred") in effects(ps)
    book = reconcile_leases(LeaseBook(), resolve_posture(offline, ps), list(ps),
                            condition_state={p.proposal_id: True for p in ps}, now=T0)
    book = reconcile_leases(book, resolve_posture(offline, ps), list(ps),
                            condition_state={p.proposal_id: True for p in ps}, now=T0 + timedelta(seconds=5))
    assert not active_posture(book)
    mark("network disappears briefly")

    expired = reconcile_leases(book, resolve_posture(snapshot(), ()), list(ps),
                               condition_state={p.proposal_id: False for p in ps}, now=T0 + timedelta(seconds=6))
    reentry = reconcile_leases(expired, resolve_posture(offline, ps), list(ps),
                               condition_state={p.proposal_id: True for p in ps}, now=T0 + timedelta(seconds=10))
    assert len(reentry.leases) == len(expired.leases)
    mark("network flaps")
    assert not assess_maintenance(snapshot(network={"stability_seconds": 5})).eligible
    assert assess_maintenance(snapshot(network={"stability_seconds": 120})).eligible
    mark("network stable again")
    unstable = snapshot(network={"connectivity": "limited", "stability": "unstable", "stability_seconds": 2},
                        maintenance={"transaction_state": "STAGED", "prepared": False, "staged": True})
    assert ("update_downloads", "deferred") in effects(network_proposals(unstable, created_at=T0))
    mark("update staging pending during instability")

def guardian_m4_cases() -> None:
    candidate = snapshot()
    maintenance = maintenance_proposals(candidate, created_at=T0)
    incident = snapshot(guardian={"active_incident": True, "severity_level": 2})
    guard = guardian_proposals(incident, created_at=T0)
    combined = resolve_posture(incident, [*maintenance_proposals(incident, created_at=T0), *guard])
    assert dict(combined.effective_posture).get("maintenance") == "suspended"
    mark("Guardian incident begins while maintenance candidate")
    recovery = snapshot(guardian={"active_incident": True, "severity_level": 3, "recovery_in_progress": True})
    posture = resolve_posture(recovery, guardian_proposals(recovery, created_at=T0))
    assert dict(posture.effective_posture)["maintenance"] == "suspended"
    assert dict(posture.effective_posture)["background_work"] == "reduced"
    mark("Guardian recovery begins during adaptation")
    gaming_recovery = snapshot(
        workload={"probable_gaming": True, "interactive": True, "confidence": .99},
        guardian={"active_incident": True, "severity_level": 3, "recovery_in_progress": True},
    )
    combined_guardian = resolve_posture(
        gaming_recovery,
        [*workload_proposals(gaming_recovery, created_at=T0), *guardian_proposals(gaming_recovery, created_at=T0)],
    )
    maintenance_field = next(field for field in combined_guardian.fields if field.effect == "maintenance")
    guardian_ids = {proposal.proposal_id for proposal in guardian_proposals(gaming_recovery, created_at=T0)}
    assert guardian_ids.intersection(maintenance_field.winning_proposal_ids)
    mark("Guardian recovery outranks convenience optimization")
    critical = snapshot(maintenance={"in_critical_section": True, "interruption_safe": False})
    assert assess_maintenance(critical).must_finish_bounded_critical_section
    mark("M4 critical section represented")
    pending = snapshot(maintenance={"transaction_state": "INSTALLED_PENDING_ACTIVATION", "prepared": True})
    assert not assess_maintenance(pending).eligible
    mark("update pending activation")

def resolver_cases() -> None:
    s = snapshot()
    a = proposal(s, "thermal.alpha", "thermal-protection", "background_work", "reduced")
    b = proposal(s, "thermal.bravo", "thermal-protection", "background_work", "reduced")
    compatible = resolve_posture(s, [b, a])
    field = next(f for f in compatible.fields if f.effect == "background_work")
    assert field.winning_proposal_ids == tuple(sorted((a.proposal_id, b.proposal_id)))
    mark("two policies request compatible effect")
    x = proposal(s, "thermal.alpha", "thermal-protection", "background_work", "reduced")
    y = proposal(s, "thermal.bravo", "thermal-protection", "background_work", "suspended")
    conflict = resolve_posture(s, [x, y])
    assert next(f for f in conflict.fields if f.effect == "background_work").status == "ambiguous"
    mark("two policies conflict")

    user = proposal(s, "intent.performance", "explicit-user-intent", "foreground_performance", "preserve")
    opt = proposal(s, "background.optimize", "background-efficiency", "foreground_performance", "balanced")
    assert dict(resolve_posture(s, [opt, user]).effective_posture)["foreground_performance"] == "preserve"
    mark("explicit user intent conflicts with optimization")
    safety = proposal(s, "hardware.danger", "hardware-data-safety", "power_survival", "critical-review")
    user_power = proposal(s, "intent.power", "explicit-user-intent", "power_survival", "normal")
    assert dict(resolve_posture(s, [user_power, safety]).effective_posture)["power_survival"] == "critical-review"
    mark("safety conflicts with user intent")

    stale = snapshot(power={"percentage": 10, "ac_online": False}, power_observed=STALE)
    stale_p = proposal(stale, "battery.low", "battery-survival", "background_work", "reduced")
    fresh_t = proposal(stale, "thermal.hot", "thermal-protection", "background_work", "suspended")
    r = resolve_posture(stale, [stale_p, fresh_t])
    assert dict(r.effective_posture)["background_work"] == "suspended"
    assert (stale_p.proposal_id, "evidence-stale") in r.rejected
    mark("stale evidence conflicts with fresh evidence")

    ambiguous = resolve_posture(s, [
        proposal(s, "network.alpha", "background-efficiency", "network_background", "normal"),
        proposal(s, "network.bravo", "background-efficiency", "network_background", "suspended"),
    ])
    assert next(f for f in ambiguous.fields if f.effect == "network_background").status == "ambiguous"
    mark("equal-priority ambiguous conflict")

    assert resolve_posture(s, [a, a]) == resolve_posture(s, [a])
    mark("duplicate event")
    assert resolve_posture(s, [a, b]) == resolve_posture(s, [b, a])
    mark("reordered events")

def persistence_schema_cases() -> None:
    s = snapshot()
    p = proposal(s, "thermal.hot", "thermal-protection", "background_work", "reduced")
    resolved = resolve_posture(s, [p])
    book = reconcile_leases(LeaseBook(), resolved, [p], condition_state={p.proposal_id: True}, now=T0)
    jumped = reconcile_leases(book, resolved, [p], condition_state={p.proposal_id: True}, now=T0 - timedelta(hours=2))
    assert jumped.leases[0].state == book.leases[0].state == "ACTIVE_SHADOW"
    mark("clock/time jump")
    restored = book_from_dict(book.as_dict())
    assert restored == book
    mark("observer restart")

    corrupt = book.as_dict()
    corrupt["leases"][0]["state"] = "ACTIVE_EXECUTABLE"
    raises(lambda: book_from_dict(corrupt), "shadow lease cannot enter executable state")
    mark("reboot/suspend-style stale leases")
    corrupt2 = book.as_dict()
    corrupt2["leases"][0]["lease_id"] = "broken"
    raises(lambda: book_from_dict(corrupt2), "invalid lease identity")
    mark("corrupted persisted lease")

    raw = p.as_dict()
    bad_field = dict(raw); bad_field["command"] = "shutdown now"
    raises(lambda: proposal_from_dict(bad_field), "unknown proposal fields")
    mark("unknown proposal field")
    bad_effect = dict(raw); bad_effect["requested_effects"] = [{"key": "shell_command", "value": "anything"}]
    raises(lambda: proposal_from_dict(bad_effect), "unknown adaptation effect")
    mark("unknown effect")
    bad_schema = dict(raw); bad_schema["schema_version"] = 999
    raises(lambda: proposal_from_dict(bad_schema), "unsupported adaptation proposal schema")
    mark("unsupported schema version")

    assert all(not q.automatic_execution_eligible for q in [p])
    assert all(lease.mode == "shadow" and "EXECUTABLE" not in lease.state for lease in book.leases)

def main() -> None:
    battery_cases(); thermal_cases(); workload_cases(); maintenance_cases(); network_cases(); guardian_m4_cases(); resolver_cases(); persistence_schema_cases()
    before = snapshot()
    after = snapshot(session={"locked": False, "lock_dwell_seconds": 0, "idle_seconds": 0, "recent_input_seconds": 0})
    assert assess_maintenance(before).eligible and not recheck_before_mutation(after).eligible
    mark("unlock before mutation")

    required = {
        "battery crosses threshold briefly", "battery oscillates around threshold", "charger flaps", "charger reconnects",
        "low battery + gaming", "low battery + explicit Performance", "low battery + idle", "stale battery observation",
        "short thermal spike", "sustained heat", "thermal oscillation", "missing thermal sensor", "absurd sensor value", "thermal recovery",
        "Steam open but no game", "actual fullscreen game evidence", "fullscreen video", "compile process exists briefly", "sustained compile",
        "locked while compiling", "render job while locked", "lock for 1 second", "repeated lock/unlock", "long lock but user activity continues",
        "idle but unlocked", "lock + AC + cool + idle", "eligibility disappears immediately before mutation", "unlock before mutation",
        "unlock during hypothetical critical section", "network disappears briefly", "network flaps", "network stable again",
        "update staging pending during instability", "Guardian incident begins while maintenance candidate", "Guardian recovery begins during adaptation",
        "M4 critical section represented", "update pending activation", "Guardian recovery outranks convenience optimization", "two policies request compatible effect", "two policies conflict",
        "explicit user intent conflicts with optimization", "safety conflicts with user intent", "stale evidence conflicts with fresh evidence",
        "equal-priority ambiguous conflict", "reboot/suspend-style stale leases", "clock/time jump", "observer restart", "duplicate event",
        "reordered events", "corrupted persisted lease", "unknown proposal field", "unknown effect", "unsupported schema version",
    }
    assert SEEN == required, (sorted(required - SEEN), sorted(SEEN - required))
    print(f"ALL ADAPTIVE ADVERSARIAL TESTS PASS ({len(SEEN)} required situations)")

if __name__ == "__main__":
    main()
