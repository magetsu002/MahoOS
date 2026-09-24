#!/usr/bin/env python3
"""Read-only, structured status model for the Maho System interface.

Subsystem payloads remain authoritative.  This module only translates their
existing contracts into one bounded vocabulary for presentation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from guardian_completion_status import enrich_status
from guardian_live_state import LivePaths, live_status
from guardian_trust_status import DEFAULT_RUNTIME_CAMPAIGN_ROOT, status_payload as recovery_status
from maho_adaptive_shadow import current_status as behavior_status
from maho_adaptive_shadow import doctor_report as behavior_doctor
from maho_adaptive_shadow import repo_root, state_root as behavior_state_root
from maho_behavior_preferences import BehaviorPreferences, load_preferences
from maho_update_cli import status_payload as update_status
from maho_login_diagnostic import collect_login_diagnostic


DIAGNOSTIC_STATES = frozenset({"PASS", "WARN", "FAIL", "UNKNOWN", "BLOCKED"})


@dataclass(frozen=True)
class DiagnosticRecord:
    id: str
    subsystem: str
    state: str
    summary: str
    reason: str
    evidence_refs: tuple[str, ...]
    recommended_action: str
    attention: bool

    def __post_init__(self) -> None:
        if self.state not in DIAGNOSTIC_STATES:
            raise ValueError("invalid diagnostic state")


@dataclass(frozen=True)
class SystemSummary:
    operational_health: str
    trust: str
    guardian_health: str
    severity: str
    attention: str
    recovery: str
    updates: str
    behavior: str


@dataclass(frozen=True)
class EvidenceEvent:
    source: str
    at: str | None
    label: str
    state: str
    reference: str | None = None


@dataclass(frozen=True)
class SystemModel:
    summary: SystemSummary
    diagnostics: tuple[DiagnosticRecord, ...]
    events: tuple[EvidenceEvent, ...]
    guardian: Mapping[str, Any]
    update: Mapping[str, Any]
    behavior: Mapping[str, Any]
    behavior_doctor: Mapping[str, Any]
    recovery: Mapping[str, Any]
    login: Mapping[str, Any]
    preferences: BehaviorPreferences
    collection_errors: tuple[str, ...] = ()

    def as_dict(self, *, include_evidence: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": 1,
            "summary": asdict(self.summary),
            "diagnostics": [asdict(item) for item in self.diagnostics],
            "events": [asdict(item) for item in self.events],
            "behavior_preferences": self.preferences.as_dict(),
            "collection_errors": list(self.collection_errors),
        }
        if include_evidence:
            result["evidence"] = {
                "guardian": dict(self.guardian),
                "update": dict(self.update),
                "behavior": dict(self.behavior),
                "behavior_doctor": dict(self.behavior_doctor),
                "recovery": dict(self.recovery),
                "login": dict(self.login),
            }
        return result


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> Sequence[Mapping[str, Any]]:
    if not isinstance(value, list):
        return ()
    return tuple(row for row in value if isinstance(row, Mapping))


def _world_guardian(guardian: Mapping[str, Any]) -> Mapping[str, Any]:
    return _object(_object(guardian.get("world_state")).get("guardian"))


def _trust_label(value: Any) -> str:
    return {
        "VERIFIED": "VERIFIED",
        "HEALTHY": "VERIFIED",
        "DEGRADED": "UNRESOLVED",
        "UNKNOWN": "UNRESOLVED",
        "UNTRUSTED": "UNTRUSTED",
        "REVOKED": "UNTRUSTED",
        "CONTAMINATED": "UNTRUSTED",
    }.get(str(value).upper(), "UNRESOLVED")


def _diag(
    id: str, subsystem: str, state: str, summary: str, reason: str,
    refs: Sequence[str], action: str, *, attention: bool | None = None,
) -> DiagnosticRecord:
    return DiagnosticRecord(
        id=id, subsystem=subsystem, state=state, summary=summary, reason=reason,
        evidence_refs=tuple(refs), recommended_action=action,
        attention=(state != "PASS") if attention is None else attention,
    )


def _diagnostics(
    guardian: Mapping[str, Any], update: Mapping[str, Any], behavior: Mapping[str, Any],
    adaptive_doctor: Mapping[str, Any], recovery: Mapping[str, Any],
    preferences: BehaviorPreferences, collection_errors: Sequence[str],
    login: Mapping[str, Any] | None = None,
) -> tuple[DiagnosticRecord, ...]:
    records: list[DiagnosticRecord] = []
    world_guardian = _world_guardian(guardian)
    system = _object(guardian.get("system"))
    runtime = _object(system.get("maho_runtime"))
    runtime_ok = runtime.get("verified") is True
    records.append(_diag(
        "platform.runtime", "Platform", "PASS" if runtime_ok else "FAIL",
        "Immutable Maho runtime", "Runtime release identity is verified." if runtime_ok else "Runtime release identity is not verified.",
        ("guardian.system.maho_runtime",), "No action required." if runtime_ok else "Restore a verified runtime through the existing runtime recovery path.",
    ))

    reliability = _object(guardian.get("reliability"))
    reliability_state = str(reliability.get("state", "unknown")).lower()
    rel_diag = "PASS" if reliability_state == "healthy" else "WARN" if reliability_state == "degraded" else "UNKNOWN"
    counts = _object(reliability.get("counts"))
    records.append(_diag(
        "platform.reliability", "Platform", rel_diag, "Operational reliability",
        f"Reliability is {reliability_state}; {counts.get('healthy', 0)} healthy, {counts.get('degraded', 0)} degraded, {counts.get('unknown', 0)} unknown findings.",
        ("guardian.reliability",), "Inspect the non-healthy reliability findings." if rel_diag != "PASS" else "No action required.",
    ))

    login = login or {}
    login_state = str(login.get("state", "UNKNOWN")).upper()
    failed_login = login.get("failed_checks") if isinstance(login.get("failed_checks"), list) else []
    login_reason = (
        "Current boot reached an active display manager and instantiated the SDDM greeter after required GPU readiness."
        if login_state == "PASS" else
        "Current boot login evidence is incomplete: " + (", ".join(map(str, failed_login)) or "collector unavailable")
    )
    records.append(_diag(
        "platform.login", "Platform/Login", login_state if login_state in DIAGNOSTIC_STATES else "UNKNOWN",
        "Graphical login contract", login_reason,
        ("login.current_boot",),
        "Inspect current-boot SDDM, seat/VT, runtime, session, and DRM ordering evidence." if login_state != "PASS" else "No action required.",
    ))

    self_health = _object(world_guardian.get("self_health"))
    guardian_state = str(self_health.get("state", "UNKNOWN")).upper()
    guardian_diag = (
        "PASS" if guardian_state == "HEALTHY"
        else "WARN" if guardian_state == "DEGRADED"
        else "FAIL" if guardian_state in {"FAILED", "UNTRUSTED"}
        else "UNKNOWN"
    )
    missing = self_health.get("missing_providers") if isinstance(self_health.get("missing_providers"), list) else []
    stale = self_health.get("stale_providers") if isinstance(self_health.get("stale_providers"), list) else []
    reason = "Guardian has current required evidence." if guardian_diag == "PASS" else (
        f"Guardian judgment is incomplete; missing={','.join(map(str, missing)) or 'none'}, stale={','.join(map(str, stale)) or 'none'}."
    )
    records.append(_diag(
        "guardian.self-health", "Guardian", guardian_diag, "Guardian judgment health", reason,
        ("guardian.world_state.guardian.self_health",), "Restore the named provider evidence, then let Guardian reassess." if guardian_diag != "PASS" else "No action required.",
    ))

    incidents = _rows(guardian.get("active_incidents"))
    severity = _object(world_guardian.get("severity"))
    level = severity.get("level") if isinstance(severity.get("level"), int) else 0
    incident_state = "PASS" if not incidents else "WARN" if level <= 1 else "FAIL"
    records.append(_diag(
        "guardian.incidents", "Guardian", incident_state, "Active incidents",
        "No active Guardian incidents." if not incidents else f"{len(incidents)} active incident(s); current severity is L{level} {severity.get('label', 'unknown')}.",
        tuple(f"guardian.incident:{row.get('incident_id', 'unknown')}" for row in incidents[:8]),
        "Review the incident explanation; do not infer mutation authority from this screen." if incidents else "No action required.",
    ))

    trust = _object(world_guardian.get("trust"))
    trust_state = str(trust.get("state", "UNKNOWN")).upper()
    trust_diag = "PASS" if trust_state == "VERIFIED" else "FAIL" if trust_state in {"UNTRUSTED", "REVOKED", "CONTAMINATED"} else "UNKNOWN"
    reasons = trust.get("reasons") if isinstance(trust.get("reasons"), list) else []
    records.append(_diag(
        "trust.current-generation", "Trust", trust_diag, "Current-generation trust",
        "; ".join(str(item) for item in reasons[:3]) or "Exact current-generation trust evidence is unavailable.",
        ("guardian.world_state.guardian.trust",), "Establish the missing independent generation and boot evidence." if trust_diag != "PASS" else "No action required.",
    ))
    boot = _object(guardian.get("boot"))
    signed = str(boot.get("signed_boot_authority", "UNKNOWN")).upper()
    signed_diag = "PASS" if signed == "VERIFIED" else "FAIL" if signed in {"UNTRUSTED", "REVOKED"} else "UNKNOWN"
    records.append(_diag(
        "trust.signed-boot", "Trust", signed_diag, "Signed Boot evidence",
        str(boot.get("trust_reason") or "Durable Signed Boot proof is unavailable."),
        ("guardian.boot", "guardian.provider:boot.authority"), "Produce and verify the existing durable Signed Boot postboot proof." if signed_diag != "PASS" else "No action required.",
    ))

    freshness = _object(guardian.get("evidence_freshness"))
    for provider_id, raw in sorted(freshness.items()):
        row = _object(raw)
        fresh = str(row.get("freshness", "unknown"))
        health = str(row.get("health", "unknown"))
        optional = provider_id in {"environment.power", "environment.thermal"}
        if optional and fresh == "missing":
            state = "UNKNOWN"
            summary = f"Optional telemetry {provider_id}"
            reason = "Not available; optional telemetry does not affect primary Guardian health or machine trust."
            action = "No action required."
            attention = False
        else:
            state = "PASS" if fresh == "current" and health == "healthy" else "FAIL" if health == "failed" else "WARN" if fresh == "stale" else "UNKNOWN"
            summary = f"Provider {provider_id}"
            reason = f"Evidence freshness is {fresh}; provider health is {health}."
            action = "Restore current provider evidence." if state != "PASS" else "No action required."
            attention = state in {"FAIL", "WARN"} or provider_id == "boot.authority"
        records.append(_diag(
            f"provider.{provider_id}", "Guardian", state, summary, reason,
            (f"guardian.provider:{provider_id}",), action, attention=attention,
        ))

    update_attention = update.get("attention_required") is True
    blockers = update.get("blockers") if isinstance(update.get("blockers"), list) else []
    update_state = "BLOCKED" if blockers else "WARN" if update_attention else "PASS"
    records.append(_diag(
        "updates.transaction", "Updates", update_state, str(update.get("status") or "Update state unavailable"),
        "; ".join(map(str, blockers)) if blockers else f"Authoritative transaction state is {update.get('authority_state', 'unknown')}.",
        ("update.status",), "Resolve the listed blocker through Maho Update." if blockers else "No action required.",
        attention=update_attention or bool(blockers),
    ))
    certified = update.get("normal_execution_certified") is True
    authority_state = str(update.get("normal_authority_state", "absent"))
    records.append(_diag(
        "updates.execution-authority", "Updates", "PASS" if certified else "WARN",
        "Normal update execution authority", "Current and certified." if certified else f"Normal execution authority is {authority_state}; this does not grant update mutation.",
        ("update.normal_authority",), "Refresh the existing certified update authority before normal execution." if not certified else "No action required.",
    ))

    adaptive_ok = adaptive_doctor.get("healthy") is True
    adaptive_reason = "Certified effects and projections are verified." if adaptive_ok else (
        f"lease={adaptive_doctor.get('lease_state', 'unknown')}, maintenance projection={adaptive_doctor.get('maintenance_projection_state', 'unknown')}."
    )
    records.append(_diag(
        "behavior.engine", "Behavior", "PASS" if adaptive_ok else "WARN", "Behavior engine authority", adaptive_reason,
        ("behavior.doctor",), "Use maho-adaptive doctor to inspect the failed contract." if not adaptive_ok else "No action required.",
    ))
    if behavior:
        blocked = behavior.get("blocked")
        records.append(_diag(
            "behavior.current", "Behavior", "BLOCKED" if blocked else "PASS", "Current automatic behavior",
            str(blocked) if blocked else "Current behavior record is readable and not blocked.",
            ("behavior.current",), "Inspect the blocked lease or actuator evidence." if blocked else "No action required.",
        ))
    else:
        records.append(_diag(
            "behavior.current", "Behavior", "UNKNOWN", "Current automatic behavior",
            "No current Behavior evaluation has been recorded.", ("behavior.current",), "Allow the existing Behavior service to record an evaluation.",
        ))
    records.append(_diag(
        "behavior.preferences", "Behavior", "WARN" if preferences.issues else "PASS", "Behavior preferences",
        "; ".join(preferences.issues) if preferences.issues else "User-owned convenience preferences are valid; safety coordination remains separate.",
        ("behavior.preferences",), "Repair or remove the invalid user preference file." if preferences.issues else "No action required.",
    ))

    invalid = int(recovery.get("invalid_unified_history_records", 0) or 0)
    modes = recovery.get("recovery_modes") if isinstance(recovery.get("recovery_modes"), list) else []
    has_recovery = bool(recovery.get("last_verified_recovery") or recovery.get("last_verified_runtime_recovery"))
    recovery_diag = "FAIL" if invalid else "PASS" if has_recovery else "UNKNOWN"
    records.append(_diag(
        "recovery.readiness", "Recovery", recovery_diag, "Verified recovery evidence",
        f"Verified modes: {', '.join(map(str, modes)) or 'none'}; invalid history records: {invalid}.",
        ("recovery.status",), "Use the existing recovery certification flow; this interface cannot certify recovery." if recovery_diag != "PASS" else "No action required.",
    ))

    for index, error in enumerate(collection_errors):
        records.append(_diag(
            f"collection.{index}", "Platform", "UNKNOWN", "Status collection incomplete", error,
            ("system.collection",), "Inspect the named subsystem directly.",
        ))
    return tuple(records)


def _events(
    guardian: Mapping[str, Any], update: Mapping[str, Any], behavior: Mapping[str, Any],
    recovery: Mapping[str, Any], limit: int = 50,
) -> tuple[EvidenceEvent, ...]:
    events: list[EvidenceEvent] = []
    for row in _rows(guardian.get("recent_activity")):
        kind = str(row.get("kind", "guardian")).title()
        events.append(EvidenceEvent(
            source="Guardian" if kind == "Incident" else kind,
            at=str(row.get("at")) if row.get("at") else None,
            label=f"{kind} {row.get('id') or 'event'}", state=str(row.get("status", "unknown")),
            reference=str(row.get("id")) if row.get("id") else None,
        ))
    receipt = _object(update.get("receipt"))
    if receipt:
        events.append(EvidenceEvent(
            source="Update", at=str(receipt.get("updated_at") or receipt.get("prepared_time") or "") or None,
            label=str(update.get("status") or "Update transaction"), state=str(receipt.get("state", "unknown")),
            reference=str(update.get("transaction_id")) if update.get("transaction_id") else None,
        ))
    if behavior:
        events.append(EvidenceEvent(
            source="Behavior", at=str(behavior.get("captured_at") or "") or None,
            label="Automatic behavior evaluation", state="blocked" if behavior.get("blocked") else "recorded",
            reference=str(behavior.get("snapshot_id")) if behavior.get("snapshot_id") else None,
        ))
    for key in ("last_verified_recovery", "last_verified_runtime_recovery"):
        row = _object(recovery.get(key))
        if row:
            events.append(EvidenceEvent(
                source="Recovery", at=None, label=str(row.get("reason") or "Verified recovery"),
                state="verified" if row.get("valid") is True else "invalid",
                reference=str(row.get("campaign_id")) if row.get("campaign_id") else None,
            ))
    events.sort(key=lambda item: item.at or "", reverse=True)
    return tuple(events[: max(0, min(limit, 200))])


def build_system_model(
    *, guardian: Mapping[str, Any], update: Mapping[str, Any],
    behavior: Mapping[str, Any] | None, adaptive_doctor: Mapping[str, Any],
    recovery: Mapping[str, Any], preferences: BehaviorPreferences,
    collection_errors: Sequence[str] = (), login: Mapping[str, Any] | None = None,
) -> SystemModel:
    behavior_map = behavior or {}
    diagnostics = _diagnostics(
        guardian, update, behavior_map, adaptive_doctor, recovery, preferences, collection_errors, login,
    )
    world_guardian = _world_guardian(guardian)
    reliability_state = str(_object(guardian.get("reliability")).get("state", "unknown")).lower()
    severity = _object(world_guardian.get("severity"))
    severity_level = severity.get("level") if isinstance(severity.get("level"), int) else 0
    if reliability_state == "healthy" and severity_level < 2:
        operational = "HEALTHY"
    elif reliability_state == "unknown":
        operational = "UNKNOWN"
    elif severity_level >= 3:
        operational = "FAILED"
    else:
        operational = "DEGRADED"
    trust_state = _trust_label(_object(world_guardian.get("trust")).get("state"))
    guardian_health = str(_object(world_guardian.get("self_health")).get("state", "UNKNOWN")).upper()
    attention_records = [item for item in diagnostics if item.attention]
    attention = "ACTION REQUIRED" if any(item.state in {"FAIL", "BLOCKED"} for item in attention_records) else "REVIEW" if attention_records else "NONE"
    runtime_recovery = _object(guardian.get("runtime_recovery"))
    runtime_recovery_state = str(runtime_recovery.get("state", "none")).lower()
    recovery_modes = recovery.get("recovery_modes") if isinstance(recovery.get("recovery_modes"), list) else []
    if runtime_recovery_state in {"recovering", "verifying", "active"}:
        recovery_label = "Recovering"
    elif recovery_modes:
        normalized_modes = {str(mode).upper() for mode in recovery_modes}
        if "NATIVE" in normalized_modes and "RUNTIME" in normalized_modes:
            recovery_label = "Native + Runtime certified"
        elif "NATIVE" in normalized_modes:
            recovery_label = "Native certified"
        elif "RUNTIME" in normalized_modes:
            recovery_label = "Runtime certified"
        else:
            recovery_label = ", ".join(sorted(normalized_modes)) + " certified"
    else:
        recovery_label = "Not certified"
    posture = _object(behavior_map.get("active_executable_posture"))
    behavior_label = "Normal" if not posture else ", ".join(f"{key} {value}" for key, value in sorted(posture.items()))
    severity_label = str(severity.get("label") or "normal")
    if severity_level == 0 and severity_label.lower() in {"none", "unknown"}:
        severity_label = "normal"
    summary = SystemSummary(
        operational_health=operational,
        trust=trust_state,
        guardian_health=guardian_health,
        severity=f"L{severity_level} {severity_label.title()}",
        attention=attention,
        recovery=recovery_label,
        updates=str(update.get("presentation_status") or update.get("status") or "Unknown"),
        behavior=behavior_label,
    )
    return SystemModel(
        summary=summary, diagnostics=diagnostics,
        events=_events(guardian, update, behavior_map, recovery),
        guardian=guardian, update=update, behavior=behavior_map,
        behavior_doctor=adaptive_doctor, recovery=recovery, login=login or {}, preferences=preferences,
        collection_errors=tuple(collection_errors),
    )


def collect_system_model(paths: LivePaths | None = None) -> SystemModel:
    paths = paths or LivePaths.defaults()
    errors: list[str] = []

    def collect(name: str, function, fallback: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            value = function()
            if not isinstance(value, Mapping):
                raise TypeError("collector did not return an object")
            return value
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            errors.append(f"{name}:{type(exc).__name__}:{exc}")
            return fallback

    guardian = collect("guardian", lambda: enrich_status(live_status(paths), paths.security_root), {})
    update = collect(
        "update",
        lambda: update_status(paths.update_root, maho_root=paths.runtime_root / "current"),
        {"status": "Unknown", "attention_required": True},
    )
    adaptive_root = behavior_state_root()
    behavior = collect("behavior", lambda: behavior_status(adaptive_root) or {}, {})
    adaptive_doctor = collect("behavior-doctor", lambda: behavior_doctor(repo_root(), adaptive_root), {"healthy": False})
    recovery = collect(
        "recovery", lambda: recovery_status(
            paths.recovery_root, runtime_campaign_root=DEFAULT_RUNTIME_CAMPAIGN_ROOT,
        ), {},
    )
    login = collect("login", collect_login_diagnostic, {"state": "UNKNOWN", "failed_checks": ["collector_unavailable"]})
    preferences = load_preferences()
    return build_system_model(
        guardian=guardian, update=update, behavior=behavior,
        adaptive_doctor=adaptive_doctor, recovery=recovery,
        preferences=preferences, collection_errors=errors, login=login,
    )
