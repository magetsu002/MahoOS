#!/usr/bin/env python3
"""Explicit registry for certified Adaptive execution bridges.

Policy remains declarative. This module may only project explicitly certified,
reversible leases into Maho's existing generic adaptation executor.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping, Sequence

from maho_adaptive_leases import LeaseBook, validate_book
from maho_adaptive_maintenance_state import (
    ALLOWED_SOURCE_POLICIES as MAINTENANCE_SOURCE_POLICIES,
    MaintenanceVetoError,
    OPERATION as MAINTENANCE_OPERATION,
    default_path as maintenance_state_path,
    read_state as read_maintenance_state,
    state_for_lease,
)
from maho_adaptive_proposal import AdaptationProposal

CERTIFIED_EFFECTS = frozenset({"notifications", "maintenance"})
NOTIFICATION_SOURCE_POLICIES = frozenset({
    "gaming.foreground",
    "media.fullscreen",
    "notification.foreground-context",
})
_NOTIFICATION_VALUES = {
    "quiet": True,
    "defer-noncritical": True,
    "normal": False,
    "unchanged": False,
}
_NOTIFICATION_RESOURCE = "notifications.presentation.adaptive-quiet"
_NOTIFICATION_OPERATION = "set-adaptive-notify-quiet"
_NOTIFICATION_POLICY = "adaptive.a15.notifications"
_MAINTENANCE_RESOURCE = "updates.maintenance.adaptive-veto"
_MAINTENANCE_POLICY = "adaptive.a16.maintenance-veto"
_ACTIVE_EXECUTABLE = {"ACTIVE_EXECUTABLE", "VERIFIED_EXECUTABLE"}
_MAINTENANCE_REFRESH_HEADROOM_SECONDS = 30


@dataclass(frozen=True)
class CertifiedActuator:
    effect: str
    allowed_source_policies: frozenset[str]
    allowed_values: frozenset[str]
    allowed_override_behaviors: frozenset[str]
    resource: str
    operation: str
    policy: str


ACTUATOR_REGISTRY = {
    "notifications": CertifiedActuator(
        "notifications", NOTIFICATION_SOURCE_POLICIES, frozenset(_NOTIFICATION_VALUES),
        frozenset({"respect"}), _NOTIFICATION_RESOURCE, _NOTIFICATION_OPERATION,
        _NOTIFICATION_POLICY,
    ),
    "maintenance": CertifiedActuator(
        "maintenance", MAINTENANCE_SOURCE_POLICIES, frozenset({"suspended"}),
        frozenset({"respect", "safety-may-override"}), _MAINTENANCE_RESOURCE,
        MAINTENANCE_OPERATION, _MAINTENANCE_POLICY,
    ),
}


@dataclass(frozen=True)
class ActuationResult:
    ok: bool
    mutation_executed: bool
    resource: str
    desired: Mapping[str, Any]
    verified_lease_ids: tuple[str, ...]
    cycle_id: str | None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActuationBatch:
    ok: bool
    results: tuple[ActuationResult, ...]
    verified_lease_ids: tuple[str, ...]

    @property
    def mutation_executed(self) -> bool:
        return any(result.mutation_executed for result in self.results)

    @property
    def cycle_ids(self) -> tuple[str, ...]:
        return tuple(result.cycle_id for result in self.results if result.cycle_id is not None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mutation_executed": self.mutation_executed,
            "verified_lease_ids": list(self.verified_lease_ids),
            "results": [result.as_dict() for result in self.results],
        }


def executable_proposal_effects(proposals: Sequence[AdaptationProposal]) -> frozenset[tuple[str, str]]:
    eligible: set[tuple[str, str]] = set()
    for proposal in proposals:
        if proposal.disruption_class not in {"A", "B"}:
            continue
        if proposal.requires_human_review or not proposal.reversibility:
            continue
        if proposal.failure_behavior != "preserve-current":
            continue
        for effect in proposal.requested_effects:
            actuator = ACTUATOR_REGISTRY.get(effect.key)
            if actuator is None:
                continue
            if proposal.source_policy not in actuator.allowed_source_policies:
                continue
            if effect.value not in actuator.allowed_values:
                continue
            if proposal.user_override_behavior not in actuator.allowed_override_behaviors:
                continue
            eligible.add((proposal.proposal_id, effect.key))
    return frozenset(eligible)


def executable_policy_effects(proposals: Sequence[AdaptationProposal]) -> frozenset[tuple[str, str]]:
    pairs = executable_proposal_effects(proposals)
    by_id = {proposal.proposal_id: proposal for proposal in proposals}
    return frozenset((by_id[proposal_id].source_policy, effect) for proposal_id, effect in pairs)


def executable_proposal_ids(proposals: Sequence[AdaptationProposal]) -> frozenset[str]:
    return frozenset(proposal_id for proposal_id, _effect in executable_proposal_effects(proposals))


def _executable_leases(book: LeaseBook) -> dict[str, Any]:
    validate_book(book)
    executable = [lease for lease in book.leases if lease.state in _ACTIVE_EXECUTABLE]
    unsupported = sorted({lease.effect.key for lease in executable if lease.effect.key not in CERTIFIED_EFFECTS})
    if unsupported:
        raise ValueError(f"uncertified executable adaptive effect: {', '.join(unsupported)}")
    result: dict[str, Any] = {}
    for lease in executable:
        if lease.effect.key in result:
            raise ValueError(f"multiple active executable {lease.effect.key} leases")
        result[lease.effect.key] = lease
    return result


def _notification_target(book: LeaseBook) -> tuple[bool, tuple[str, ...]]:
    lease = _executable_leases(book).get("notifications")
    if lease is None:
        return False, ()
    enabled = _NOTIFICATION_VALUES.get(lease.effective_state)
    if enabled is None:
        raise ValueError("unsupported executable notification value")
    return enabled, (lease.lease_id,)


def notification_decision(book: LeaseBook) -> dict[str, Any]:
    enabled, lease_ids = _notification_target(book)
    return {
        "version": 1,
        "domain": "adaptive",
        "policy": _NOTIFICATION_POLICY,
        "action": "adapt",
        "resource": _NOTIFICATION_RESOURCE,
        "reason": "certified A15 notification presentation lease",
        "evidence": {"lease_ids": list(lease_ids), "certified_effect": "notifications"},
        "desired": {"operation": _NOTIFICATION_OPERATION, "enabled": enabled},
    }


def maintenance_decision(
    book: LeaseBook, *, now: datetime, existing_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    lease = _executable_leases(book).get("maintenance")
    if lease is None:
        desired: dict[str, Any] = {"operation": MAINTENANCE_OPERATION, "active": False}
        lease_ids: tuple[str, ...] = ()
    else:
        if lease.effective_state != "suspended":
            raise ValueError("unsupported executable maintenance value")
        state = None
        if existing_state is not None:
            valid_until = datetime.fromisoformat(str(existing_state["valid_until"]).replace("Z", "+00:00"))
            remaining = (valid_until.astimezone(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()
            if (
                existing_state.get("lease_id") == lease.lease_id
                and existing_state.get("source_policy") == lease.source_policy
                and existing_state.get("source_proposal_id") == lease.source_proposal_id
                and remaining > _MAINTENANCE_REFRESH_HEADROOM_SECONDS
            ):
                state = dict(existing_state)
        if state is None:
            state = state_for_lease(
                lease_id=lease.lease_id,
                source_policy=lease.source_policy,
                source_proposal_id=lease.source_proposal_id,
                captured_at=lease.entered_at,
                now=now,
            )
        desired = {"operation": MAINTENANCE_OPERATION, "active": True, "state": state}
        lease_ids = (lease.lease_id,)
    return {
        "version": 1,
        "domain": "adaptive",
        "policy": _MAINTENANCE_POLICY,
        "action": "adapt",
        "resource": _MAINTENANCE_RESOURCE,
        "reason": "certified bounded Adaptive maintenance veto lease",
        "evidence": {"lease_ids": list(lease_ids), "certified_effect": "maintenance"},
        "desired": desired,
    }


Runner = Callable[[Sequence[str], Mapping[str, str]], tuple[int, str, str]]


def _run(command: Sequence[str], environment: Mapping[str, str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        list(command), check=False, text=True, capture_output=True, timeout=10,
        env=dict(environment),
    )
    return completed.returncode, completed.stdout, completed.stderr


def execute_certified_actuators(
    root: Path,
    book: LeaseBook,
    *,
    runner: Runner | None = None,
    now: datetime | None = None,
    eligible_policy_effects: frozenset[tuple[str, str]] | None = None,
    lease_condition_state: Mapping[str, bool | None] | None = None,
) -> ActuationBatch:
    root = root.resolve()
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    active = _executable_leases(book)
    existing_maintenance_state = None
    try:
        existing_maintenance_state = read_maintenance_state(
            maintenance_state_path(), now=current, expected_uid=os.getuid(),
        )
    except MaintenanceVetoError:
        # The generic transaction path must observe and report unsafe existing
        # state. Do not bypass capture/verification by repairing it here.
        pass
    decisions = (
        ("notifications", notification_decision(book)),
        ("maintenance", maintenance_decision(
            book, now=current, existing_state=existing_maintenance_state,
        )),
    )
    adapt = root / "bin/maho-adapt"
    results: list[ActuationResult] = []
    verified: list[str] = []
    for effect, decision in decisions:
        lease_ids = tuple(decision["evidence"]["lease_ids"])
        lease = active.get(effect)
        condition = lease_condition_state.get(lease.lease_id) if lease is not None and lease_condition_state is not None else True
        if (
            lease is not None
            and (
                condition is None
                or (
                    condition is True
                    and eligible_policy_effects is not None
                    and (lease.source_policy, effect) not in eligible_policy_effects
                )
            )
        ):
            results.append(ActuationResult(
                False, False, str(decision["resource"]), decision["desired"], lease_ids,
                None, "current fresh policy evidence is unavailable",
            ))
            continue
        if not adapt.is_file():
            results.append(ActuationResult(False, False, str(decision["resource"]), decision["desired"], lease_ids, None, "maho-adapt unavailable"))
            continue
        command = ("bash", str(adapt), "execute", json.dumps(decision, sort_keys=True, separators=(",", ":")))
        environment = dict(os.environ)
        environment["MAHO_ROOT"] = str(root)
        rc, stdout, stderr = (runner or _run)(command, environment)
        if rc != 0:
            detail = (stderr.strip() or stdout.strip() or f"executor exited {rc}")[:500]
            results.append(ActuationResult(False, False, str(decision["resource"]), decision["desired"], lease_ids, None, detail))
            continue
        try:
            payload = json.loads(stdout)
        except Exception:
            results.append(ActuationResult(False, False, str(decision["resource"]), decision["desired"], lease_ids, None, "executor returned invalid JSON"))
            continue
        if not isinstance(payload, Mapping) or payload.get("status") != "verified" or payload.get("resource") != decision["resource"]:
            results.append(ActuationResult(False, False, str(decision["resource"]), decision["desired"], lease_ids, None, "executor did not verify certified resource"))
            continue
        cycle = payload.get("cycle_id") if isinstance(payload.get("cycle_id"), str) else None
        mutation = isinstance(payload.get("before"), Mapping)
        results.append(ActuationResult(True, mutation, str(decision["resource"]), decision["desired"], lease_ids, cycle))
        verified.extend(lease_ids)
    return ActuationBatch(
        all(result.ok for result in results), tuple(results), tuple(sorted(set(verified))),
    )
