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


SCHEMA_VERSION = 2


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
        "Quiet noncritical notifications during games/fullscreen media",
        "Focus",
        "Controls only Maho's certified noncritical notification presentation; explicit DND remains separate.",
    ),
    PreferenceSpec(
        "focus.pause_maintenance_gaming",
        "Pause optional maintenance while gaming",
        "Focus",
        "Prevents optional Maho maintenance from competing with a detected game.",
    ),
    PreferenceSpec(
        "focus.pause_maintenance_interactive",
        "Pause optional maintenance during focused interactive work",
        "Focus",
        "Protects high-confidence foreground interactive work without changing the application itself.",
    ),
    PreferenceSpec(
        "focus.pause_maintenance_builds",
        "Pause optional maintenance during sustained builds",
        "Focus",
        "Keeps optional maintenance out of the way while a sustained compile/build is detected.",
    ),
    PreferenceSpec(
        "focus.pause_maintenance_rendering",
        "Pause optional maintenance during rendering/encoding",
        "Focus",
        "Keeps optional maintenance out of the way while sustained rendering or encoding is detected.",
    ),
    PreferenceSpec(
        "power.pause_maintenance_low_battery",
        "Pause optional maintenance on low battery",
        "Power",
        "Controls only the certified maintenance veto; unrelated battery policy stays non-executable unless separately certified.",
    ),
    PreferenceSpec(
        "thermal.pause_maintenance_hot",
        "Pause optional maintenance under sustained heat",
        "Thermals",
        "Controls convenience maintenance deferral, never independent hardware/data-safety authority.",
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
    version = payload.get("schema_version")
    if version not in {1, SCHEMA_VERSION}:
        return BehaviorPreferences(defaults().values, ("unsupported_schema",))
    raw = payload.get("preferences")
    if not isinstance(raw, Mapping):
        return BehaviorPreferences(defaults().values, ("preferences_not_an_object",))

    # V1 exposed one broad "heavy work" switch. V2 keeps the user's choice but
    # splits it into interactive/build/rendering intentions so Behavior is
    # actually customizable rather than a collection of broad implementation
    # buckets.
    legacy_heavy = raw.get("focus.pause_maintenance_heavy_work", True)
    if version == 1 and not isinstance(legacy_heavy, bool):
        issues.append("invalid_boolean:focus.pause_maintenance_heavy_work")
        legacy_heavy = True

    values: dict[str, bool] = {}
    for spec in SPECS:
        if version == 1 and spec.key in {
            "focus.pause_maintenance_interactive",
            "focus.pause_maintenance_builds",
            "focus.pause_maintenance_rendering",
        }:
            value = raw.get(spec.key, legacy_heavy)
        else:
            value = raw.get(spec.key, spec.default)
        if not isinstance(value, bool):
            issues.append(f"invalid_boolean:{spec.key}")
            value = spec.default
        values[spec.key] = value

    known = set(SPEC_BY_KEY)
    if version == 1:
        known.add("focus.pause_maintenance_heavy_work")
    unknown = tuple(sorted(key for key in raw if isinstance(key, str) and key not in known))
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
            if isinstance(loaded, dict) and loaded.get("schema_version") in {1, SCHEMA_VERSION}:
                raw = loaded
        except (OSError, UnicodeError, json.JSONDecodeError):
            raw = {}
    preferences = raw.get("preferences")
    preserved = dict(preferences) if isinstance(preferences, Mapping) else {}
    if raw.get("schema_version") == 1:
        legacy_heavy = preserved.pop("focus.pause_maintenance_heavy_work", True)
        if not isinstance(legacy_heavy, bool):
            legacy_heavy = True
        for migrated_key in (
            "focus.pause_maintenance_interactive",
            "focus.pause_maintenance_builds",
            "focus.pause_maintenance_rendering",
        ):
            preserved.setdefault(migrated_key, legacy_heavy)
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
            elif effect.key == "maintenance" and proposal.source_policy == "workload.interactive":
                pref = "focus.pause_maintenance_interactive"
            elif effect.key == "maintenance" and proposal.source_policy == "compile.sustained":
                pref = "focus.pause_maintenance_builds"
            elif effect.key == "maintenance" and proposal.source_policy == "render.sustained":
                pref = "focus.pause_maintenance_rendering"
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
