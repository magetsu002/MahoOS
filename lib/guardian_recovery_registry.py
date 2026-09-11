#!/usr/bin/env python3
"""Explicit registry of Guardian-certified recovery paths.

Certification is product-owned policy. Runtime incident data may describe a
failure, but it cannot self-certify a mutating recovery by setting a boolean.
Only exact entries in this registry may reach a recovery authority boundary.
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
    health_check: str
    health_process_patterns: tuple[str, ...]
    replacement_timeout_seconds: float
    stability_seconds: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CertifiedRuntimeRecovery:
    domain: str
    ownership: str
    provider: str
    mode: str
    action: str
    scope: str
    executor: str
    preserves_personal_files: bool
    previous_runtime_required: bool
    automatic_only_in_transaction: bool
    postcondition: str

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
        unit="maho-notify.service", ownership="maho", provider="systemd-user", mode="delegated",
        provider_action="restart-on-failure", expected_restart="on-failure",
        failure_identity="boot-id+unit+invocation-id", healthy_active_state="active", healthy_sub_state="running",
        health_check="quickshell-notify-runtime", health_process_patterns=("quickshell", "maho-notify"),
        replacement_timeout_seconds=5.0, stability_seconds=3.0,
    ),
    "maho-shell.service": CertifiedServiceRecovery(
        unit="maho-shell.service", ownership="maho", provider="systemd-user", mode="delegated",
        provider_action="restart-on-failure", expected_restart="on-failure",
        failure_identity="boot-id+unit+invocation-id", healthy_active_state="active", healthy_sub_state="running",
        health_check="quickshell-shell-runtime", health_process_patterns=("quickshell", "maho-shell/shell.qml"),
        replacement_timeout_seconds=5.0, stability_seconds=3.0,
    ),
    "maho-dock.service": CertifiedServiceRecovery(
        unit="maho-dock.service", ownership="maho", provider="systemd-user", mode="delegated",
        provider_action="restart-on-failure", expected_restart="on-failure",
        failure_identity="boot-id+unit+invocation-id", healthy_active_state="active", healthy_sub_state="running",
        health_check="quickshell-dock-runtime", health_process_patterns=("quickshell", "maho-shell/dock-shell.qml"),
        replacement_timeout_seconds=5.0, stability_seconds=3.0,
    ),
    "maho-wallpaper.service": CertifiedServiceRecovery(
        unit="maho-wallpaper.service", ownership="maho", provider="systemd-user", mode="delegated",
        provider_action="restart-on-failure", expected_restart="on-failure",
        failure_identity="boot-id+unit+invocation-id", healthy_active_state="active", healthy_sub_state="running",
        health_check="wallpaper-watch-runtime", health_process_patterns=("maho-wallpaper", "watch"),
        replacement_timeout_seconds=5.0, stability_seconds=3.0,
    ),
    "maho-awww-daemon.service": CertifiedServiceRecovery(
        unit="maho-awww-daemon.service", ownership="maho", provider="systemd-user", mode="delegated",
        provider_action="restart-always", expected_restart="always",
        failure_identity="boot-id+unit+invocation-id", healthy_active_state="active", healthy_sub_state="running",
        health_check="awww-daemon-runtime", health_process_patterns=("awww-daemon", "--no-cache"),
        replacement_timeout_seconds=5.0, stability_seconds=3.0,
    ),
    "maho-security.service": CertifiedServiceRecovery(
        unit="maho-security.service", ownership="maho", provider="systemd-user", mode="delegated",
        provider_action="restart-on-failure", expected_restart="on-failure",
        failure_identity="boot-id+unit+invocation-id", healthy_active_state="active", healthy_sub_state="running",
        health_check="security-monitor-runtime", health_process_patterns=("maho-security-monitor", "watch"),
        replacement_timeout_seconds=8.0, stability_seconds=3.0,
    ),
    "maho-observe.service": CertifiedServiceRecovery(
        unit="maho-observe.service", ownership="maho", provider="systemd-user", mode="delegated",
        provider_action="restart-on-failure", expected_restart="on-failure",
        failure_identity="boot-id+unit+invocation-id", healthy_active_state="active", healthy_sub_state="running",
        health_check="observer-watch-runtime", health_process_patterns=("maho-observe", "watch"),
        replacement_timeout_seconds=5.0, stability_seconds=3.0,
    ),
    "maho-clipboard-history.service": CertifiedServiceRecovery(
        unit="maho-clipboard-history.service", ownership="maho", provider="systemd-user", mode="delegated",
        provider_action="restart-always", expected_restart="always",
        failure_identity="boot-id+unit+invocation-id", healthy_active_state="active", healthy_sub_state="running",
        health_check="clipboard-history-owner", health_process_patterns=("maho-clipboard-history", "serve", "wl-paste", "--watch"),
        replacement_timeout_seconds=5.0, stability_seconds=3.0,
    ),
}

_RUNTIME_RECOVERIES = {
    "maho-runtime": CertifiedRuntimeRecovery(
        domain="maho-runtime",
        ownership="maho",
        provider="maho-runtime",
        mode="transactional",
        action="rollback-previous",
        scope="maho-runtime",
        executor="maho-setup",
        preserves_personal_files=True,
        previous_runtime_required=True,
        automatic_only_in_transaction=True,
        postcondition="verified-previous-is-current-and-managed-wiring-matches-current",
    ),
}

# G1/G2 intentionally have no Guardian-owned ordinary service restart.
_GUARDIAN_RESTARTS: dict[str, CertifiedGuardianRestart] = {}


def certified_service_recovery(unit: object) -> CertifiedServiceRecovery | None:
    if not isinstance(unit, str):
        return None
    return _SERVICE_RECOVERIES.get(unit)


def certified_service_units() -> tuple[str, ...]:
    return tuple(sorted(_SERVICE_RECOVERIES))


def certified_runtime_recovery(domain: object) -> CertifiedRuntimeRecovery | None:
    if not isinstance(domain, str):
        return None
    return _RUNTIME_RECOVERIES.get(domain)


def certified_runtime_domains() -> tuple[str, ...]:
    return tuple(sorted(_RUNTIME_RECOVERIES))


def certified_guardian_restart(unit: object) -> CertifiedGuardianRestart | None:
    """Return no direct ordinary service restart path in G2.

    Ordinary Notify crashes are delegated to systemd. Keeping this separate
    lookup makes it impossible for a delegated provider contract to leak into
    the direct Guardian executor.
    """
    if not isinstance(unit, str):
        return None
    return _GUARDIAN_RESTARTS.get(unit)
