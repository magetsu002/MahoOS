#!/usr/bin/env python3
"""Read-only reliability reasoning for Guardian.

Reliability observations describe degradation and may point at an already
certified recovery provider. They never grant mutation authority or causal
proof themselves.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from guardian_evidence import parse_timestamp, utc_stamp
from guardian_provider_state import load_heartbeat
from guardian_recovery_registry import certified_runtime_recovery, certified_service_recovery


class ReliabilityState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


class RemediationDisposition(str, Enum):
    NONE = "none"
    OBSERVE_ONLY = "observe-only"
    DELEGATED_CERTIFIED = "delegated-certified"
    AUTHORIZATION_REQUIRED = "authorization-required"


@dataclass(frozen=True)
class ReliabilityObservation:
    observer_id: str
    domain: str
    subject: str
    freshness: str
    health: str
    facts: Mapping[str, Any] = field(default_factory=dict)
    observed_at: str | None = None


@dataclass(frozen=True)
class ReliabilityFinding:
    observer_id: str
    domain: str
    subject: str
    state: ReliabilityState
    reason: str
    remediation: RemediationDisposition
    provider: str | None = None
    action: str | None = None
    authority_granted: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["state"] = self.state.value
        payload["remediation"] = self.remediation.value
        return payload


@dataclass(frozen=True)
class FailureOccurrence:
    identity: str
    occurred_at: str
    source: str

    def __post_init__(self) -> None:
        if not self.identity or not self.source or parse_timestamp(self.occurred_at) is None:
            raise ValueError("failure occurrence identity/timestamp/source is incomplete")


@dataclass(frozen=True)
class RecurrenceAssessment:
    identity: str
    count: int
    window_seconds: int
    repeated: bool
    confidence: str
    causal_proof_granted: bool = False
    recovery_authority_granted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_recurrence(
    identity: str,
    occurrences: Iterable[FailureOccurrence],
    *,
    now: str | None = None,
    window_seconds: int = 3600,
    repeat_threshold: int = 3,
) -> RecurrenceAssessment:
    if window_seconds <= 0 or repeat_threshold <= 1:
        raise ValueError("recurrence bounds are invalid")
    current = parse_timestamp(now or utc_stamp(datetime.now(timezone.utc)))
    assert current is not None
    count = 0
    for item in occurrences:
        if item.identity != identity:
            continue
        stamp = parse_timestamp(item.occurred_at)
        assert stamp is not None
        age = (current - stamp).total_seconds()
        if 0 <= age <= window_seconds:
            count += 1
    repeated = count >= repeat_threshold
    confidence = "high" if count >= repeat_threshold + 2 else "medium" if repeated else "low"
    return RecurrenceAssessment(identity, count, window_seconds, repeated, confidence)


def _finding(
    observation: ReliabilityObservation,
    state: ReliabilityState,
    reason: str,
    remediation: RemediationDisposition = RemediationDisposition.NONE,
    provider: str | None = None,
    action: str | None = None,
) -> ReliabilityFinding:
    return ReliabilityFinding(
        observation.observer_id, observation.domain, observation.subject,
        state, reason, remediation, provider, action, False,
    )


def assess_observation(observation: ReliabilityObservation) -> ReliabilityFinding:
    freshness = observation.freshness.lower()
    health = observation.health.lower()
    if freshness != "current":
        return _finding(observation, ReliabilityState.UNKNOWN,
                        f"observer evidence is {freshness}; stale/missing/unsupported evidence cannot establish health",
                        RemediationDisposition.OBSERVE_ONLY)
    if health != "healthy":
        state = ReliabilityState.DEGRADED if health in {"degraded", "failed"} else ReliabilityState.UNKNOWN
        return _finding(observation, state, f"observer health is {health}", RemediationDisposition.OBSERVE_ONLY)

    facts = observation.facts
    if observation.domain == "service":
        active_state = str(facts.get("active_state") or "unknown")
        restarts_raw = facts.get("restart_count")
        restarts = int(restarts_raw) if isinstance(restarts_raw, int) and not isinstance(restarts_raw, bool) else 0
        if active_state == "failed" or restarts >= 3:
            contract = certified_service_recovery(observation.subject)
            if contract is None:
                return _finding(observation, ReliabilityState.DEGRADED,
                                "service is failed or restart-churning, but no exact certified service recovery exists",
                                RemediationDisposition.OBSERVE_ONLY)
            return _finding(observation, ReliabilityState.DEGRADED,
                            "service is failed or restart-churning and maps to an existing delegated recovery provider",
                            RemediationDisposition.DELEGATED_CERTIFIED,
                            contract.provider, contract.provider_action)

    if observation.domain == "journal":
        dropped = int(facts.get("dropped_events") or 0)
        continuity = str(facts.get("continuity") or "unknown")
        if dropped > 0 or continuity != "continuous":
            return _finding(observation, ReliabilityState.DEGRADED,
                            "journal continuity is broken or events were dropped",
                            RemediationDisposition.OBSERVE_ONLY)

    if observation.domain == "storage":
        used = facts.get("used_percent")
        if isinstance(used, (int, float)) and not isinstance(used, bool) and float(used) >= 90.0:
            return _finding(observation, ReliabilityState.DEGRADED,
                            f"storage usage is {float(used):.1f}%", RemediationDisposition.OBSERVE_ONLY)

    if observation.domain == "memory":
        available = facts.get("available_percent")
        pressure = str(facts.get("pressure") or "normal")
        if (isinstance(available, (int, float)) and not isinstance(available, bool) and float(available) <= 10.0) or pressure in {"critical", "severe"}:
            return _finding(observation, ReliabilityState.DEGRADED,
                            "memory availability/pressure crossed the reliability threshold",
                            RemediationDisposition.OBSERVE_ONLY)

    if observation.domain in {"thermal", "power"} and facts.get("critical") is True:
        return _finding(observation, ReliabilityState.DEGRADED,
                        f"{observation.domain} observer reports a critical condition",
                        RemediationDisposition.OBSERVE_ONLY)

    if observation.domain == "transaction":
        age = facts.get("age_seconds")
        limit = facts.get("max_age_seconds")
        if isinstance(age, (int, float)) and isinstance(limit, (int, float)) and float(age) > float(limit):
            contract = certified_runtime_recovery(observation.subject)
            if contract is not None:
                return _finding(observation, ReliabilityState.DEGRADED,
                                "transaction exceeded its bounded age; existing runtime recovery still requires transaction authority",
                                RemediationDisposition.AUTHORIZATION_REQUIRED,
                                contract.provider, contract.action)
            return _finding(observation, ReliabilityState.DEGRADED,
                            "transaction exceeded its bounded age without a certified recovery mapping",
                            RemediationDisposition.OBSERVE_ONLY)

    return _finding(observation, ReliabilityState.HEALTHY,
                    "current healthy evidence shows no configured reliability degradation")


def assess_reliability(observations: Iterable[ReliabilityObservation]) -> dict[str, Any]:
    findings = tuple(assess_observation(item) for item in observations)
    counts = {state.value: 0 for state in ReliabilityState}
    for finding in findings:
        counts[finding.state.value] += 1
    overall = ReliabilityState.HEALTHY
    if counts[ReliabilityState.DEGRADED.value]:
        overall = ReliabilityState.DEGRADED
    elif counts[ReliabilityState.UNKNOWN.value]:
        overall = ReliabilityState.UNKNOWN
    return {
        "schema_version": 1,
        "kind": "guardian-reliability",
        "state": overall.value,
        "counts": counts,
        "findings": [item.as_dict() for item in findings],
        "automatic_authority": False,
    }


_LIVE_PROVIDERS = {
    "reliability.memory": ("memory", "host-memory"),
    "reliability.storage": ("storage", "root-filesystem"),
    "reliability.services": ("services", "certified-services"),
}


def _read_state(root: Path, provider_id: str) -> Mapping[str, Any]:
    path = root / "guardian" / "reliability" / f"{provider_id.removeprefix('reliability.')}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, Mapping) else {}


def load_live_reliability(
    root: Path,
    *,
    now: datetime | None = None,
    max_age_seconds: float = 90.0,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    observations: list[ReliabilityObservation] = []
    freshness_rows: dict[str, dict[str, Any]] = {}
    for provider_id, (domain, subject) in _LIVE_PROVIDERS.items():
        try:
            heartbeat = load_heartbeat(root, provider_id)
        except (OSError, ValueError, json.JSONDecodeError):
            heartbeat = None
        if heartbeat is None:
            freshness = "missing"
            health = "unknown"
            observed_at = None
        else:
            observed_at = heartbeat.last_success_at
            health = heartbeat.health.value
            stamp = parse_timestamp(observed_at) if observed_at else None
            freshness = "missing" if stamp is None else ("current" if 0 <= (current - stamp).total_seconds() <= max_age_seconds else "stale")
        state = _read_state(root, provider_id)
        facts = state.get("facts") if isinstance(state.get("facts"), Mapping) else {}
        freshness_rows[provider_id] = {
            "freshness": freshness,
            "health": health,
            "observed_at": observed_at,
            "decision_usable": freshness == "current" and health == "healthy",
        }
        if provider_id == "reliability.services":
            services = facts.get("services") if isinstance(facts.get("services"), list) else []
            if not services:
                observations.append(ReliabilityObservation(provider_id, "service", subject, freshness, health, {}, observed_at))
            for row in services:
                if isinstance(row, Mapping):
                    observations.append(ReliabilityObservation(
                        provider_id, "service", str(row.get("unit") or "unknown"),
                        freshness, health, dict(row), observed_at,
                    ))
        else:
            observations.append(ReliabilityObservation(provider_id, domain, subject, freshness, health, dict(facts), observed_at))
    return assess_reliability(observations), freshness_rows
