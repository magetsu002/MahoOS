#!/usr/bin/env python3
"""Explicit V1 registry of Guardian-certified recovery paths.

Certification is product-owned policy. Runtime incident data may describe a
failure, but it cannot self-certify a mutating recovery by setting a boolean.
Only exact entries in this registry may reach an automatic executor.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CertifiedServiceRecovery:
    unit: str
    ownership: str
    provider: str
    mode: str
    provider_action: str
    expected_restart: str
    failure_identity: str
    healthy_active_state: str
    healthy_sub_state: str
    replacement_timeout_seconds: float
    stability_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CertifiedGuardianRestart:
    """A future, explicitly Guardian-owned direct restart contract."""

    unit: str
    action: str = "restart-service"
    precondition: str = "systemd-user-failed"
    postcondition: str = "systemd-user-active"


_SERVICE_RECOVERIES = {
    "maho-notify.service": CertifiedServiceRecovery(
        unit="maho-notify.service",
        ownership="maho",
        provider="systemd-user",
        mode="delegated",
        provider_action="restart-on-failure",
        expected_restart="on-failure",
        failure_identity="boot-id+unit+invocation-id",
        healthy_active_state="active",
        healthy_sub_state="running",
        replacement_timeout_seconds=5.0,
        stability_seconds=3.0,
    ),
}

# G1 intentionally has no Guardian-owned ordinary service restart.
_GUARDIAN_RESTARTS: dict[str, CertifiedGuardianRestart] = {}


def certified_service_recovery(unit: object) -> CertifiedServiceRecovery | None:
    if not isinstance(unit, str):
        return None
    return _SERVICE_RECOVERIES.get(unit)


def certified_service_units() -> tuple[str, ...]:
    return tuple(sorted(_SERVICE_RECOVERIES))


def certified_guardian_restart(unit: object) -> CertifiedGuardianRestart | None:
    """Return no direct restart path in G1.

    Ordinary Notify crashes are delegated to systemd. Keeping this separate
    lookup makes it impossible for a delegated provider contract to leak into
    the direct Guardian executor.
    """
    if not isinstance(unit, str):
        return None
    return _GUARDIAN_RESTARTS.get(unit)
