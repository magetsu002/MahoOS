#!/usr/bin/env python3
"""Unified read-only Guardian world state, self-health, and trust posture."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping

from guardian_evidence import EvidenceEnvelope, EvidenceFreshness, ProviderHealth, utc_stamp

class GuardianSelfHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"
    UNTRUSTED = "UNTRUSTED"

class GuardianTrustState(str, Enum):
    VERIFIED = "VERIFIED"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"
    UNTRUSTED = "UNTRUSTED"
    RECOVERING = "RECOVERING"
    CONTAINED = "CONTAINED"

@dataclass(frozen=True)
class GuardianSelfFacts:
    durable_state_readable: bool | None = None
    durable_state_writable: bool | None = None
    schema_consistent: bool | None = None
    historical_evidence_integrity: bool | None = None
    runtime_identity_verified: bool | None = None
    clock_sane: bool | None = None
    boot_identity_available: bool | None = None
    recovery_provider_available: bool | None = None
    security_provider_available: bool | None = None
    journal_continuity: bool | None = None
    dropped_events: int | None = None
    def __post_init__(self) -> None:
        if self.dropped_events is not None and self.dropped_events < 0:
            raise ValueError("dropped event count cannot be negative")

@dataclass(frozen=True)
class GuardianSelfHealth:
    state: GuardianSelfHealthState
    reasons: tuple[str, ...]
    stale_providers: tuple[str, ...]
    missing_providers: tuple[str, ...]
    failed_providers: tuple[str, ...]
    required_providers: tuple[str, ...]
    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state"] = self.state.value
        for key in ("reasons", "stale_providers", "missing_providers", "failed_providers", "required_providers"):
            payload[key] = list(payload[key])
        return payload

@dataclass(frozen=True)
class TrustSignal:
    provider_id: str
    state: GuardianTrustState
    reason: str
    def __post_init__(self) -> None:
        if not self.provider_id or not self.reason:
            raise ValueError("trust signal requires provider identity and reason")

@dataclass(frozen=True)
class TrustAssessment:
    state: GuardianTrustState
    reasons: tuple[str, ...]
    signals: tuple[TrustSignal, ...]
    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "reasons": list(self.reasons),
            "signals": [{"provider_id": item.provider_id, "state": item.state.value, "reason": item.reason} for item in self.signals],
        }

def assess_self_health(evidence: Iterable[EvidenceEnvelope], *, required_provider_ids: Iterable[str], facts: GuardianSelfFacts, now: datetime | None = None) -> GuardianSelfHealth:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = {item.provider_id: item for item in evidence}
    required = tuple(sorted(set(required_provider_ids)))
    stale: list[str] = []
    missing: list[str] = []
    failed: list[str] = []
    reasons: list[str] = []
    for provider_id in required:
        item = rows.get(provider_id)
        if item is None:
            missing.append(provider_id)
            continue
        freshness = item.freshness(now=current)
        if freshness is EvidenceFreshness.STALE:
            stale.append(provider_id)
        elif freshness in {EvidenceFreshness.MISSING, EvidenceFreshness.UNSUPPORTED}:
            missing.append(provider_id)
        elif freshness is EvidenceFreshness.FAILED or item.health is ProviderHealth.FAILED:
            failed.append(provider_id)
    unknown_health = sorted(provider_id for provider_id in required if provider_id in rows and rows[provider_id].health is ProviderHealth.UNKNOWN)
    degraded_health = sorted(provider_id for provider_id in required if provider_id in rows and rows[provider_id].health is ProviderHealth.DEGRADED)
    untrusted_facts = {
        "schema_consistent": facts.schema_consistent,
        "historical_evidence_integrity": facts.historical_evidence_integrity,
        "runtime_identity_verified": facts.runtime_identity_verified,
        "clock_sane": facts.clock_sane,
    }
    broken_trust = [name for name, value in untrusted_facts.items() if value is False]
    if broken_trust:
        reasons.extend(f"{name}=false" for name in broken_trust)
        state = GuardianSelfHealthState.UNTRUSTED
    else:
        unknown_critical = [name for name, value in {
            "durable_state_readable": facts.durable_state_readable,
            "schema_consistent": facts.schema_consistent,
            "runtime_identity_verified": facts.runtime_identity_verified,
            "clock_sane": facts.clock_sane,
            "boot_identity_available": facts.boot_identity_available,
        }.items() if value is None]
        if facts.durable_state_readable is False:
            unknown_critical.append("durable_state_readable=false")
        if facts.boot_identity_available is False:
            unknown_critical.append("boot_identity_available=false")
        if missing:
            unknown_critical.append("required_evidence_missing")
        if unknown_health:
            unknown_critical.append("required_provider_health_unknown")
        if unknown_critical:
            reasons.extend(unknown_critical)
            state = GuardianSelfHealthState.UNKNOWN
        else:
            degraded = bool(stale or failed or degraded_health)
            degraded = degraded or facts.durable_state_writable is False
            degraded = degraded or facts.recovery_provider_available is False
            degraded = degraded or facts.security_provider_available is False
            degraded = degraded or facts.journal_continuity is False
            degraded = degraded or bool(facts.dropped_events)
            degraded = degraded or facts.historical_evidence_integrity is None
            if stale:
                reasons.append("required_evidence_stale")
            if failed:
                reasons.append("required_provider_failed")
            if degraded_health:
                reasons.append("required_provider_degraded")
            if facts.durable_state_writable is False:
                reasons.append("durable_state_not_writable")
            if facts.journal_continuity is False:
                reasons.append("journal_continuity_lost")
            if facts.dropped_events:
                reasons.append(f"dropped_events={facts.dropped_events}")
            if facts.recovery_provider_available is False:
                reasons.append("recovery_provider_unavailable")
            if facts.security_provider_available is False:
                reasons.append("security_provider_unavailable")
            if facts.historical_evidence_integrity is None:
                reasons.append("historical_evidence_integrity_unknown")
            state = GuardianSelfHealthState.DEGRADED if degraded else GuardianSelfHealthState.HEALTHY
    return GuardianSelfHealth(state=state, reasons=tuple(dict.fromkeys(reasons)), stale_providers=tuple(sorted(stale)), missing_providers=tuple(sorted(missing)), failed_providers=tuple(sorted(failed)), required_providers=required)

def assess_trust(self_health: GuardianSelfHealth, signals: Iterable[TrustSignal], *, recovering: bool = False, contained: bool = False) -> TrustAssessment:
    rows = tuple(signals)
    reasons = [item.reason for item in rows]
    states = {item.state for item in rows}
    if self_health.state is GuardianSelfHealthState.UNTRUSTED or GuardianTrustState.UNTRUSTED in states:
        state = GuardianTrustState.UNTRUSTED
    elif self_health.state is GuardianSelfHealthState.UNKNOWN or GuardianTrustState.UNKNOWN in states or not rows:
        state = GuardianTrustState.UNKNOWN
    elif contained:
        state = GuardianTrustState.CONTAINED
    elif recovering:
        state = GuardianTrustState.RECOVERING
    elif self_health.state is GuardianSelfHealthState.DEGRADED or GuardianTrustState.DEGRADED in states:
        state = GuardianTrustState.DEGRADED
    elif states <= {GuardianTrustState.VERIFIED}:
        state = GuardianTrustState.VERIFIED
    else:
        state = GuardianTrustState.UNKNOWN
    if self_health.state is not GuardianSelfHealthState.HEALTHY:
        reasons.append(f"guardian_self_health={self_health.state.value}")
    if not rows:
        reasons.append("no_trust_evidence")
    return TrustAssessment(state, tuple(dict.fromkeys(reasons)), rows)

@dataclass(frozen=True)
class GuardianWorldState:
    captured_at: str
    self_health: GuardianSelfHealth
    trust: TrustAssessment
    severity: Mapping[str, Any]
    domains: Mapping[str, tuple[EvidenceEnvelope, ...]]
    def as_dict(self) -> dict[str, Any]:
        now = datetime.fromisoformat(self.captured_at.replace("Z", "+00:00"))
        return {
            "schema_version": 1,
            "kind": "guardian-world-state",
            "captured_at": self.captured_at,
            "guardian": {"self_health": self.self_health.as_dict(), "trust": self.trust.as_dict(), "severity": dict(self.severity)},
            "domains": {name: [item.as_dict(now=now) for item in rows] for name, rows in sorted(self.domains.items())},
        }

def build_world_state(evidence: Iterable[EvidenceEnvelope], *, required_provider_ids: Iterable[str], self_facts: GuardianSelfFacts, trust_signals: Iterable[TrustSignal], severity: Mapping[str, Any] | None = None, recovering: bool = False, contained: bool = False, now: datetime | None = None) -> GuardianWorldState:
    captured = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = tuple(evidence)
    grouped: dict[str, list[EvidenceEnvelope]] = {}
    for item in rows:
        grouped.setdefault(item.domain, []).append(item)
    domains = {name: tuple(sorted(items, key=lambda item: item.provider_id)) for name, items in grouped.items()}
    self_health = assess_self_health(rows, required_provider_ids=required_provider_ids, facts=self_facts, now=captured)
    trust = assess_trust(self_health, trust_signals, recovering=recovering, contained=contained)
    return GuardianWorldState(captured_at=utc_stamp(captured), self_health=self_health, trust=trust, severity=dict(severity or {"level": 0, "label": "normal"}), domains=domains)
