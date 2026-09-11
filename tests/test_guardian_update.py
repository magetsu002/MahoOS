#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_update import project_update_status  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def status(state: str, **changes) -> dict:
    value = {
        "schema_version": 1, "transaction_id": "upd-20260912T080000Z-abcdef123456",
        "authority_state": state, "attention_required": state == "ATTENTION_REQUIRED",
        "notification_policy": "one-meaningful-attention" if state == "ATTENTION_REQUIRED" else "none",
    }
    value.update(changes)
    return value


def main() -> None:
    for state in ("NONE", "DISCOVERED", "STAGED", "PREPARED", "MAINTENANCE_READY", "INSTALLING", "INSTALLED_PENDING_ACTIVATION", "ACTIVE_VERIFYING", "HEALTHY", "BLOCKED", "RECOVERED"):
        view = project_update_status(status(state))
        check(f"Guardian passively consumes {state}", not view.active and view.guardian_level == 0 and not view.mutating_recovery_allowed)
    recovering = project_update_status(status("RECOVERING"))
    check("Guardian observes bounded update recovery without taking it over", recovering.active and recovering.guardian_level == 1 and recovering.execution_mode == "observe" and not recovering.mutating_recovery_allowed)
    failed = project_update_status(status("FAILED_RECOVERABLE"))
    check("Guardian observes recoverable update failure", failed.active and failed.guardian_level == 1)
    attention = project_update_status(status("ATTENTION_REQUIRED"))
    check("Guardian reflects authoritative attention without mutation", attention.active and attention.guardian_level == 2 and attention.attention_required and not attention.mutating_recovery_allowed)
    malformed = project_update_status({"updated": True})
    check("ambiguous update boolean fails closed in Guardian", malformed.authority_state == "ATTENTION_REQUIRED" and malformed.guardian_level == 2)
    print("ALL GUARDIAN UPDATE AUTHORITY CONTRACTS PASS")


if __name__ == "__main__":
    main()
