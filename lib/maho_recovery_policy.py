#!/usr/bin/env python3
"""Pure recovery-policy planner for MahoOS.

This module never mutates the machine. It consumes normalized failure facts and
returns the smallest recovery action Maho is allowed to recommend or perform.
Actual rollback/boot/snapshot adapters live behind separate privileged
boundaries.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from guardian_recovery_registry import certified_service_recovery


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    scope: str
    requires_confirmation: bool
    automatic_allowed: bool
    surface: str
    preserves_personal_files: bool
    reason: str
    target: str | None = None
    provider: str | None = None
    recovery_mode: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bool(mapping: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = mapping.get(key, default)
    return value if isinstance(value, bool) else default


def _int(mapping: Mapping[str, Any], key: str, default: int = 0) -> int:
    value = mapping.get(key, default)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def decide_recovery(state: Mapping[str, Any], *, service_failure_threshold: int = 3) -> RecoveryDecision:
    """Return a deterministic recovery decision without performing it.

    Expected normalized domains are: ``maho-runtime``, ``kernel``,
    ``system-userspace``, ``service`` and ``unknown``. Unknown or malformed
    inputs fail closed to diagnosis only.
    """

    failure = _mapping(state.get("failure"))
    availability = _mapping(state.get("availability"))
    service = _mapping(state.get("service"))

    domain = failure.get("domain")
    if not isinstance(domain, str):
        domain = "unknown"
    graphical_available = _bool(failure, "graphical_available", False)
    transaction_in_progress = _bool(failure, "transaction_in_progress", False)

    if domain == "kernel":
        if _bool(availability, "lts_kernel", False):
            return RecoveryDecision(
                action="boot-lts-kernel",
                scope="kernel",
                requires_confirmation=True,
                automatic_allowed=False,
                surface="boot-recovery",
                preserves_personal_files=True,
                reason="The normal kernel failed before a healthy userspace could be established; an LTS fallback is available.",
            )
        return RecoveryDecision(
            action="open-recovery-console",
            scope="diagnostic",
            requires_confirmation=False,
            automatic_allowed=True,
            surface="text-console",
            preserves_personal_files=True,
            reason="Kernel failure was identified but no verified LTS fallback is available.",
        )

    if domain == "system-userspace":
        if _bool(availability, "root_snapshot", False):
            home_scope = availability.get("home_excluded_from_root_snapshot")
            if not isinstance(home_scope, bool):
                return RecoveryDecision(
                    action="open-recovery-console",
                    scope="diagnostic",
                    requires_confirmation=False,
                    automatic_allowed=True,
                    surface="graphical-recovery" if graphical_available else "text-console",
                    preserves_personal_files=False,
                    reason=(
                        "A system-state snapshot is available, but Maho cannot prove whether personal data is inside "
                        "its rollback scope, so restore-system-state is not authorized."
                    ),
                )
            return RecoveryDecision(
                action="restore-system-state",
                scope="root-filesystem",
                requires_confirmation=True,
                automatic_allowed=False,
                surface="graphical-recovery" if graphical_available else "text-console",
                preserves_personal_files=home_scope,
                reason="The booted kernel is healthy but the system userspace failed verification; a previous root snapshot is available.",
            )
        return RecoveryDecision(
            action="open-recovery-console",
            scope="diagnostic",
            requires_confirmation=False,
            automatic_allowed=True,
            surface="graphical-recovery" if graphical_available else "text-console",
            preserves_personal_files=True,
            reason="Userspace failure was identified but no verified system-state snapshot is available.",
        )

    if domain == "maho-runtime":
        if _bool(availability, "previous_runtime_verified", False):
            return RecoveryDecision(
                action="rollback-maho-runtime",
                scope="maho-runtime",
                requires_confirmation=not transaction_in_progress,
                automatic_allowed=transaction_in_progress,
                surface="graphical-recovery" if graphical_available else "text-console",
                preserves_personal_files=True,
                reason="The Maho runtime failed verification and a previously verified immutable runtime is available.",
            )
        return RecoveryDecision(
            action="open-recovery-console",
            scope="diagnostic",
            requires_confirmation=False,
            automatic_allowed=True,
            surface="graphical-recovery" if graphical_available else "text-console",
            preserves_personal_files=True,
            reason="The Maho runtime failed verification and there is no verified previous runtime to restore.",
        )

    if domain == "service":
        name = service.get("name") if isinstance(service.get("name"), str) else "service"
        provider_unresolved = _bool(service, "provider_recovery_unresolved", False)
        certified = certified_service_recovery(name)
        if (
            certified is not None
            and certified.provider == "systemd-user"
            and certified.mode == "delegated"
            and not provider_unresolved
        ):
            return RecoveryDecision(
                action="observe-service-recovery",
                scope="service",
                requires_confirmation=False,
                automatic_allowed=True,
                surface="incident",
                preserves_personal_files=True,
                reason=(
                    f"{name} has an exact product-owned delegated recovery contract; "
                    "systemd-user owns restart-on-failure and Guardian must only verify it."
                ),
                target=name,
                provider=certified.provider,
                recovery_mode=certified.mode,
            )
        return RecoveryDecision(
            action="diagnose-service-incident",
            scope="service",
            requires_confirmation=False,
            automatic_allowed=True,
            surface="incident",
            preserves_personal_files=True,
            reason=(
                f"{name} has no currently successful certified provider recovery; diagnose the "
                "incident instead of trusting runtime self-certification or retrying indefinitely."
            ),
            target=name if name != "service" else None,
        )

    return RecoveryDecision(
        action="diagnose-only",
        scope="diagnostic",
        requires_confirmation=False,
        automatic_allowed=True,
        surface="incident" if graphical_available else "text-console",
        preserves_personal_files=True,
        reason="The failure domain is unknown, so Maho must not guess at a mutating recovery action.",
    )


def decision_json(state: Mapping[str, Any], *, service_failure_threshold: int = 3) -> str:
    return json.dumps(
        decide_recovery(state, service_failure_threshold=service_failure_threshold).as_dict(),
        sort_keys=True,
        separators=(",", ":"),
    )
