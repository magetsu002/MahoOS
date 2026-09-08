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
    action: str
    max_consecutive_failures: int
    postcondition: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_SERVICE_RECOVERIES = {
    "maho-notify.service": CertifiedServiceRecovery(
        unit="maho-notify.service",
        action="restart-service",
        max_consecutive_failures=2,
        postcondition="systemd-user-active",
    ),
}


def certified_service_recovery(unit: object) -> CertifiedServiceRecovery | None:
    if not isinstance(unit, str):
        return None
    return _SERVICE_RECOVERIES.get(unit)


def certified_service_units() -> tuple[str, ...]:
    return tuple(sorted(_SERVICE_RECOVERIES))
