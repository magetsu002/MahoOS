#!/usr/bin/env python3
"""Certified A15 actuator bridge.

Policy remains declarative. This module may only project explicitly certified,
reversible leases into Maho's existing generic adaptation executor.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Callable, Mapping, Sequence

from maho_adaptive_leases import LeaseBook, validate_book
from maho_adaptive_proposal import AdaptationProposal

CERTIFIED_EFFECTS = frozenset({"notifications"})
CERTIFIED_SOURCE_POLICIES = frozenset({
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
_RESOURCE = "notifications.presentation.adaptive-quiet"
_OPERATION = "set-adaptive-notify-quiet"
_POLICY = "adaptive.a15.notifications"
_ACTIVE_EXECUTABLE = {"ACTIVE_EXECUTABLE", "VERIFIED_EXECUTABLE"}


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


def executable_proposal_ids(proposals: Sequence[AdaptationProposal]) -> frozenset[str]:
    eligible: set[str] = set()
    for proposal in proposals:
        if proposal.source_policy not in CERTIFIED_SOURCE_POLICIES:
            continue
        requested = {effect.key: effect.value for effect in proposal.requested_effects}
        has_certified = any(key in CERTIFIED_EFFECTS for key in requested)
        if not has_certified:
            continue
        if proposal.disruption_class not in {"A", "B"}:
            continue
        if proposal.requires_human_review or not proposal.reversibility:
            continue
        if proposal.failure_behavior != "preserve-current":
            continue
        if proposal.user_override_behavior != "respect":
            continue
        if any(key == "notifications" and value not in _NOTIFICATION_VALUES for key, value in requested.items()):
            continue
        eligible.add(proposal.proposal_id)
    return frozenset(eligible)


def _notification_target(book: LeaseBook) -> tuple[bool, tuple[str, ...]]:
    validate_book(book)
    executable = [lease for lease in book.leases if lease.state in _ACTIVE_EXECUTABLE]
    unsupported = sorted({lease.effect.key for lease in executable if lease.effect.key not in CERTIFIED_EFFECTS})
    if unsupported:
        raise ValueError(f"uncertified executable adaptive effect: {', '.join(unsupported)}")
    leases = [lease for lease in executable if lease.effect.key == "notifications"]
    if len(leases) > 1:
        raise ValueError("multiple active executable notification leases")
    if not leases:
        return False, ()
    lease = leases[0]
    enabled = _NOTIFICATION_VALUES.get(lease.effective_state)
    if enabled is None:
        raise ValueError("unsupported executable notification value")
    return enabled, (lease.lease_id,)


def notification_decision(book: LeaseBook) -> dict[str, Any]:
    enabled, lease_ids = _notification_target(book)
    return {
        "version": 1,
        "domain": "adaptive",
        "policy": _POLICY,
        "action": "adapt",
        "resource": _RESOURCE,
        "reason": "certified A15 notification presentation lease",
        "evidence": {"lease_ids": list(lease_ids), "certified_effect": "notifications"},
        "desired": {"operation": _OPERATION, "enabled": enabled},
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
) -> ActuationResult:
    root = root.resolve()
    decision = notification_decision(book)
    lease_ids = tuple(decision["evidence"]["lease_ids"])
    adapt = root / "bin/maho-adapt"
    if not adapt.is_file():
        return ActuationResult(False, False, _RESOURCE, decision["desired"], lease_ids, None, "maho-adapt unavailable")
    command = ("bash", str(adapt), "execute", json.dumps(decision, sort_keys=True, separators=(",", ":")))
    environment = dict(os.environ)
    environment["MAHO_ROOT"] = str(root)
    rc, stdout, stderr = (runner or _run)(command, environment)
    if rc != 0:
        detail = (stderr.strip() or stdout.strip() or f"executor exited {rc}")[:500]
        return ActuationResult(False, False, _RESOURCE, decision["desired"], lease_ids, None, detail)
    try:
        payload = json.loads(stdout)
    except Exception:
        return ActuationResult(False, False, _RESOURCE, decision["desired"], lease_ids, None, "executor returned invalid JSON")
    if not isinstance(payload, Mapping) or payload.get("status") != "verified" or payload.get("resource") != _RESOURCE:
        return ActuationResult(False, False, _RESOURCE, decision["desired"], lease_ids, None, "executor did not verify certified resource")
    cycle = payload.get("cycle_id") if isinstance(payload.get("cycle_id"), str) else None
    mutation = isinstance(payload.get("before"), Mapping)
    return ActuationResult(True, mutation, _RESOURCE, decision["desired"], lease_ids, cycle)
