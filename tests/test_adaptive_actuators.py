from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

from maho_adaptive_actuators import (
    CERTIFIED_EFFECTS, executable_policy_effects, executable_proposal_effects,
    executable_proposal_ids, execute_certified_actuators, maintenance_decision,
)
from maho_adaptive_leases import LeaseBook, reconcile_leases, verify_executable
from maho_adaptive_proposal import Effect, ExpiryCondition, create_proposal
from maho_adaptive_resolver import FieldResolution, ResolvedPosture
import maho_adaptive_shadow as shadow
from test_adaptive_shadow import fixture

T0 = datetime(2026, 9, 12, 2, 0, tzinfo=timezone.utc)
SID = "sit-" + "1" * 20


def proposal(*, source="gaming.foreground", disruption="A", reversible=True,
             override="respect", failure="preserve-current", dwell=0,
             effects=(Effect("notifications", "quiet"),), priority="foreground-task-continuity"):
    return create_proposal(
        source_policy=source, policy_version="1", situation_snapshot_id=SID,
        priority_domain=priority, disruption_class=disruption,
        confidence=.99, reason="certification fixture", supporting_evidence=["fixture"],
        requested_effects=list(effects), minimum_dwell_seconds=dwell,
        expiry_condition=ExpiryCondition("condition-clears", source), cooldown_seconds=10,
        minimum_residency_seconds=0, reversibility=reversible,
        user_override_behavior=override, notification_policy="none",
        verification_requirement="required", failure_behavior=failure, created_at=T0,
    )


def posture(p):
    field = FieldResolution("notifications", "quiet", "resolved", (p.proposal_id,),
                            (p.proposal_id,), "fixture")
    return ResolvedPosture(1, SID, (("notifications", "quiet"),), (field,), (), ())


def test_eligibility() -> None:
    good = proposal()
    assert good.proposal_id in executable_proposal_ids([good])
    assert not executable_proposal_ids([proposal(source="notification.dnd")])
    assert not executable_proposal_ids([proposal(disruption="C")])
    assert not executable_proposal_ids([proposal(reversible=False)])
    assert not executable_proposal_ids([proposal(override="safety-may-override")])
    assert not executable_proposal_ids([proposal(failure="human-review")])
    maintenance = proposal(effects=(Effect("maintenance", "suspended"),))
    assert (maintenance.proposal_id, "maintenance") in executable_proposal_effects([maintenance])
    eligible = proposal(effects=(Effect("maintenance", "eligible"),))
    assert (eligible.proposal_id, "maintenance") not in executable_proposal_effects([eligible])
    guardian = proposal(
        source="guardian.reliability-state", override="safety-may-override",
        priority="reliability-recovery", effects=(Effect("maintenance", "suspended"),),
    )
    assert (guardian.proposal_id, "maintenance") in executable_proposal_effects([guardian])
    mixed = proposal(effects=(Effect("maintenance", "suspended"), Effect("background_work", "reduced")))
    assert executable_proposal_effects([mixed]) == frozenset({(mixed.proposal_id, "maintenance")})


def test_executable_lease_and_bridge() -> None:
    p = proposal()
    ids = executable_proposal_ids([p])
    book = reconcile_leases(
        LeaseBook(), posture(p), [p], condition_state={p.proposal_id: True}, now=T0,
        executable_effects=CERTIFIED_EFFECTS, executable_proposal_ids=ids,
    )
    assert book.leases[0].mode == "executable"
    assert book.leases[0].state == "ACTIVE_EXECUTABLE"
    seen = {}

    def runner(command, environment):
        decision = json.loads(command[-1])
        seen[decision["resource"]] = decision
        assert environment["MAHO_ROOT"] == str(ROOT)
        payload = {
            "version": 1, "status": "verified",
            "resource": decision["resource"],
            "cycle_id": "cyc-adaptive-fixture", "before": {"enabled": False},
        }
        return 0, json.dumps(payload), ""
    result = execute_certified_actuators(
        ROOT, book, runner=runner, now=T0,
        eligible_policy_effects=executable_policy_effects([p]),
    )
    assert result.ok and result.mutation_executed
    assert result.verified_lease_ids == (book.leases[0].lease_id,)
    assert seen["notifications.presentation.adaptive-quiet"]["desired"] == {
        "operation": "set-adaptive-notify-quiet", "enabled": True,
    }
    assert seen["updates.maintenance.adaptive-veto"]["desired"] == {
        "operation": "set-adaptive-maintenance-veto", "active": False,
    }
    verified = verify_executable(book, book.leases[0].lease_id)
    assert verified.leases[0].state == "VERIFIED_EXECUTABLE"


def test_verified_veto_reuse_and_bounded_refresh() -> None:
    p = proposal(effects=(Effect("maintenance", "suspended"),))
    book = reconcile_leases(
        LeaseBook(),
        ResolvedPosture(
            1, SID, (("maintenance", "suspended"),),
            (FieldResolution("maintenance", "suspended", "resolved", (p.proposal_id,), (p.proposal_id,), "fixture"),),
            (), (),
        ),
        [p], condition_state={p.proposal_id: True}, now=T0,
        executable_effects=CERTIFIED_EFFECTS,
        executable_proposal_effects=executable_proposal_effects([p]),
    )
    existing = maintenance_decision(book, now=T0)["desired"]["state"]
    reused = maintenance_decision(book, now=T0 + timedelta(seconds=60), existing_state=existing)
    assert reused["desired"]["state"] == existing
    refreshed = maintenance_decision(book, now=T0 + timedelta(seconds=100), existing_state=existing)
    assert refreshed["desired"]["state"]["updated_at"] != existing["updated_at"]
    assert refreshed["desired"]["state"]["lease_id"] == existing["lease_id"]


def game(now):
    data = fixture(now, battery=80, ac=True, thermal=70000, locked=False)
    data["workload"]["data"].update({
        "fullscreen": True, "probable_gaming": True, "interactive": True,
        "gpu_activity": True, "confidence": .99, "evidence": ["game-window"],
    })
    return data


def compile_work(now):
    data = fixture(now, battery=80, ac=True, thermal=70000, locked=False)
    data["workload"]["data"].update({"probable_compile": True, "confidence": .99, "evidence": ["compiler-tree"]})
    return data


def hot(now):
    return fixture(now, battery=80, ac=True, thermal=86000, locked=False)


def guardian_recovery(now):
    data = fixture(now, battery=80, ac=True, thermal=70000, locked=False)
    data["guardian"]["data"].update({
        "active_incident": True, "severity_level": 3,
        "recovery_in_progress": True, "unresolved_reliability": True,
    })
    return data


def stateful_runner(state):
    def runner(command, environment):
        decision = json.loads(command[-1])
        payload = {
            "version": 1, "status": "verified", "resource": decision["resource"],
            "cycle_id": "cyc-adaptive-live-fixture",
        }
        if decision["resource"] == "notifications.presentation.adaptive-quiet":
            enabled = bool(decision["desired"]["enabled"])
            if state["quiet"] != enabled:
                payload["before"] = {"enabled": state["quiet"]}
                state["quiet"] = enabled
        else:
            desired = decision["desired"]
            target = desired.get("state") if desired["active"] else None
            if state["veto"] != target:
                payload["before"] = {"state": state["veto"]}
                state["veto"] = target
        return 0, json.dumps(payload), ""
    return runner


def test_evaluator_actuate_and_revert() -> None:
    old_policy = shadow.adaptive_execution_policy
    shadow.adaptive_execution_policy = lambda root: {
        "certified": True,
        "effects": ("maintenance", "notifications"),
        "service_enabled": False,
        "reason": None,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="maho-a15-") as temporary:
            state = {"quiet": False, "veto": None}
            root = Path(temporary)
            first = shadow.evaluate_shadow(
                root, now=T0, observations=game(T0), execute_certified=True,
                actuator_runner=stateful_runner(state),
            )
            assert first["actions"]["mode"] == "A16_CERTIFIED"
            later = T0 + timedelta(seconds=15)
            second = shadow.evaluate_shadow(
                root, now=later, observations=game(later), execute_certified=True,
                actuator_runner=stateful_runner(state),
            )
            assert second["actions"]["verified"] is True
            assert second["active_executable_posture"] == {"maintenance": "suspended", "notifications": "quiet"}
            assert state["quiet"] is True
            assert state["veto"]["source_policy"] == "gaming.foreground"
            assert second["active_shadow_posture"] == {
                "background_work": "reduced", "foreground_performance": "preserve",
            }

            cleared = T0 + timedelta(seconds=150)
            third = shadow.evaluate_shadow(
                root, now=cleared,
                observations=fixture(cleared, battery=80, ac=True),
                execute_certified=True, actuator_runner=stateful_runner(state),
            )
            assert third["active_executable_posture"] == {}
            assert state["quiet"] is False
            assert state["veto"] is None
            assert third["actions"]["verified"] is True
    finally:
        shadow.adaptive_execution_policy = old_policy


def test_same_veto_across_policy_families() -> None:
    old_policy = shadow.adaptive_execution_policy
    shadow.adaptive_execution_policy = lambda root: {
        "certified": True, "effects": ("maintenance", "notifications"),
        "service_enabled": True, "reason": None,
    }
    scenarios = (
        ("compile.sustained", compile_work, 16),
        ("battery.low", lambda now: fixture(now, battery=30, ac=False, thermal=70000), 46),
        ("thermal.hot-sustained", hot, 61),
        ("guardian.reliability-state", guardian_recovery, 0),
    )
    try:
        for source, observation, delay in scenarios:
            with tempfile.TemporaryDirectory(prefix="maho-a16-scenario-") as temporary:
                runtime = Path(temporary)
                state = {"quiet": False, "veto": None}
                shadow.evaluate_shadow(
                    runtime, now=T0, observations=observation(T0), execute_certified=True,
                    actuator_runner=stateful_runner(state),
                )
                current = T0 + timedelta(seconds=delay)
                result = shadow.evaluate_shadow(
                    runtime, now=current, observations=observation(current), execute_certified=True,
                    actuator_runner=stateful_runner(state),
                )
                assert result["active_executable_posture"].get("maintenance") == "suspended", (source, result)
                assert state["veto"]["source_policy"] == source
                assert state["quiet"] is False
                assert result["active_shadow_posture"] or source in {"compile.sustained", "guardian.reliability-state"}
    finally:
        shadow.adaptive_execution_policy = old_policy


def test_eligible_and_unsupported_effects_remain_shadow_only() -> None:
    old_policy = shadow.adaptive_execution_policy
    shadow.adaptive_execution_policy = lambda root: {
        "certified": True, "effects": ("maintenance", "notifications"),
        "service_enabled": True, "reason": None,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="maho-a16-eligible-") as temporary:
            runtime = Path(temporary)
            state = {"quiet": False, "veto": None}
            observations = fixture(T0, battery=80, ac=True, thermal=70000, locked=True)
            observations["session"]["data"].update({
                "lock_dwell_seconds": 1800, "idle_seconds": 1800,
                "recent_input_seconds": 1800,
            })
            observations["maintenance"]["data"].update({
                "transaction_state": "PREPARED", "pending": True, "staged": True,
                "prepared": True, "recovery_prerequisites": True, "enough_disk": True,
            })
            shadow.evaluate_shadow(runtime, now=T0, observations=observations, execute_certified=True, actuator_runner=stateful_runner(state))
            later = T0 + timedelta(seconds=31)
            for envelope in observations.values():
                envelope["observed_at"] = later.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            result = shadow.evaluate_shadow(runtime, now=later, observations=observations, execute_certified=True, actuator_runner=stateful_runner(state))
            assert result["active_shadow_posture"]["maintenance"] == "eligible"
            assert result["active_executable_posture"] == {}
            assert state["veto"] is None
    finally:
        shadow.adaptive_execution_policy = old_policy


def test_failure_and_anti_flap_behavior() -> None:
    old_policy = shadow.adaptive_execution_policy
    shadow.adaptive_execution_policy = lambda root: {
        "certified": True, "effects": ("maintenance", "notifications"),
        "service_enabled": True, "reason": None,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="maho-a16-failure-") as temporary:
            runtime = Path(temporary)
            state = {"quiet": False, "veto": None}
            shadow.evaluate_shadow(runtime, now=T0, observations=game(T0), execute_certified=True, actuator_runner=stateful_runner(state))

            def fail_maintenance(command, environment):
                decision = json.loads(command[-1])
                if decision["resource"] == "updates.maintenance.adaptive-veto":
                    return 1, "", "injected maintenance adapter failure"
                return stateful_runner(state)(command, environment)

            active_time = T0 + timedelta(seconds=15)
            failed = shadow.evaluate_shadow(runtime, now=active_time, observations=game(active_time), execute_certified=True, actuator_runner=fail_maintenance)
            assert failed["actions"]["verified"] is False
            assert "updates.maintenance.adaptive-veto" in failed["blocked"]
            states = {lease["effect"]["key"]: lease["state"] for lease in failed["leases"] if lease["mode"] == "executable"}
            assert states["notifications"] == "VERIFIED_EXECUTABLE"
            assert states["maintenance"] == "ACTIVE_EXECUTABLE"
            assert state["veto"] is None

        with tempfile.TemporaryDirectory(prefix="maho-a16-restore-failure-") as temporary:
            runtime = Path(temporary)
            state = {"quiet": False, "veto": None}
            shadow.evaluate_shadow(runtime, now=T0, observations=game(T0), execute_certified=True, actuator_runner=stateful_runner(state))
            active_time = T0 + timedelta(seconds=15)
            shadow.evaluate_shadow(runtime, now=active_time, observations=game(active_time), execute_certified=True, actuator_runner=stateful_runner(state))
            assert state["veto"] is not None

            def fail_restoration(command, environment):
                decision = json.loads(command[-1])
                if decision["resource"] == "updates.maintenance.adaptive-veto" and decision["desired"]["active"] is False:
                    return 1, "", "injected restoration failure"
                return stateful_runner(state)(command, environment)

            cleared = T0 + timedelta(seconds=150)
            restored = shadow.evaluate_shadow(runtime, now=cleared, observations=fixture(cleared, battery=80, ac=True), execute_certified=True, actuator_runner=fail_restoration)
            assert restored["active_executable_posture"] == {}
            assert state["veto"] is not None
            assert "injected restoration failure" in restored["blocked"]

        with tempfile.TemporaryDirectory(prefix="maho-a16-flap-") as temporary:
            runtime = Path(temporary)
            state = {"quiet": False, "veto": None}
            shadow.evaluate_shadow(runtime, now=T0, observations=game(T0), execute_certified=True, actuator_runner=stateful_runner(state))
            cleared = T0 + timedelta(seconds=5)
            result = shadow.evaluate_shadow(runtime, now=cleared, observations=fixture(cleared, battery=80, ac=True), execute_certified=True, actuator_runner=stateful_runner(state))
            assert result["active_executable_posture"] == {}
            assert state == {"quiet": False, "veto": None}
    finally:
        shadow.adaptive_execution_policy = old_policy


def test_uncertified_gate() -> None:
    old_policy = shadow.adaptive_execution_policy
    shadow.adaptive_execution_policy = lambda root: {
        "certified": False,
        "effects": ("maintenance", "notifications"),
        "service_enabled": False,
        "reason": "adaptive-execution-uncertified",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="maho-a15-blocked-") as temporary:
            result = shadow.evaluate_shadow(
                Path(temporary), now=T0, observations=game(T0), execute_certified=True,
            )
            assert result["actions"]["mode"] == "A16_BLOCKED"
            assert result["actions"]["mutation_executed"] is False
            assert result["active_executable_posture"] == {}
            assert result["blocked"] == "adaptive-execution-uncertified"
    finally:
        shadow.adaptive_execution_policy = old_policy


def main() -> None:
    test_eligibility()
    test_executable_lease_and_bridge()
    test_verified_veto_reuse_and_bounded_refresh()
    test_evaluator_actuate_and_revert()
    test_same_veto_across_policy_families()
    test_eligible_and_unsupported_effects_remain_shadow_only()
    test_failure_and_anti_flap_behavior()
    test_uncertified_gate()
    print("ALL A16 ADAPTIVE ACTUATOR CONTRACTS PASS")


if __name__ == "__main__":
    main()
