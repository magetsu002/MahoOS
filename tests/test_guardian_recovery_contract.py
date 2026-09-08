#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_engine import evaluate_guardian  # noqa: E402
from maho_recovery_policy import decide_recovery  # noqa: E402


def effective_automatic_mutation(guardian_state: dict, recovery_state: dict) -> bool:
    return evaluate_guardian(guardian_state, recovery_state).mutating_recovery_allowed


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def main() -> None:
    tiny_maho_incident = {
        "incident": {
            "scope": "component",
            "ownership": "maho",
            "impact": "minor",
            "evidence_confidence": "confirmed",
            "occurrence_count": 1,
        },
        "recovery": {"confidence": "certified", "certified_path": True},
    }
    safe_service_recovery = {
        "failure": {"domain": "service", "graphical_available": True},
        "service": {
            "name": "maho-notify.service",
            "consecutive_failures": 1,
            "restart_safe": False,
        },
    }
    decision = decide_recovery(safe_service_recovery)
    check(
        "recovery planner selects only the explicitly registered Maho Notify provider",
        decision.action == "observe-service-recovery"
        and decision.target == "maho-notify.service"
        and decision.provider == "systemd-user"
        and decision.recovery_mode == "delegated"
        and decision.automatic_allowed,
    )
    check(
        "delegated provider recovery never grants Guardian mutation",
        not effective_automatic_mutation(tiny_maho_incident, safe_service_recovery),
    )

    spoofed_service_recovery = {
        "failure": {"domain": "service", "graphical_available": True},
        "service": {
            "name": "external.service",
            "consecutive_failures": 1,
            "restart_safe": True,
        },
    }
    check(
        "runtime restart_safe flag cannot self-certify an external service",
        decide_recovery(spoofed_service_recovery).action == "diagnose-service-incident",
    )

    unknown_owner = {
        "incident": {
            "scope": "component",
            "ownership": "unknown",
            "impact": "minor",
            "evidence_confidence": "confirmed",
            "occurrence_count": 1,
        },
        "recovery": {"confidence": "certified", "certified_path": True},
    }
    check(
        "unknown ownership blocks mutation even when recovery planner says automatic",
        not effective_automatic_mutation(unknown_owner, safe_service_recovery),
    )

    runtime_l3 = {
        "incident": {
            "scope": "runtime",
            "ownership": "maho",
            "impact": "unavailable",
            "evidence_confidence": "confirmed",
            "persistent": True,
            "correlated_failures": 2,
        },
        "recovery": {
            "confidence": "certified",
            "certified_path": True,
            "previous_failures": 1,
        },
    }
    post_transaction_rollback = {
        "failure": {
            "domain": "maho-runtime",
            "transaction_in_progress": False,
            "graphical_available": True,
        },
        "availability": {"previous_runtime_verified": True},
    }
    check(
        "post-transaction rollback remains confirmation-gated despite L3 certification",
        not effective_automatic_mutation(runtime_l3, post_transaction_rollback),
    )

    in_transaction_rollback = {
        "failure": {
            "domain": "maho-runtime",
            "transaction_in_progress": True,
            "graphical_available": True,
        },
        "availability": {"previous_runtime_verified": True},
    }
    check(
        "certified in-transaction runtime rollback may self-heal",
        effective_automatic_mutation(runtime_l3, in_transaction_rollback),
    )

    catastrophic = {
        "incident": {
            "scope": "boot",
            "ownership": "maho",
            "impact": "catastrophic",
            "evidence_confidence": "confirmed",
            "persistent": True,
        },
        "recovery": {"confidence": "certified", "certified_path": True},
    }
    kernel_fallback = {
        "failure": {"domain": "kernel"},
        "availability": {"lts_kernel": True},
    }
    check(
        "L4 never becomes automatic mutation even with a known fallback",
        not effective_automatic_mutation(catastrophic, kernel_fallback),
    )

    print("ALL GUARDIAN/RECOVERY COMPATIBILITY CONTRACTS PASS")


if __name__ == "__main__":
    main()
