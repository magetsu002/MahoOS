#!/usr/bin/env python3
"""Product maintenance policy shared by Power, Notify, Settings, and Edge."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from maho_update_state import UpdateState, transition_transaction, validate_transaction


@dataclass(frozen=True)
class MaintenanceContext:
    intent: str
    active_user: bool
    fullscreen_or_gaming: bool
    idle_seconds: int
    locked: bool
    power_status_known: bool
    on_ac: bool
    battery_percent: int | None
    system_safe: bool
    concurrent_package_or_build_operation: bool
    unattended_allowed: bool
    serious_security_issue: bool
    update_debt_days: int
    # Optional adaptive-policy projection. "unknown" preserves the exact M4A
    # behavior for callers that have not integrated the adaptive layer yet.
    adaptive_maintenance: str = "unknown"


@dataclass(frozen=True)
class MaintenanceDecision:
    transaction: dict[str, Any]
    may_begin: bool
    authority: str
    passthrough_power_action: str | None
    passive_state: str
    reasons: tuple[str, ...]
    attention_required: bool
    notification_policy: str
    reboot_requested: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_context(context: MaintenanceContext) -> None:
    if context.intent not in {"none", "explicit-update", "shutdown", "restart"}:
        raise ValueError("maintenance intent is invalid")
    if context.idle_seconds < 0 or context.update_debt_days < 0:
        raise ValueError("maintenance durations cannot be negative")
    if context.battery_percent is not None and not 0 <= context.battery_percent <= 100:
        raise ValueError("battery percentage is invalid")
    if context.adaptive_maintenance not in {"unknown", "unchanged", "eligible", "suspended"}:
        raise ValueError("adaptive maintenance posture is invalid")


def evaluate_maintenance(
    transaction: Mapping[str, Any],
    context: MaintenanceContext,
    *,
    idle_threshold_seconds: int = 30 * 60,
    debt_attention_days: int = 30,
    authority_evidence: Mapping[str, Any] | None = None,
    now=None,
) -> MaintenanceDecision:
    current = validate_transaction(transaction)
    if current["state"] != UpdateState.PREPARED.value:
        raise ValueError("maintenance policy requires a PREPARED transaction")
    _validate_context(context)
    if idle_threshold_seconds <= 0 or debt_attention_days <= 0:
        raise ValueError("maintenance thresholds must be positive")

    if context.intent in {"shutdown", "restart"}:
        return MaintenanceDecision(
            transaction=current,
            may_begin=False,
            authority="ordinary-power-action",
            passthrough_power_action=context.intent,
            passive_state="Maintenance queued",
            reasons=(f"plain_{context.intent}_never_starts_update",),
            attention_required=False,
            notification_policy="none",
        )

    unsafe: list[str] = []
    if context.active_user:
        unsafe.append("active_user")
    if context.fullscreen_or_gaming:
        unsafe.append("fullscreen_or_gaming")
    if not context.power_status_known:
        unsafe.append("power_status_unknown")
    elif not context.on_ac:
        unsafe.append("ac_power_required")
    if context.battery_percent is not None and context.battery_percent < 25:
        unsafe.append("battery_too_low")
    if not context.system_safe:
        unsafe.append("system_not_safe")
    if context.concurrent_package_or_build_operation:
        unsafe.append("concurrent_package_or_build_operation")
    # Adaptive policy is a veto/permission signal only. It cannot erase any
    # native M4 safety reason and therefore cannot authorize around M4 gates.
    if context.adaptive_maintenance == "suspended":
        unsafe.append("adaptive_maintenance_suspended")

    authority = "none"
    if context.intent == "explicit-update" and not unsafe:
        authority = "explicit-update-intent"
    unattended = (
        context.intent == "none"
        and context.unattended_allowed
        and context.locked
        and context.idle_seconds >= idle_threshold_seconds
        and not unsafe
    )
    if unattended:
        authority = "certified-unattended-maintenance"

    if authority != "none":
        evidence: dict[str, Any] = {
            "authority": authority,
            "idle_seconds": context.idle_seconds,
            "locked": context.locked,
        }
        if authority_evidence is not None:
            evidence["coordinator"] = dict(authority_evidence)
        ready = transition_transaction(
            current, UpdateState.MAINTENANCE_READY,
            reason="explicit or certified unattended maintenance authority granted",
            evidence=evidence,
            now=now,
        )
        return MaintenanceDecision(
            transaction=ready,
            may_begin=True,
            authority=authority,
            passthrough_power_action=None,
            passive_state="Maintenance queued",
            reasons=(),
            attention_required=False,
            notification_policy="none",
        )

    attention_reasons: list[str] = []
    if context.serious_security_issue:
        attention_reasons.append("serious_security_issue_deferred")
    if context.update_debt_days >= debt_attention_days:
        attention_reasons.append("update_debt_excessive")
    if attention_reasons:
        reasons = tuple(dict.fromkeys([*attention_reasons, *unsafe]))
        attention = transition_transaction(
            current, UpdateState.ATTENTION_REQUIRED,
            reason="maintenance needs one meaningful user handoff",
            blockers=list(reasons), now=now,
        )
        return MaintenanceDecision(
            transaction=attention,
            may_begin=False,
            authority="attention-handoff",
            passthrough_power_action=None,
            passive_state="Attention required",
            reasons=reasons,
            attention_required=True,
            notification_policy="one-meaningful-attention",
        )

    deferred = tuple(unsafe) or ("no_suitable_maintenance_opportunity",)
    return MaintenanceDecision(
        transaction=current,
        may_begin=False,
        authority="deferred",
        passthrough_power_action=None,
        passive_state="Maintenance queued",
        reasons=deferred,
        attention_required=False,
        notification_policy="none",
    )
