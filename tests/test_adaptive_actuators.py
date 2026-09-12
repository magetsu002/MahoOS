from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

from maho_adaptive_actuators import CERTIFIED_EFFECTS, executable_proposal_ids, execute_certified_actuators
from maho_adaptive_leases import LeaseBook, reconcile_leases, verify_executable
from maho_adaptive_proposal import Effect, ExpiryCondition, create_proposal
from maho_adaptive_resolver import FieldResolution, ResolvedPosture
import maho_adaptive_shadow as shadow
from test_adaptive_shadow import fixture

T0 = datetime(2026, 9, 12, 2, 0, tzinfo=timezone.utc)
SID = "sit-" + "1" * 20


def proposal(*, source="gaming.foreground", disruption="A", reversible=True,
             override="respect", failure="preserve-current", dwell=0):
    return create_proposal(
        source_policy=source, policy_version="1", situation_snapshot_id=SID,
        priority_domain="foreground-task-continuity", disruption_class=disruption,
        confidence=.99, reason="certification fixture", supporting_evidence=["fixture"],
        requested_effects=[Effect("notifications", "quiet")], minimum_dwell_seconds=dwell,
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
        seen["decision"] = json.loads(command[-1])
        assert environment["MAHO_ROOT"] == str(ROOT)
        payload = {
            "version": 1, "status": "verified",
            "resource": "notifications.presentation.adaptive-quiet",
            "cycle_id": "cyc-adaptive-fixture", "before": {"enabled": False},
        }
        return 0, json.dumps(payload), ""
    result = execute_certified_actuators(ROOT, book, runner=runner)
    assert result.ok and result.mutation_executed
    assert result.verified_lease_ids == (book.leases[0].lease_id,)
    assert seen["decision"]["desired"] == {
        "operation": "set-adaptive-notify-quiet", "enabled": True,
    }
    verified = verify_executable(book, book.leases[0].lease_id)
    assert verified.leases[0].state == "VERIFIED_EXECUTABLE"


def game(now):
    data = fixture(now, battery=80, ac=True, thermal=70000, locked=False)
    data["workload"]["data"].update({
        "fullscreen": True, "probable_gaming": True, "interactive": True,
        "gpu_activity": True, "confidence": .99, "evidence": ["game-window"],
    })
    return data


def stateful_runner(state):
    def runner(command, environment):
        decision = json.loads(command[-1])
        enabled = bool(decision["desired"]["enabled"])
        payload = {
            "version": 1, "status": "verified", "resource": decision["resource"],
            "cycle_id": "cyc-adaptive-live-fixture",
        }
        if state["quiet"] != enabled:
            payload["before"] = {"enabled": state["quiet"]}
            state["quiet"] = enabled
        return 0, json.dumps(payload), ""
    return runner


def test_evaluator_actuate_and_revert() -> None:
    old_policy = shadow.adaptive_execution_policy
    shadow.adaptive_execution_policy = lambda root: {
        "certified": True,
        "effects": ("notifications",),
        "service_enabled": False,
        "reason": None,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="maho-a15-") as temporary:
            state = {"quiet": False}
            root = Path(temporary)
            first = shadow.evaluate_shadow(
                root, now=T0, observations=game(T0), execute_certified=True,
                actuator_runner=stateful_runner(state),
            )
            assert first["actions"]["mode"] == "A15_CERTIFIED"
            later = T0 + timedelta(seconds=15)
            second = shadow.evaluate_shadow(
                root, now=later, observations=game(later), execute_certified=True,
                actuator_runner=stateful_runner(state),
            )
            assert second["actions"]["verified"] is True
            assert second["active_executable_posture"] == {"notifications": "quiet"}
            assert state["quiet"] is True

            cleared = T0 + timedelta(seconds=150)
            third = shadow.evaluate_shadow(
                root, now=cleared,
                observations=fixture(cleared, battery=80, ac=True),
                execute_certified=True, actuator_runner=stateful_runner(state),
            )
            assert third["active_executable_posture"] == {}
            assert state["quiet"] is False
            assert third["actions"]["verified"] is True
    finally:
        shadow.adaptive_execution_policy = old_policy


def test_uncertified_gate() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-a15-blocked-") as temporary:
        result = shadow.evaluate_shadow(
            Path(temporary), now=T0, observations=game(T0), execute_certified=True,
        )
        assert result["actions"]["mode"] == "A15_BLOCKED"
        assert result["actions"]["mutation_executed"] is False
        assert result["active_executable_posture"] == {}
        assert result["blocked"] == "a15-execution-uncertified"


def main() -> None:
    test_eligibility()
    test_executable_lease_and_bridge()
    test_evaluator_actuate_and_revert()
    test_uncertified_gate()
    print("ALL A15 ADAPTIVE ACTUATOR CONTRACTS PASS")


if __name__ == "__main__":
    main()
