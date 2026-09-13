#!/usr/bin/env python3
"""Normalized immutable situation snapshots for Maho adaptive policy.

This layer consumes already-observed state. It never reads /sys, processes,
QML state, or executes commands; optional capabilities fail independently and
are represented explicitly as ``unknown``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

UNKNOWN = "unknown"
FRESH_SECONDS = 120.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _age(observed_at: Any, captured: datetime) -> float | str:
    observed = _parse_time(observed_at)
    if observed is None:
        return UNKNOWN
    return max(0.0, (captured - observed).total_seconds())


def _freshness(age: float | str) -> str:
    if age == UNKNOWN:
        return UNKNOWN
    return "fresh" if float(age) <= FRESH_SECONDS else "stale"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bool(value: Any) -> bool | str:
    return value if isinstance(value, bool) else UNKNOWN


def _number(value: Any, *, low: float | None = None, high: float | None = None) -> float | int | str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return UNKNOWN
    if low is not None and value < low:
        return UNKNOWN
    if high is not None and value > high:
        return UNKNOWN
    return value


def _text(value: Any, allowed: set[str] | None = None) -> str:
    if not isinstance(value, str) or not value:
        return UNKNOWN
    if allowed is not None and value not in allowed:
        return UNKNOWN
    return value


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _envelope(observations: Mapping[str, Any], domain: str, captured: datetime) -> tuple[Mapping[str, Any], float | str, str]:
    raw = _mapping(observations.get(domain))
    data = _mapping(raw.get("data", raw))
    age = _age(raw.get("observed_at"), captured)
    return data, age, _freshness(age)


@dataclass(frozen=True)
class TimeSituation:
    captured_at: str
    observation_age_seconds: float | str
    session_age_seconds: float | str


@dataclass(frozen=True)
class PowerSituation:
    ac_online: bool | str
    battery_present: bool | str
    percentage: int | str
    charging_state: str
    drain_trend: str
    severity_band: str
    ac_stable_seconds: float | str
    age_seconds: float | str
    freshness: str


@dataclass(frozen=True)
class ThermalSituation:
    level: str
    maximum_millidegree_c: int | str
    sustained_seconds: float | str
    trend: str
    recent_transitions: tuple[str, ...]
    age_seconds: float | str
    freshness: str


@dataclass(frozen=True)
class SessionSituation:
    locked: bool | str
    lock_dwell_seconds: float | str
    idle_seconds: float | str
    recent_input_seconds: float | str
    inhibitors: tuple[str, ...]
    age_seconds: float | str
    freshness: str


@dataclass(frozen=True)
class WorkloadSituation:
    fullscreen: bool | str
    probable_gaming: bool | str
    probable_compile: bool | str
    probable_rendering: bool | str
    probable_media: bool | str
    interactive: bool | str
    high_background_cpu: bool | str
    gpu_activity: bool | str
    confidence: float | str
    evidence: tuple[str, ...]
    age_seconds: float | str
    freshness: str


@dataclass(frozen=True)
class NetworkSituation:
    connectivity: str
    default_route: bool | str
    reachable: bool | str
    stability: str
    metered: bool | str
    recent_transition: str
    stability_seconds: float | str
    age_seconds: float | str
    freshness: str


@dataclass(frozen=True)
class MaintenanceSituation:
    transaction_state: str
    pending: bool | str
    staged: bool | str
    prepared: bool | str
    recovery_prerequisites: bool | str
    in_critical_section: bool | str
    interruption_safe: bool | str
    enough_disk: bool | str
    age_seconds: float | str
    freshness: str


@dataclass(frozen=True)
class GuardianSituation:
    active_incident: bool | str
    severity_level: int | str
    recovery_in_progress: bool | str
    unresolved_reliability: bool | str
    age_seconds: float | str
    freshness: str


@dataclass(frozen=True)
class UserIntentSituation:
    power_mode: str
    adaptation_opt_outs: tuple[str, ...]
    dnd: bool | str
    explicit_maintenance: bool | str
    foreground_performance: bool | str
    age_seconds: float | str
    freshness: str


@dataclass(frozen=True)
class AdaptivePostureSituation:
    active_leases: tuple[str, ...]
    effective_posture: tuple[tuple[str, str], ...]
    oldest_lease_age_seconds: float | str
    source_policies: tuple[str, ...]


@dataclass(frozen=True)
class SituationSnapshot:
    schema_version: int
    snapshot_id: str
    time: TimeSituation
    power: PowerSituation
    thermal: ThermalSituation
    session: SessionSituation
    workload: WorkloadSituation
    network: NetworkSituation
    maintenance: MaintenanceSituation
    guardian: GuardianSituation
    user_intent: UserIntentSituation
    adaptive_posture: AdaptivePostureSituation

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _power(data: Mapping[str, Any], age: float | str, freshness: str) -> PowerSituation:
    supplies = data.get("supplies") if isinstance(data.get("supplies"), list) else []
    batteries = [x for x in supplies if isinstance(x, Mapping) and x.get("type") == "Battery"]
    external = [x for x in supplies if isinstance(x, Mapping) and x.get("type") != "Battery"]
    battery = batteries[0] if batteries else {}
    ac_values = [x.get("online") for x in external if isinstance(x.get("online"), bool)]
    ac_online: bool | str = any(ac_values) if ac_values else _bool(data.get("ac_online"))
    if battery:
        battery_present: bool | str = _bool(battery.get("present"))
        if battery_present == UNKNOWN:
            battery_present = True
    else:
        battery_present = _bool(data.get("battery_present"))
    percentage_raw = battery.get("capacity_percent", data.get("percentage"))
    percentage_num = _number(percentage_raw, low=0, high=100)
    percentage: int | str = int(percentage_num) if percentage_num != UNKNOWN else UNKNOWN
    status = _text(battery.get("status", data.get("charging_state")))
    status_lower = status.lower() if status != UNKNOWN else UNKNOWN
    trend = _text(data.get("drain_trend"), {"rising", "stable", "falling", "rapid-fall"})
    severity = UNKNOWN
    if percentage != UNKNOWN:
        p = int(percentage)
        if ac_online is True or status_lower in {"charging", "full"}:
            severity = "NORMAL"
        elif p < 10:
            severity = "CRITICAL"
        elif p < 20:
            severity = "CONSERVING"
        elif p < 40:
            severity = "LOW"
        else:
            severity = "NORMAL"
    return PowerSituation(ac_online, battery_present, percentage, status_lower, trend, severity, _number(data.get("ac_stable_seconds"), low=0), age, freshness)


def _thermal(data: Mapping[str, Any], age: float | str, freshness: str) -> ThermalSituation:
    maximum = _number(data.get("max_millidegree_c"), low=-100000, high=250000)
    if maximum == UNKNOWN:
        maximum_i: int | str = UNKNOWN
        level = _text(data.get("level"), {"normal", "warm", "hot", "critical"})
    else:
        maximum_i = int(maximum)
        level = "critical" if maximum_i >= 95000 else "hot" if maximum_i >= 85000 else "warm" if maximum_i >= 75000 else "normal"
    return ThermalSituation(
        level,
        maximum_i,
        _number(data.get("sustained_seconds"), low=0),
        _text(data.get("trend"), {"rising", "stable", "falling"}),
        _strings(data.get("recent_transitions")),
        age,
        freshness,
    )


def _session(data: Mapping[str, Any], age: float | str, freshness: str) -> SessionSituation:
    return SessionSituation(
        _bool(data.get("locked")),
        _number(data.get("lock_dwell_seconds"), low=0),
        _number(data.get("idle_seconds"), low=0),
        _number(data.get("recent_input_seconds"), low=0),
        _strings(data.get("inhibitors")),
        age,
        freshness,
    )


def _workload(data: Mapping[str, Any], age: float | str, freshness: str) -> WorkloadSituation:
    confidence = _number(data.get("confidence"), low=0, high=1)
    return WorkloadSituation(
        _bool(data.get("fullscreen")),
        _bool(data.get("probable_gaming")),
        _bool(data.get("probable_compile")),
        _bool(data.get("probable_rendering")),
        _bool(data.get("probable_media")),
        _bool(data.get("interactive")),
        _bool(data.get("high_background_cpu")),
        _bool(data.get("gpu_activity")),
        float(confidence) if confidence != UNKNOWN else UNKNOWN,
        _strings(data.get("evidence")),
        age,
        freshness,
    )


def _network(data: Mapping[str, Any], age: float | str, freshness: str) -> NetworkSituation:
    return NetworkSituation(
        _text(data.get("connectivity"), {"online", "limited", "offline"}),
        _bool(data.get("default_route")),
        _bool(data.get("reachable")),
        _text(data.get("stability"), {"stable", "unstable"}),
        _bool(data.get("metered")),
        _text(data.get("recent_transition")),
        _number(data.get("stability_seconds"), low=0),
        age,
        freshness,
    )


def _maintenance(data: Mapping[str, Any], age: float | str, freshness: str) -> MaintenanceSituation:
    return MaintenanceSituation(
        _text(data.get("transaction_state")),
        _bool(data.get("pending")),
        _bool(data.get("staged")),
        _bool(data.get("prepared")),
        _bool(data.get("recovery_prerequisites")),
        _bool(data.get("in_critical_section")),
        _bool(data.get("interruption_safe")),
        _bool(data.get("enough_disk")),
        age,
        freshness,
    )


def _guardian(data: Mapping[str, Any], age: float | str, freshness: str) -> GuardianSituation:
    severity = _number(data.get("severity_level"), low=0, high=4)
    return GuardianSituation(
        _bool(data.get("active_incident")),
        int(severity) if severity != UNKNOWN else UNKNOWN,
        _bool(data.get("recovery_in_progress")),
        _bool(data.get("unresolved_reliability")),
        age,
        freshness,
    )


def _intent(data: Mapping[str, Any], age: float | str, freshness: str) -> UserIntentSituation:
    return UserIntentSituation(
        _text(data.get("power_mode"), {"balanced", "performance", "powersave"}),
        _strings(data.get("adaptation_opt_outs")),
        _bool(data.get("dnd")),
        _bool(data.get("explicit_maintenance")),
        _bool(data.get("foreground_performance")),
        age,
        freshness,
    )


def _posture(data: Mapping[str, Any]) -> AdaptivePostureSituation:
    raw = data.get("effective_posture")
    posture: list[tuple[str, str]] = []
    if isinstance(raw, Mapping):
        for key, value in sorted(raw.items()):
            if isinstance(key, str) and isinstance(value, str):
                posture.append((key, value))
    return AdaptivePostureSituation(
        _strings(data.get("active_leases")),
        tuple(posture),
        _number(data.get("oldest_lease_age_seconds"), low=0),
        _strings(data.get("source_policies")),
    )


def build_situation(observations: Mapping[str, Any], *, captured_at: datetime | None = None) -> SituationSnapshot:
    """Build one immutable situation from independently optional observations."""
    captured = (captured_at or _utc_now()).astimezone(timezone.utc)
    built: dict[str, Any] = {}
    ages: list[float] = []
    for domain, factory in (
        ("power", _power),
        ("thermal", _thermal),
        ("session", _session),
        ("workload", _workload),
        ("network", _network),
        ("maintenance", _maintenance),
        ("guardian", _guardian),
        ("user_intent", _intent),
    ):
        data, age, freshness = _envelope(observations, domain, captured)
        built[domain] = factory(data, age, freshness)
        if age != UNKNOWN:
            ages.append(float(age))
    session_age = built["session"].lock_dwell_seconds if built["session"].locked is True else UNKNOWN
    time = TimeSituation(_stamp(captured), max(ages) if ages else UNKNOWN, session_age)
    posture = _posture(_mapping(observations.get("adaptive_posture")))
    payload = {
        "schema_version": 1,
        "time": asdict(time),
        **{name: asdict(value) for name, value in built.items()},
        "adaptive_posture": asdict(posture),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    snapshot_id = "sit-" + hashlib.sha256(canonical).hexdigest()[:20]
    return SituationSnapshot(
        1,
        snapshot_id,
        time,
        built["power"],
        built["thermal"],
        built["session"],
        built["workload"],
        built["network"],
        built["maintenance"],
        built["guardian"],
        built["user_intent"],
        posture,
    )
