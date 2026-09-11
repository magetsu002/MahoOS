#!/usr/bin/env python3
"""Cross-layer M4A failure campaign. All mutation is confined to temporary fixtures."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

from maho_update_maintenance import evaluate_maintenance  # noqa: E402
from maho_update_preparation import prepare_transaction  # noqa: E402
from maho_update_receipts import product_status  # noqa: E402
from maho_update_staging import stage_transaction  # noqa: E402
from maho_update_state import UpdateState, transition_transaction, validate_transaction  # noqa: E402
from maho_update_transaction import build_execution_plan, execute_update, recover_interrupted_fixture  # noqa: E402
from test_maho_update_maintenance import context, prepared  # noqa: E402
from test_maho_update_preparation import evidence, staged  # noqa: E402
from test_maho_update_staging import backend, transaction as staging_transaction  # noqa: E402
from test_maho_update_transaction import FakeOps, ready, relationships  # noqa: E402

NOW = datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc)
SAFE_FAILURE_STATES = {"BLOCKED", "FAILED_RECOVERABLE", "RECOVERING", "RECOVERED", "ATTENTION_REQUIRED"}


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def rejects(function) -> bool:
    try:
        function()
    except (ValueError, PermissionError):
        return True
    return False


def safe_failure(name: str, transaction: dict) -> None:
    check(name, transaction["state"] in SAFE_FAILURE_STATES)


def main() -> None:
    malformed = prepared()
    malformed["history"] = "corrupt"
    check("malformed durable state fails closed", rejects(lambda: validate_transaction(malformed)))
    check("illegal transition fails closed", rejects(lambda: transition_transaction(prepared(), UpdateState.HEALTHY)))

    with tempfile.TemporaryDirectory(prefix="maho-update-adversarial-prep-") as temporary:
        cache = Path(temporary)
        transaction, manifest = staged(cache)
        stale = prepare_transaction(transaction, manifest, cache, evidence(execution_environment="fixture", discovery_generation_current=False), now=NOW)
        safe_failure("stale transaction blocks before mutation", stale.transaction)
        unavailable = prepare_transaction(transaction, manifest, cache, evidence(execution_environment="fixture", recovery_protection_available=False), now=NOW)
        safe_failure("recovery unavailable blocks before mutation", unavailable.transaction)

    for label, options, available, expected in (
        ("package disappeared after discovery", {"missing": "maho-os"}, 1024**3, "BLOCKED"),
        ("incomplete staging", {"incomplete": True}, 1024**3, "FAILED_RECOVERABLE"),
        ("low staging disk", {}, 1, "BLOCKED"),
        ("network unavailable", {"download_error": True}, 1024**3, "FAILED_RECOVERABLE"),
    ):
        with tempfile.TemporaryDirectory(prefix="maho-update-adversarial-stage-") as temporary:
            result = stage_transaction(staging_transaction(), backend(Path(temporary), **options), available_bytes=available, now=NOW)
            check(f"{label} has explicit safe state", result.transaction["state"] == expected)

    for label, changes, reason in (
        ("low battery", {"on_ac": False, "battery_percent": 5}, "battery_too_low"),
        ("AC removed", {"on_ac": False}, "ac_power_required"),
        ("active user", {"active_user": True}, "active_user"),
        ("fullscreen gaming", {"fullscreen_or_gaming": True}, "fullscreen_or_gaming"),
        ("concurrent package transaction", {"concurrent_package_or_build_operation": True}, "concurrent_package_or_build_operation"),
    ):
        decision = evaluate_maintenance(prepared(), context(**changes), now=NOW)
        check(f"{label} defers before mutation", not decision.may_begin and reason in decision.reasons and decision.transaction["state"] == "PREPARED")

    with tempfile.TemporaryDirectory(prefix="maho-update-adversarial-engine-") as temporary:
        cache = Path(temporary)
        transaction, manifest = ready(cache)
        plan = build_execution_plan(transaction, manifest, cache, relationships(), execution_environment="fixture")
        check("kernel/header mismatch blocks before mutation", rejects(lambda: build_execution_plan(transaction, manifest, cache, relationships(primary_headers={"package": "linux-cachyos-headers", "version": "bad"}), execution_environment="fixture")))
        check("missing Fallback kernel blocks before mutation", rejects(lambda: build_execution_plan(transaction, manifest, cache, relationships(fallback_kernel=None), execution_environment="fixture")))
        for label, stage in (
            ("DKMS failure", "kernel-header-dkms"),
            ("Primary initramfs failure", "initramfs:linux-cachyos"),
            ("Fallback initramfs failure", "initramfs:linux-cachyos-lts"),
            ("boot artifact mismatch", "boot-artifacts"),
            ("Maho runtime failure", "maho-runtime"),
        ):
            result = execute_update(transaction, plan, FakeOps(fail=stage), now=NOW)
            check(f"{label} performs bounded recovery", result.transaction["state"] == "RECOVERED" and result.recovery_attempted)
        failed_recovery = execute_update(transaction, plan, FakeOps(fail="boot-artifacts", recover_ok=False), now=NOW)
        check("failed recovery becomes explicit handoff", failed_recovery.transaction["state"] == "ATTENTION_REQUIRED")
        interrupted = transition_transaction(transaction, UpdateState.INSTALLING, reason="interrupted", now=NOW)
        reconciled = recover_interrupted_fixture(interrupted, plan, FakeOps(), now=NOW)
        check("interrupted transaction is recovered explicitly", reconciled.transaction["state"] == "RECOVERED")
        success = execute_update(transaction, plan, FakeOps(), now=NOW)
        check("success awaits restart without activating", success.transaction["state"] == "INSTALLED_PENDING_ACTIVATION" and not success.reboot_performed)
        check("routine installed receipt requests no popup", product_status(success.transaction)["notification_policy"] == "none")

    for action in ("shutdown", "restart"):
        decision = evaluate_maintenance(prepared(), context(intent=action), now=NOW)
        check(f"ordinary {action} never triggers maintenance", not decision.may_begin and decision.passthrough_power_action == action and decision.transaction["state"] == "PREPARED")
    attention = evaluate_maintenance(prepared(), context(active_user=True, serious_security_issue=True), now=NOW)
    check("serious prolonged blockage escalates once", product_status(attention.transaction)["notification_policy"] == "one-meaningful-attention")

    print("ALL MAHO UPDATE ADVERSARIAL CAMPAIGNS PASS")


if __name__ == "__main__":
    main()
