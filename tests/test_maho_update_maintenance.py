#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_update_maintenance import MaintenanceContext, evaluate_maintenance  # noqa: E402
from maho_update_state import UpdateState, create_transaction, transition_transaction  # noqa: E402

NOW = datetime(2026, 9, 12, 5, 0, tzinfo=timezone.utc)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def prepared() -> dict:
    transaction = create_transaction(
        transaction_id="upd-20260912T050000Z-abcdefabcdef", source_revision="e" * 40,
        packages=[{"name": "demo", "installed_version": "1", "candidate_version": "2", "repository": "core", "roles": []}],
        activation_requirements=[], recovery_generation_id=None, now=NOW,
    )
    transaction = transition_transaction(transaction, UpdateState.STAGED, now=NOW)
    return transition_transaction(transaction, UpdateState.PREPARED, now=NOW)


def context(**changes) -> MaintenanceContext:
    values = {
        "intent": "none",
        "active_user": False,
        "fullscreen_or_gaming": False,
        "idle_seconds": 3600,
        "locked": True,
        "power_status_known": True,
        "on_ac": True,
        "battery_percent": 100,
        "system_safe": True,
        "concurrent_package_or_build_operation": False,
        "unattended_allowed": True,
        "serious_security_issue": False,
        "update_debt_days": 2,
    }
    values.update(changes)
    return MaintenanceContext(**values)


def main() -> None:
    unattended = evaluate_maintenance(prepared(), context(), now=NOW)
    check("idle locked AC safe state grants certified unattended authority", unattended.may_begin and unattended.authority == "certified-unattended-maintenance")
    check("eligible policy advances shared authority to MAINTENANCE_READY", unattended.transaction["state"] == "MAINTENANCE_READY")
    check("maintenance readiness never requests a forced reboot", unattended.reboot_requested is False)

    explicit = evaluate_maintenance(prepared(), context(intent="explicit-update", unattended_allowed=False), now=NOW)
    check("explicit update intent is a distinct maintenance authority", explicit.may_begin and explicit.authority == "explicit-update-intent")

    for intent in ("shutdown", "restart"):
        decision = evaluate_maintenance(prepared(), context(intent=intent), now=NOW)
        check(f"plain {intent} passes through without update", not decision.may_begin and decision.passthrough_power_action == intent and decision.transaction["state"] == "PREPARED")
        check(f"plain {intent} remains notification silent", decision.notification_policy == "none")

    for label, changes, reason in (
        ("active user", {"active_user": True}, "active_user"),
        ("gaming", {"fullscreen_or_gaming": True}, "fullscreen_or_gaming"),
        ("unlocked", {"locked": False}, "no_suitable_maintenance_opportunity"),
        ("not idle", {"idle_seconds": 10}, "no_suitable_maintenance_opportunity"),
        ("unknown power", {"power_status_known": False}, "power_status_unknown"),
        ("AC removed", {"on_ac": False}, "ac_power_required"),
        ("low battery", {"on_ac": False, "battery_percent": 10}, "battery_too_low"),
        ("concurrent work", {"concurrent_package_or_build_operation": True}, "concurrent_package_or_build_operation"),
    ):
        decision = evaluate_maintenance(prepared(), context(**changes), now=NOW)
        check(f"{label} defers without installing", not decision.may_begin and decision.transaction["state"] == "PREPARED" and reason in decision.reasons)

    active_explicit = evaluate_maintenance(prepared(), context(intent="explicit-update", active_user=True), now=NOW)
    check("explicit intent cannot bypass active-user safety", not active_explicit.may_begin and "active_user" in active_explicit.reasons)
    gaming_explicit = evaluate_maintenance(prepared(), context(intent="explicit-update", fullscreen_or_gaming=True), now=NOW)
    check("explicit intent cannot bypass gaming safety", not gaming_explicit.may_begin and "fullscreen_or_gaming" in gaming_explicit.reasons)

    security = evaluate_maintenance(prepared(), context(active_user=True, serious_security_issue=True), now=NOW)
    check("serious deferred security issue creates one attention state", security.attention_required and security.transaction["state"] == "ATTENTION_REQUIRED" and security.notification_policy == "one-meaningful-attention")
    debt = evaluate_maintenance(prepared(), context(active_user=True, update_debt_days=45), now=NOW)
    check("excessive age-based debt creates attention without package counting", debt.attention_required and "update_debt_excessive" in debt.reasons)
    routine = evaluate_maintenance(prepared(), context(active_user=True, update_debt_days=5), now=NOW)
    check("routine deferral remains passive and silent", routine.passive_state == "Maintenance queued" and routine.notification_policy == "none")

    print("ALL MAHO UPDATE MAINTENANCE POLICY CONTRACTS PASS")


if __name__ == "__main__":
    main()
