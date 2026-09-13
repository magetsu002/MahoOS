#!/usr/bin/env python3
"""Strict declarative adaptation proposal schema.

Policies describe desired effects. They cannot carry shell commands, adapter
paths, package-manager invocations, or other execution authority.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1

PRIORITY_ORDER = {
    "hardware-data-safety": 900,
    "explicit-user-intent": 800,
    "foreground-task-continuity": 700,
    "reliability-recovery": 600,
    "thermal-protection": 500,
    "battery-survival": 400,
    "maintenance": 300,
    "background-efficiency": 200,
    "cosmetics": 100,
}

DISRUPTION_ORDER = {"A": 1, "B": 2, "C": 3, "D": 4}

# Effect vocabulary is intentionally narrow. Adding an effect is an authority
# review because policies must never smuggle commands through arbitrary keys.
EFFECT_VALUES: dict[str, frozenset[str]] = {
    "maintenance": frozenset({"suspended", "eligible", "unchanged"}),
    "background_work": frozenset({"reduced", "normal", "suspended", "unchanged"}),
    "foreground_performance": frozenset({"preserve", "balanced", "unchanged"}),
    "notifications": frozenset({"quiet", "normal", "defer-noncritical", "unchanged"}),
    "update_downloads": frozenset({"deferred", "allowed", "unchanged"}),
    "network_background": frozenset({"suspended", "normal", "reduced", "unchanged"}),
    "visual_cost": frozenset({"reduced", "normal", "unchanged"}),
    "power_survival": frozenset({"conserve", "normal", "critical-review", "unchanged"}),
    "thermal_protection": frozenset({"elevated", "normal", "critical-review", "unchanged"}),
    "display_brightness": frozenset({"lower", "normal", "unchanged"}),
    "performance_mode": frozenset({"conservative", "balanced", "performance", "unchanged"}),
    "foreground_network": frozenset({"preserve", "normal", "unchanged"}),
    "power_action": frozenset({"none", "suspend-review", "shutdown-review", "reboot-review"}),
}

_ALLOWED_FIELDS = {
    "schema_version", "proposal_id", "source_policy", "policy_version",
    "situation_snapshot_id", "created_at", "priority_domain", "disruption_class",
    "confidence", "reason", "supporting_evidence", "requested_effects",
    "prohibited_effects", "minimum_dwell_seconds", "expiry_condition",
    "cooldown_seconds", "minimum_residency_seconds", "reversibility",
    "user_override_behavior", "notification_policy", "verification_requirement",
    "failure_behavior",
}
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_POLICY_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}$")
_SNAPSHOT = re.compile(r"^sit-[0-9a-f]{20}$")
_PROPOSAL = re.compile(r"^prop-[0-9a-f]{20}$")


@dataclass(frozen=True, order=True)
class Effect:
    key: str
    value: str


@dataclass(frozen=True)
class ExpiryCondition:
    kind: str
    value: str | int | None = None


@dataclass(frozen=True)
class AdaptationProposal:
    schema_version: int
    proposal_id: str
    source_policy: str
    policy_version: str
    situation_snapshot_id: str
    created_at: str
    priority_domain: str
    disruption_class: str
    confidence: float
    reason: str
    supporting_evidence: tuple[str, ...]
    requested_effects: tuple[Effect, ...]
    prohibited_effects: tuple[Effect, ...]
    minimum_dwell_seconds: int
    expiry_condition: ExpiryCondition
    cooldown_seconds: int
    minimum_residency_seconds: int
    reversibility: bool
    user_override_behavior: str
    notification_policy: str
    verification_requirement: str
    failure_behavior: str

    @property
    def priority(self) -> int:
        return PRIORITY_ORDER[self.priority_domain]

    @property
    def automatic_execution_eligible(self) -> bool:
        # A1-A14 has no new real adaptive execution. This property only records
        # future eligibility semantics; Class C/D are never automatic here.
        return False

    @property
    def shadow_eligible(self) -> bool:
        return self.disruption_class in {"A", "B"}

    @property
    def requires_human_review(self) -> bool:
        return self.disruption_class in {"C", "D"}

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["requested_effects"] = [asdict(effect) for effect in self.requested_effects]
        data["prohibited_effects"] = [asdict(effect) for effect in self.prohibited_effects]
        return data


def _stamp(value: datetime | None = None) -> str:
    now = (value or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return now.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _effects(value: Any, name: str) -> tuple[Effect, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list")
    effects: list[Effect] = []
    seen: set[str] = set()
    for raw in value:
        if isinstance(raw, Effect):
            effect = raw
        elif isinstance(raw, Mapping) and set(raw) == {"key", "value"}:
            effect = Effect(str(raw["key"]), str(raw["value"]))
        else:
            raise ValueError(f"{name} entries must contain only key/value")
        allowed = EFFECT_VALUES.get(effect.key)
        if allowed is None:
            raise ValueError(f"unknown adaptation effect: {effect.key}")
        if effect.value not in allowed:
            raise ValueError(f"invalid value for adaptation effect {effect.key}: {effect.value}")
        if effect.key in seen:
            raise ValueError(f"duplicate adaptation effect: {effect.key}")
        seen.add(effect.key)
        effects.append(effect)
    return tuple(sorted(effects))


def _expiry(value: Any) -> ExpiryCondition:
    if isinstance(value, ExpiryCondition):
        condition = value
    elif isinstance(value, Mapping) and set(value).issubset({"kind", "value"}) and "kind" in value:
        condition = ExpiryCondition(str(value["kind"]), value.get("value"))
    else:
        raise ValueError("expiry_condition must be a declarative predicate")
    if condition.kind not in {"condition-clears", "elapsed-seconds", "snapshot-changes", "manual"}:
        raise ValueError("unsupported expiry condition")
    if condition.kind == "elapsed-seconds":
        if isinstance(condition.value, bool) or not isinstance(condition.value, int) or condition.value <= 0:
            raise ValueError("elapsed expiry requires positive integer seconds")
    elif condition.value is not None and not isinstance(condition.value, str):
        raise ValueError("expiry condition value must be text or null")
    return condition


def _evidence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("supporting_evidence must be a list")
    result = tuple(item for item in value if isinstance(item, str) and item)
    if len(result) != len(value) or len(set(result)) != len(result):
        raise ValueError("supporting_evidence must contain unique non-empty strings")
    return result


def _positive_or_zero(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _validate_common(data: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(data) - _ALLOWED_FIELDS
    missing = _ALLOWED_FIELDS - set(data)
    if unknown:
        raise ValueError(f"unknown proposal fields: {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"missing proposal fields: {', '.join(sorted(missing))}")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported adaptation proposal schema")
    source = data.get("source_policy")
    if not isinstance(source, str) or _NAME.fullmatch(source) is None:
        raise ValueError("invalid source policy")
    version = data.get("policy_version")
    if not isinstance(version, str) or _POLICY_VERSION.fullmatch(version) is None:
        raise ValueError("invalid policy version")
    snapshot = data.get("situation_snapshot_id")
    if not isinstance(snapshot, str) or _SNAPSHOT.fullmatch(snapshot) is None:
        raise ValueError("invalid situation snapshot identity")
    created = data.get("created_at")
    if not isinstance(created, str) or not created.endswith("Z"):
        raise ValueError("proposal created_at must be UTC")
    priority = data.get("priority_domain")
    if priority not in PRIORITY_ORDER:
        raise ValueError("invalid priority domain")
    disruption = data.get("disruption_class")
    if disruption not in DISRUPTION_ORDER:
        raise ValueError("invalid disruption class")
    confidence = data.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("proposal confidence must be between zero and one")
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("proposal reason is required")
    if data.get("user_override_behavior") not in {"respect", "safety-may-override"}:
        raise ValueError("invalid user override behavior")
    if data.get("notification_policy") not in {"none", "passive", "action-required", "critical"}:
        raise ValueError("invalid notification policy")
    if data.get("verification_requirement") not in {"none", "observe", "required"}:
        raise ValueError("invalid verification requirement")
    if data.get("failure_behavior") not in {"preserve-current", "drop-proposal", "human-review"}:
        raise ValueError("invalid failure behavior")
    if not isinstance(data.get("reversibility"), bool):
        raise ValueError("reversibility must be boolean")
    requested = _effects(data.get("requested_effects"), "requested_effects")
    prohibited = _effects(data.get("prohibited_effects"), "prohibited_effects")
    overlap = {e.key for e in requested} & {e.key for e in prohibited}
    if overlap:
        raise ValueError(f"effect cannot be both requested and prohibited: {', '.join(sorted(overlap))}")
    normalized = dict(data)
    normalized["confidence"] = float(confidence)
    normalized["supporting_evidence"] = _evidence(data.get("supporting_evidence"))
    normalized["requested_effects"] = requested
    normalized["prohibited_effects"] = prohibited
    normalized["minimum_dwell_seconds"] = _positive_or_zero(data.get("minimum_dwell_seconds"), "minimum_dwell_seconds")
    normalized["expiry_condition"] = _expiry(data.get("expiry_condition"))
    normalized["cooldown_seconds"] = _positive_or_zero(data.get("cooldown_seconds"), "cooldown_seconds")
    normalized["minimum_residency_seconds"] = _positive_or_zero(data.get("minimum_residency_seconds"), "minimum_residency_seconds")
    return normalized


def validate_proposal(payload: Mapping[str, Any]) -> AdaptationProposal:
    data = _validate_common(payload)
    proposal_id = data.get("proposal_id")
    if not isinstance(proposal_id, str) or _PROPOSAL.fullmatch(proposal_id) is None:
        raise ValueError("invalid proposal identity")
    return AdaptationProposal(**data)


def create_proposal(
    *,
    source_policy: str,
    policy_version: str,
    situation_snapshot_id: str,
    priority_domain: str,
    disruption_class: str,
    confidence: float,
    reason: str,
    supporting_evidence: Iterable[str],
    requested_effects: Iterable[Effect | Mapping[str, str]],
    prohibited_effects: Iterable[Effect | Mapping[str, str]] = (),
    minimum_dwell_seconds: int = 0,
    expiry_condition: ExpiryCondition = ExpiryCondition("condition-clears"),
    cooldown_seconds: int = 0,
    minimum_residency_seconds: int = 0,
    reversibility: bool = True,
    user_override_behavior: str = "respect",
    notification_policy: str = "none",
    verification_requirement: str = "observe",
    failure_behavior: str = "preserve-current",
    created_at: datetime | None = None,
) -> AdaptationProposal:
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": "prop-" + "0" * 20,
        "source_policy": source_policy,
        "policy_version": policy_version,
        "situation_snapshot_id": situation_snapshot_id,
        "created_at": _stamp(created_at),
        "priority_domain": priority_domain,
        "disruption_class": disruption_class,
        "confidence": confidence,
        "reason": reason,
        "supporting_evidence": list(supporting_evidence),
        "requested_effects": list(requested_effects),
        "prohibited_effects": list(prohibited_effects),
        "minimum_dwell_seconds": minimum_dwell_seconds,
        "expiry_condition": expiry_condition,
        "cooldown_seconds": cooldown_seconds,
        "minimum_residency_seconds": minimum_residency_seconds,
        "reversibility": reversibility,
        "user_override_behavior": user_override_behavior,
        "notification_policy": notification_policy,
        "verification_requirement": verification_requirement,
        "failure_behavior": failure_behavior,
    }
    checked = _validate_common(base)
    canonical = dict(checked)
    canonical["proposal_id"] = None
    canonical["requested_effects"] = [asdict(e) for e in checked["requested_effects"]]
    canonical["prohibited_effects"] = [asdict(e) for e in checked["prohibited_effects"]]
    canonical["expiry_condition"] = asdict(checked["expiry_condition"])
    proposal_id = "prop-" + hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]
    checked["proposal_id"] = proposal_id
    return AdaptationProposal(**checked)


def proposal_from_dict(payload: Mapping[str, Any]) -> AdaptationProposal:
    """Strict deserialize. Unknown fields and effect keys fail closed."""
    return validate_proposal(payload)
