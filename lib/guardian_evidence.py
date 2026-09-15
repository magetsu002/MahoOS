#!/usr/bin/env python3
"""Common Guardian evidence envelope and freshness semantics.

Providers keep ownership of their typed payloads. This module standardizes only
identity, provenance, freshness, health, confidence, errors, and authority
boundaries so missing visibility can never masquerade as a healthy observation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import math
import re
from typing import Any, Mapping, Protocol

_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9._:-]{1,127}")
_DOMAIN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")

class EvidenceFreshness(str, Enum):
    CURRENT = "current"
    STALE = "stale"
    MISSING = "missing"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    NOT_APPLICABLE = "not-applicable"

class ProviderHealth(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    FAILED = "failed"

class EvidenceConfidence(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CONFIRMED = "confirmed"

@dataclass(frozen=True)
class FreshnessPolicy:
    max_age_seconds: float | None
    required: bool = True
    def __post_init__(self) -> None:
        if self.max_age_seconds is not None and (not math.isfinite(self.max_age_seconds) or self.max_age_seconds <= 0):
            raise ValueError("freshness max age must be a positive finite number")

def parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("evidence timestamp must be text")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("evidence timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)

def utc_stamp(value: datetime) -> str:
    current = value.astimezone(timezone.utc)
    return current.isoformat(timespec="milliseconds").replace("+00:00", "Z")

class EvidenceProvider(Protocol):
    provider_id: str
    domain: str
    def observe(self, *, now: datetime | None = None) -> "EvidenceEnvelope": ...

@dataclass(frozen=True)
class EvidenceEnvelope:
    provider_id: str
    domain: str
    schema_version: int
    observed_at: str | None
    source: str
    freshness_policy: FreshnessPolicy
    health: ProviderHealth
    data: Mapping[str, Any]
    confidence: EvidenceConfidence
    errors: tuple[str, ...]
    authority_boundary: str
    supported: bool = True
    applicable: bool = True
    def __post_init__(self) -> None:
        if _PROVIDER_ID.fullmatch(self.provider_id) is None:
            raise ValueError("evidence provider identity is invalid")
        if _DOMAIN.fullmatch(self.domain) is None:
            raise ValueError("evidence domain is invalid")
        if self.schema_version <= 0:
            raise ValueError("evidence schema version must be positive")
        if not self.source or not self.authority_boundary:
            raise ValueError("evidence provenance and authority boundary are required")
        if self.observed_at is not None:
            parse_timestamp(self.observed_at)
    def freshness(self, *, now: datetime | None = None) -> EvidenceFreshness:
        if not self.applicable:
            return EvidenceFreshness.NOT_APPLICABLE
        if not self.supported:
            return EvidenceFreshness.UNSUPPORTED
        if self.health is ProviderHealth.FAILED:
            return EvidenceFreshness.FAILED
        observed = parse_timestamp(self.observed_at)
        if observed is None:
            return EvidenceFreshness.MISSING
        if self.freshness_policy.max_age_seconds is None:
            return EvidenceFreshness.CURRENT
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        age = (current - observed).total_seconds()
        return EvidenceFreshness.CURRENT if age <= self.freshness_policy.max_age_seconds else EvidenceFreshness.STALE
    def age_seconds(self, *, now: datetime | None = None) -> float | None:
        observed = parse_timestamp(self.observed_at)
        if observed is None:
            return None
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return (current - observed).total_seconds()
    def decision_usable(self, *, now: datetime | None = None) -> bool:
        return self.freshness(now=now) is EvidenceFreshness.CURRENT and self.health is ProviderHealth.HEALTHY
    def as_dict(self, *, now: datetime | None = None) -> dict[str, Any]:
        payload = asdict(self)
        payload["freshness_policy"] = asdict(self.freshness_policy)
        payload["health"] = self.health.value
        payload["confidence"] = self.confidence.value
        payload["errors"] = list(self.errors)
        payload["freshness"] = self.freshness(now=now).value
        age = self.age_seconds(now=now)
        payload["age_seconds"] = None if age is None else round(age, 3)
        payload["decision_usable"] = self.decision_usable(now=now)
        return payload

def missing_evidence(provider_id: str, domain: str, *, source: str, max_age_seconds: float, authority_boundary: str, required: bool = True) -> EvidenceEnvelope:
    return EvidenceEnvelope(provider_id=provider_id, domain=domain, schema_version=1, observed_at=None, source=source, freshness_policy=FreshnessPolicy(max_age_seconds, required=required), health=ProviderHealth.UNKNOWN, data={}, confidence=EvidenceConfidence.NONE, errors=("evidence_missing",), authority_boundary=authority_boundary)
