#!/usr/bin/env python3
"""Bounded Guardian recovery executor for explicitly certified V1 paths.

This module is intentionally not wired into automatic incident reconciliation.
It provides the execution boundary and post-action verification contract that a
future normalized service-incident source may invoke after Guardian and the
recovery planner have independently granted automatic mutation authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import subprocess
from typing import Any, Callable, Mapping, Sequence

from guardian_recovery_registry import certified_service_recovery


@dataclass(frozen=True)
class RecoveryExecution:
    action: str
    target: str | None
    attempted: bool
    verified: bool
    status: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _run(runner: Runner, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return runner(tuple(argv))


def execute_guardian_recovery(
    decision: Mapping[str, Any],
    *,
    runner: Runner = _default_runner,
) -> RecoveryExecution:
    """Execute only an already-authorized, exactly registered recovery path."""

    recovery = _mapping(decision.get("recovery"))
    action = recovery.get("action") if isinstance(recovery.get("action"), str) else ""
    target = recovery.get("target") if isinstance(recovery.get("target"), str) else None

    if decision.get("execution_mode") != "automatic" or decision.get("mutating_recovery_allowed") is not True:
        return RecoveryExecution(
            action=action or "none",
            target=target,
            attempted=False,
            verified=False,
            status="refused",
            reason="Guardian decision did not grant automatic mutating recovery authority.",
        )

    if action != "restart-service" or target is None:
        return RecoveryExecution(
            action=action or "none",
            target=target,
            attempted=False,
            verified=False,
            status="refused",
            reason="No V1 executor is certified for this recovery action.",
        )

    certified = certified_service_recovery(target)
    if certified is None or certified.action != action:
        return RecoveryExecution(
            action=action,
            target=target,
            attempted=False,
            verified=False,
            status="refused",
            reason="Requested service recovery is not present in the explicit V1 certification registry.",
        )

    load = _run(
        runner,
        ("systemctl", "--user", "show", target, "--property=LoadState", "--value"),
    )
    if load.returncode != 0 or load.stdout.strip() != "loaded":
        return RecoveryExecution(
            action=action,
            target=target,
            attempted=False,
            verified=False,
            status="precondition-failed",
            reason="Certified service is not loaded in the user systemd manager; no restart was attempted.",
        )

    restart = _run(runner, ("systemctl", "--user", "restart", target))
    if restart.returncode != 0:
        return RecoveryExecution(
            action=action,
            target=target,
            attempted=True,
            verified=False,
            status="action-failed",
            reason="Certified service restart failed; recovery success is not recorded.",
        )

    active = _run(runner, ("systemctl", "--user", "is-active", "--quiet", target))
    if active.returncode != 0:
        return RecoveryExecution(
            action=action,
            target=target,
            attempted=True,
            verified=False,
            status="verification-failed",
            reason="Restart completed but the required active-state postcondition was not verified.",
        )

    return RecoveryExecution(
        action=action,
        target=target,
        attempted=True,
        verified=True,
        status="verified",
        reason="Certified service restart completed and the active-state postcondition was verified.",
    )


def recovery_history_record(execution: RecoveryExecution) -> dict[str, Any]:
    """Return a history-safe result; success is impossible without verification."""

    return {
        "version": 1,
        "kind": "guardian-recovery-result",
        "action": execution.action,
        "target": execution.target,
        "status": "succeeded" if execution.verified else "failed",
        "verified": execution.verified,
        "attempted": execution.attempted,
        "reason": execution.reason,
    }
