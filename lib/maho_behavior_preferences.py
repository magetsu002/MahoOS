#!/usr/bin/env python3
"""User-owned restrictions for already-certified Maho convenience behavior."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from maho_adaptive_proposal import AdaptationProposal, Effect, create_proposal


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PreferenceSpec:
    key: str
    label: str
    group: str
    description: str
    default: bool = True


SPECS = (
    PreferenceSpec(
        "focus.quiet_notifications",
        "Quiet noncritical notifications while gaming",
        "Focus",
        "Restricts the certified notification presentation effect only.",
    ),
    PreferenceSpec(
        "focus.pause_maintenance_gaming",
        "Pause optional maintenance while gaming",
        "Focus",
        "Restricts the certified maintenance veto from the gaming policy.",
    ),
    PreferenceSpec(
        "focus.pause_maintenance_heavy_work",
        "Pause optional maintenance during heavy work",
        "Focus",
        "Applies to interactive, compile, and rendering context policies.",
    ),
    PreferenceSpec(
        "power.pause_maintenance_low_battery",
        "Pause optional maintenance on low battery",
        "Power",
        "Restricts only the maintenance effect; other policy remains non-executable unless certified elsewhere.",
    ),
    PreferenceSpec(
        "thermal.pause_maintenance_hot",
        "Pause optional maintenance under sustained heat",
        "Thermals",
        "Does not suppress a separate hardware or recovery safety authority.",
    ),
)
SPEC_BY_KEY = {item.key: item for item in SPECS}


@dataclass(frozen=True)
class BehaviorPreferences:
    values: Mapping[str, bool]
    issues: tuple[str, ...] = ()
    unknown_keys: tuple[str, ...] = ()

    def enabled(self, key: str) -> bool:
        spec = SPEC_BY_KEY[key]
        return self.values.get(key, spec.default) is True

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "class": "user-configurable-convenience",
            "preferences": {key: self.enabled(key) for key in SPEC_BY_KEY},
            "issues": list(self.issues),
            "unknown_keys": list(self.unknown_keys),
            "authority": False,
        }


def default_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "maho" / "behavior.json"


def defaults() -> BehaviorPreferences:
    return BehaviorPreferences({item.key: item.default for item in SPECS})


def parse_preferences(payload: Mapping[str, Any]) -> BehaviorPreferences:
    issues: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        return BehaviorPreferences(defaults().values, ("unsupported_schema",))
    raw = payload.get("preferences")
    if not isinstance(raw, Mapping):
        return BehaviorPreferences(defaults().values, ("preferences_not_an_object",))
    values: dict[str, bool] = {}
    for spec in SPECS:
        value = raw.get(spec.key, spec.default)
        if not isinstance(value, bool):
            issues.append(f"invalid_boolean:{spec.key}")
            value = spec.default
        values[spec.key] = value
    unknown = tuple(sorted(key for key in raw if isinstance(key, str) and key not in SPEC_BY_KEY))
    return BehaviorPreferences(values, tuple(issues), unknown)


def load_preferences(path: Path | None = None) -> BehaviorPreferences:
    source = path or default_path()
    if not source.exists():
        return defaults()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return BehaviorPreferences(defaults().values, ("preferences_unreadable",))
    if not isinstance(payload, Mapping):
        return BehaviorPreferences(defaults().values, ("preferences_not_an_object",))
    return parse_preferences(payload)


def write_preference(key: str, value: bool, path: Path | None = None) -> BehaviorPreferences:
    if key not in SPEC_BY_KEY:
        raise ValueError("unknown behavior preference")
    if not isinstance(value, bool):
        raise ValueError("behavior preference must be boolean")
    destination = path or default_path()
    raw: dict[str, Any] = {}
    if destination.exists():
        try:
            loaded = json.loads(destination.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and loaded.get("schema_version") == SCHEMA_VERSION:
                raw = loaded
        except (OSError, UnicodeError, json.JSONDecodeError):
            raw = {}
    preferences = raw.get("preferences")
    preserved = dict(preferences) if isinstance(preferences, Mapping) else {}
    preserved[key] = value
    raw.update({"schema_version": SCHEMA_VERSION, "preferences": preserved})
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(destination.parent, 0o700)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(raw, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return load_preferences(destination)


def _created_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _restricted(proposal: AdaptationProposal, effects: tuple[Effect, ...]) -> AdaptationProposal | None:
    if effects == proposal.requested_effects:
        return proposal
    if not effects:
        return None
    return create_proposal(
        source_policy=proposal.source_policy,
        policy_version=proposal.policy_version,
        situation_snapshot_id=proposal.situation_snapshot_id,
        priority_domain=proposal.priority_domain,
        disruption_class=proposal.disruption_class,
        confidence=proposal.confidence,
        reason=proposal.reason,
        supporting_evidence=proposal.supporting_evidence,
        requested_effects=effects,
        prohibited_effects=proposal.prohibited_effects,
        minimum_dwell_seconds=proposal.minimum_dwell_seconds,
        expiry_condition=proposal.expiry_condition,
        cooldown_seconds=proposal.cooldown_seconds,
        minimum_residency_seconds=proposal.minimum_residency_seconds,
        reversibility=proposal.reversibility,
        user_override_behavior=proposal.user_override_behavior,
        notification_policy=proposal.notification_policy,
        verification_requirement=proposal.verification_requirement,
        failure_behavior=proposal.failure_behavior,
        created_at=_created_at(proposal.created_at),
    )


def apply_preferences(
    proposals: Iterable[AdaptationProposal], preferences: BehaviorPreferences,
) -> tuple[AdaptationProposal, ...]:
    """Remove convenience effects only; safety/recovery proposals bypass this layer."""
    result: list[AdaptationProposal] = []
    for proposal in proposals:
        # Guardian/reliability coordination is a separate safety class and can
        # never be disabled by this user convenience registry.
        if proposal.priority_domain in {"hardware-data-safety", "reliability-recovery"}:
            result.append(proposal)
            continue
        retained: list[Effect] = []
        for effect in proposal.requested_effects:
            pref: str | None = None
            if effect.key == "notifications" and proposal.source_policy in {
                "gaming.foreground", "media.fullscreen", "notification.foreground-context",
            }:
                pref = "focus.quiet_notifications"
            elif effect.key == "maintenance" and proposal.source_policy == "gaming.foreground":
                pref = "focus.pause_maintenance_gaming"
            elif effect.key == "maintenance" and proposal.source_policy in {
                "workload.interactive", "compile.sustained", "render.sustained",
            }:
                pref = "focus.pause_maintenance_heavy_work"
            elif effect.key == "maintenance" and proposal.source_policy.startswith("battery."):
                pref = "power.pause_maintenance_low_battery"
            elif effect.key == "maintenance" and proposal.source_policy.startswith("thermal."):
                pref = "thermal.pause_maintenance_hot"
            if pref is None or preferences.enabled(pref):
                retained.append(effect)
        narrowed = _restricted(proposal, tuple(retained))
        if narrowed is not None:
            result.append(narrowed)
    return tuple(result)
