#!/usr/bin/env python3
"""Canonical read-only live aggregation for Guardian.

Provider-specific files remain authoritative for their own schemas.  This module
only adapts them into Guardian evidence envelopes, preserves provenance, and
computes a coherent read-only projection.  It never mutates policy or recovery
state and never treats historical clean data as current without a successful
provider heartbeat.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import platform
from typing import Any, Mapping

from guardian_evidence import (
    EvidenceConfidence,
    EvidenceEnvelope,
    FreshnessPolicy,
    ProviderHealth,
    missing_evidence,
    parse_timestamp,
    utc_stamp,
)
from guardian_journal_stream import JournalStreamState, StreamContinuity, load_stream
from guardian_provider_state import ProviderHeartbeat, load_heartbeat
from guardian_signed_boot_provider import SignedBootTrust, observe_signed_boot
from guardian_trust_status import status_payload as recovery_status_payload
from guardian_world_state import (
    GuardianSelfFacts,
    GuardianTrustState,
    TrustSignal,
    build_world_state,
)
from maho_runtime_release import verify_release
from maho_update_cli import current_transaction
from maho_update_state import UpdateState


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    domain: str
    max_age_seconds: float
    state_relative_path: str | None
    required: bool = True


SECURITY_SPECS = (
    ProviderSpec("security.packages", "system", 900, "monitor-v2/packages.json"),
    ProviderSpec("security.persistence", "security", 900, "monitor-v2/persistence.json"),
    ProviderSpec("security.runtime", "security", 900, "monitor-v2/runtime.json"),
    ProviderSpec("security.privilege", "security", 900, "monitor-v2/privilege.json"),
    ProviderSpec("security.network", "security", 900, "monitor-v2/network.json"),
    ProviderSpec("security.integrity", "security", 2400, "monitor-v2/integrity.json"),
)
GUARDIAN_SPECS = (
    ProviderSpec("guardian.watch", "guardian", 90, None),
    ProviderSpec("guardian.service-events", "guardian", 90, "guardian/service-events/stream.json"),
)
ENVIRONMENT_SPECS = (
    ProviderSpec("environment.power", "hardware", 60, "power.json", required=False),
    ProviderSpec("environment.thermal", "hardware", 60, "thermal.json", required=False),
)


@dataclass(frozen=True)
class LivePaths:
    security_root: Path
    state_root: Path
    update_root: Path
    recovery_root: Path
    runtime_root: Path
    proc_root: Path = Path("/proc")
    signed_boot_root: Path = Path("/var/lib/maho/signed-boot")

    @classmethod
    def defaults(cls) -> "LivePaths":
        state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        return cls(
            security_root=state_home / "maho/security",
            state_root=state_home / "maho/state",
            update_root=Path(os.environ.get("MAHO_UPDATE_STATE_ROOT", "/var/lib/maho/update")),
            recovery_root=Path(os.environ.get("MAHO_GUARDIAN_RECOVERY_ROOT", "/var/lib/maho/guardian-recovery-r3/campaigns")),
            runtime_root=Path.home() / ".local/share/maho/runtime",
            signed_boot_root=Path(os.environ.get("MAHO_SIGNED_BOOT_STATE_ROOT", "/var/lib/maho/signed-boot")),
        )


def _read_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "state_missing"
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"state_unreadable:{type(exc).__name__}"
    if not isinstance(value, dict):
        return None, "state_not_object"
    return value, None


def _mtime(path: Path) -> str | None:
    try:
        return utc_stamp(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc))
    except OSError:
        return None


def _heartbeat_failure(spec: ProviderSpec, error: str) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        provider_id=spec.provider_id,
        domain=spec.domain,
        schema_version=1,
        observed_at=None,
        source="guardian-provider-heartbeat",
        freshness_policy=FreshnessPolicy(spec.max_age_seconds, required=spec.required),
        health=ProviderHealth.FAILED,
        data={},
        confidence=EvidenceConfidence.NONE,
        errors=(error,),
        authority_boundary="read-only-observer",
    )


def _provider_envelope(
    paths: LivePaths,
    spec: ProviderSpec,
    *,
    state_root: Path,
    now: datetime,
) -> tuple[EvidenceEnvelope, bool]:
    try:
        heartbeat = load_heartbeat(paths.security_root, spec.provider_id)
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return _heartbeat_failure(spec, "heartbeat_malformed"), False
    if heartbeat is None:
        return missing_evidence(
            spec.provider_id,
            spec.domain,
            source="guardian-provider-heartbeat",
            max_age_seconds=spec.max_age_seconds,
            authority_boundary="read-only-observer",
            required=spec.required,
        ), True

    state: dict[str, Any] | None = None
    state_error: str | None = None
    changed_at: str | None = None
    if spec.state_relative_path is not None:
        state_path = state_root / spec.state_relative_path
        state, state_error = _read_object(state_path)
        changed_at = _mtime(state_path)

    health = heartbeat.health
    errors = list(heartbeat.errors)
    if state_error is not None:
        health = ProviderHealth.UNKNOWN if state_error == "state_missing" else ProviderHealth.FAILED
        errors.append(state_error)

    data: dict[str, Any] = {
        "last_state_change_at": changed_at,
        "last_successful_observation_at": heartbeat.last_success_at,
        "last_observation_attempt_at": heartbeat.last_attempt_at,
        "heartbeat_sequence": heartbeat.sequence,
        "heartbeat_details": dict(heartbeat.details or {}),
    }
    if state is not None:
        data["state"] = state

    return EvidenceEnvelope(
        provider_id=spec.provider_id,
        domain=spec.domain,
        schema_version=1,
        observed_at=heartbeat.last_success_at,
        source=heartbeat.source,
        freshness_policy=FreshnessPolicy(spec.max_age_seconds, required=spec.required),
        health=health,
        data=data,
        confidence=EvidenceConfidence.HIGH if state_error is None else EvidenceConfidence.NONE,
        errors=tuple(dict.fromkeys(errors)),
        authority_boundary=heartbeat.authority_boundary,
    ), True


def collect_provider_evidence(
    paths: LivePaths,
    *,
    now: datetime | None = None,
) -> tuple[tuple[EvidenceEnvelope, ...], tuple[str, ...], JournalStreamState | None]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows: list[EvidenceEnvelope] = []
    schema_errors: list[str] = []

    for spec in SECURITY_SPECS:
        envelope, schema_ok = _provider_envelope(paths, spec, state_root=paths.security_root, now=current)
        rows.append(envelope)
        if not schema_ok:
            schema_errors.append(spec.provider_id)

    for spec in ENVIRONMENT_SPECS:
        envelope, schema_ok = _provider_envelope(paths, spec, state_root=paths.state_root, now=current)
        rows.append(envelope)
        if not schema_ok:
            schema_errors.append(spec.provider_id)

    watch_spec = GUARDIAN_SPECS[0]
    watch, schema_ok = _provider_envelope(paths, watch_spec, state_root=paths.security_root, now=current)
    rows.append(watch)
    if not schema_ok:
        schema_errors.append(watch_spec.provider_id)

    stream: JournalStreamState | None = None
    stream_spec = GUARDIAN_SPECS[1]
    stream_envelope, schema_ok = _provider_envelope(paths, stream_spec, state_root=paths.security_root, now=current)
    try:
        stream = load_stream(paths.security_root)
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        schema_ok = False
        stream = None
    if stream is not None:
        health = stream_envelope.health
        errors = list(stream_envelope.errors)
        if stream.continuity is StreamContinuity.FAILED:
            health = ProviderHealth.FAILED
            errors.append(stream.reason)
        elif stream.continuity is not StreamContinuity.CONTINUOUS:
            health = ProviderHealth.UNKNOWN
            errors.append(stream.reason)
        stream_envelope = EvidenceEnvelope(
            provider_id=stream_envelope.provider_id,
            domain=stream_envelope.domain,
            schema_version=stream_envelope.schema_version,
            observed_at=stream_envelope.observed_at,
            source=stream_envelope.source,
            freshness_policy=stream_envelope.freshness_policy,
            health=health,
            data={**dict(stream_envelope.data), "stream": stream.as_dict()},
            confidence=stream_envelope.confidence,
            errors=tuple(dict.fromkeys(errors)),
            authority_boundary=stream_envelope.authority_boundary,
        )
    rows.append(stream_envelope)
    if not schema_ok:
        schema_errors.append(stream_spec.provider_id)

    signed_boot = observe_signed_boot(
        paths.signed_boot_root,
        boot_id_path=paths.proc_root / "sys/kernel/random/boot_id",
        now=current,
    )
    rows.append(signed_boot.evidence)
    return tuple(rows), tuple(sorted(set(schema_errors))), stream


def _active_assessments(root: Path) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    directory = root / "guardian/active"
    if not directory.is_dir():
        return [], ()
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(directory.glob("*.json")):
        value, error = _read_object(path)
        if error is not None or value is None:
            errors.append(path.name)
            continue
        rows.append(value)
    rows.sort(key=lambda item: str(item.get("updated_at") or item.get("opened_at") or ""), reverse=True)
    return rows, tuple(errors)


def _severity(incidents: list[dict[str, Any]]) -> dict[str, Any]:
    best = {"level": 0, "label": "normal", "reason": "no active Guardian incident"}
    for row in incidents:
        severity = ((row.get("decision") or {}).get("severity") or {})
        level = severity.get("level")
        if isinstance(level, int) and 0 <= level <= 4 and level > best["level"]:
            best = {
                "level": level,
                "label": str(severity.get("label") or f"L{level}"),
                "reason": str(severity.get("reason") or "active Guardian incident"),
            }
    return best


_SIGNAL_PROVIDERS = {
    "integrity-drift": "security.integrity",
    "persistence-drift": "security.persistence",
    "privilege-boundary": "security.privilege",
    "runtime-executable": "security.runtime",
    "network-exposure": "security.network",
}


def _provider_condition_active(signal_kind: str, state: Mapping[str, Any]) -> bool | None:
    result = state.get("result")
    if signal_kind == "persistence-drift":
        attention = state.get("attention_result", result)
        return attention == "changed" if isinstance(attention, str) else None
    expected = {
        "integrity-drift": "changed",
        "privilege-boundary": "observed",
        "runtime-executable": "observed",
        "network-exposure": "observed",
    }.get(signal_kind)
    if expected is None or not isinstance(result, str):
        return None
    return result == expected


def _partition_incidents(
    root: Path,
    incidents: list[dict[str, Any]],
    evidence: tuple[EvidenceEnvelope, ...],
    *,
    now: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate current incidents from retained stale/superseded assessments.

    Guardian assessment files are durable history, not freshness authority.
    Security incidents are decision-active only while every referenced provider
    is current/healthy and still reports the condition represented by its
    signal. The on-disk reconciliation loop remains the lifecycle owner and
    archives resolved records; this read-only projection prevents the lagging
    durable latch from being mistaken for current truth in the meantime.
    """
    by_provider = {item.provider_id: item for item in evidence}
    current_rows: list[dict[str, Any]] = []
    retained_rows: list[dict[str, Any]] = []
    for row in incidents:
        if row.get("source_kind") != "security-incident":
            current_rows.append(row)
            continue
        incident_id = row.get("incident_id")
        source, error = _read_object(root / "incidents" / "active" / f"{incident_id}.json")
        if error is not None or source is None:
            retained_rows.append({**row, "canonical_state": "superseded", "canonical_reason": "source-incident-not-active"})
            continue
        signals = source.get("signals") if isinstance(source.get("signals"), list) else []
        provider_signals: list[tuple[str, str]] = []
        for signal in signals:
            if not isinstance(signal, Mapping):
                continue
            kind = signal.get("kind")
            provider = _SIGNAL_PROVIDERS.get(str(kind))
            if provider:
                provider_signals.append((str(kind), provider))
        if not provider_signals:
            retained_rows.append({**row, "canonical_state": "unknown", "canonical_reason": "signal-provider-unmapped"})
            continue
        disposition = "current"
        reason = "current-provider-condition"
        for signal_kind, provider_id in provider_signals:
            envelope = by_provider.get(provider_id)
            if envelope is None or not envelope.decision_usable(now=now):
                disposition, reason = "stale", f"{provider_id}-not-current"
                break
            state = envelope.data.get("state") if isinstance(envelope.data.get("state"), Mapping) else {}
            active = _provider_condition_active(signal_kind, state)
            if active is not True:
                disposition = "superseded" if active is False else "unknown"
                reason = f"{provider_id}-condition-cleared" if active is False else f"{provider_id}-condition-unknown"
                break
        if disposition == "current":
            current_rows.append({**row, "canonical_state": "current", "canonical_reason": reason})
        else:
            retained_rows.append({**row, "canonical_state": disposition, "canonical_reason": reason})
    return current_rows, retained_rows


def _boot_id(paths: LivePaths) -> str | None:
    try:
        value = (paths.proc_root / "sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    return value if value else None


def _runtime_verification(paths: LivePaths) -> dict[str, Any]:
    current = paths.runtime_root / "current"
    releases = paths.runtime_root / "releases"
    result = verify_release(current, releases)
    return result.as_dict()


def _clock_sane(evidence: tuple[EvidenceEnvelope, ...], now: datetime) -> bool:
    future_limit = now + timedelta(minutes=5)
    for item in evidence:
        if item.observed_at is None:
            continue
        try:
            stamp = parse_timestamp(item.observed_at)
        except ValueError:
            return False
        if stamp is not None and stamp > future_limit:
            return False
    return True


def _update_authority(paths: LivePaths) -> tuple[dict[str, Any] | None, list[dict[str, Any]], tuple[str, ...]]:
    try:
        transaction = current_transaction(paths.update_root)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return None, [], (f"update_authority_unreadable:{type(exc).__name__}",)
    if transaction is None:
        return None, [], ()

    state = str(transaction.get("state") or "")
    txid = str(transaction.get("transaction_id") or "")
    source_revision = str(transaction.get("source_revision") or "")
    generation = transaction.get("package_generation") if isinstance(transaction.get("package_generation"), Mapping) else {}
    packages = generation.get("packages") if isinstance(generation, Mapping) else []
    package_names = sorted(
        str(item.get("name")) for item in packages
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    )
    active = state in {
        UpdateState.STAGED.value,
        UpdateState.PREPARED.value,
        UpdateState.MAINTENANCE_READY.value,
        UpdateState.INSTALLING.value,
        UpdateState.INSTALLED_PENDING_ACTIVATION.value,
        UpdateState.ACTIVE_VERIFYING.value,
        UpdateState.FAILED_RECOVERABLE.value,
        UpdateState.RECOVERING.value,
    }
    records: list[dict[str, Any]] = []

    def record(kind: str, authority: str, subjects: list[str], details: Mapping[str, Any]) -> None:
        records.append({
            "kind": kind,
            "operation_id": txid,
            "state": state,
            "authority": authority,
            "authority_verified": True,
            "source_revision": source_revision,
            "subjects": subjects,
            "details": dict(details),
            "bounded_window": False,
            "suppression_ready": False,
            "suppression_blocker": "authoritative record has no explicit bounded intent window",
        })

    if active:
        record("maho-update", "maho-update-authority", [str(generation.get("id") or "")], {"package_generation": generation.get("id")})
        record("package-transaction", "maho-update-authority", package_names, {"package_generation": generation.get("id")})
        if any("maho-runtime" in (item.get("roles") or []) for item in packages if isinstance(item, Mapping)):
            record("maho-runtime-deployment", "maho-update-authority", [name for name in package_names if name], {"package_generation": generation.get("id")})
        activation = transaction.get("activation") if isinstance(transaction.get("activation"), Mapping) else {}
        if activation.get("native_execution_certified") is True and isinstance(activation.get("authority"), Mapping):
            record("native-admission", "maho-update-native-authority", [str(generation.get("id") or "")], {"native_authority": activation.get("authority")})
        recovery = transaction.get("recovery") if isinstance(transaction.get("recovery"), Mapping) else {}
        if recovery.get("native_l3_certified") is True and isinstance(recovery.get("authority"), Mapping):
            record("guardian-recovery", "maho-update-recovery-authority", [str(recovery.get("generation_id") or "")], {"native_authority": recovery.get("authority")})
    return transaction, records, ()


def _trust_signals(
    evidence: tuple[EvidenceEnvelope, ...],
    runtime: Mapping[str, Any],
    *,
    now: datetime,
) -> tuple[TrustSignal, ...]:
    by_id = {item.provider_id: item for item in evidence}
    signals: list[TrustSignal] = [
        TrustSignal("system.generation", GuardianTrustState.UNKNOWN, "exact live SystemGeneration/KernelGeneration authority is unavailable"),
    ]
    boot = by_id.get("boot.authority")
    if boot is None or not boot.decision_usable(now=now):
        reason = "Signed Boot evidence is missing, stale, or the provider is unavailable"
        if boot is not None and isinstance(boot.data, Mapping):
            reason = str(boot.data.get("trust_reason") or reason)
        signals.append(TrustSignal("boot.authority", GuardianTrustState.UNKNOWN, reason))
    else:
        raw_state = str(boot.data.get("trust_state") or SignedBootTrust.UNKNOWN.value)
        try:
            state = GuardianTrustState(raw_state)
        except ValueError:
            state = GuardianTrustState.UNKNOWN
        signals.append(TrustSignal(
            "boot.authority",
            state,
            str(boot.data.get("trust_reason") or "Signed Boot provider returned no trust explanation"),
        ))
    if runtime.get("verified") is True:
        signals.append(TrustSignal("maho.runtime", GuardianTrustState.VERIFIED, "immutable Maho runtime release verified"))
    elif runtime.get("reasons") == ["release_unavailable"]:
        signals.append(TrustSignal("maho.runtime", GuardianTrustState.UNKNOWN, "Maho runtime identity unavailable"))
    else:
        signals.append(TrustSignal("maho.runtime", GuardianTrustState.UNTRUSTED, "Maho runtime release verification failed"))

    integrity = by_id.get("security.integrity")
    if integrity is None or not integrity.decision_usable():
        signals.append(TrustSignal("security.integrity", GuardianTrustState.UNKNOWN, "critical integrity evidence is not current and healthy"))
    else:
        state = integrity.data.get("state") if isinstance(integrity.data, Mapping) else None
        result = state.get("result") if isinstance(state, Mapping) else None
        if result == "clean":
            signals.append(TrustSignal("security.integrity", GuardianTrustState.DEGRADED, "critical files match local package metadata, which is evidence but not an independent trust anchor"))
        elif result in {"changed", "partial"}:
            signals.append(TrustSignal("security.integrity", GuardianTrustState.DEGRADED, f"critical integrity observer reports {result}"))
        else:
            signals.append(TrustSignal("security.integrity", GuardianTrustState.UNKNOWN, "critical integrity result is not interpretable"))
    return tuple(signals)


def _recent_activity(
    incidents: list[dict[str, Any]],
    recovery: Mapping[str, Any],
    transaction: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for incident in incidents[:8]:
        rows.append({
            "kind": "incident",
            "at": incident.get("updated_at") or incident.get("opened_at"),
            "id": incident.get("incident_id"),
            "status": incident.get("status", "active"),
        })
    verified = recovery.get("last_verified_recovery")
    if isinstance(verified, Mapping):
        rows.append({"kind": "recovery", "at": None, "id": verified.get("campaign_id"), "status": "verified"})
    if transaction is not None:
        rows.append({"kind": "update", "at": transaction.get("updated_at"), "id": transaction.get("transaction_id"), "status": transaction.get("state")})
    return rows[:10]


def live_status(paths: LivePaths | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    paths = paths or LivePaths.defaults()
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    evidence, schema_errors, stream = collect_provider_evidence(paths, now=current)
    durable_incidents, incident_errors = _active_assessments(paths.security_root)
    incidents, retained_incidents = _partition_incidents(
        paths.security_root, durable_incidents, evidence, now=current,
    )
    severity = _severity(incidents)
    runtime = _runtime_verification(paths)
    boot_id = _boot_id(paths)
    recovery = recovery_status_payload(paths.recovery_root, current_kernel_release=platform.release())
    transaction, authority_records, authority_errors = _update_authority(paths)

    required = tuple(spec.provider_id for spec in (*SECURITY_SPECS, *GUARDIAN_SPECS) if spec.required) + ("boot.authority",)
    security_current = [
        item for item in evidence
        if item.provider_id.startswith("security.") and item.decision_usable(now=current)
    ]
    durable_readable = paths.security_root.is_dir() and os.access(paths.security_root, os.R_OK)
    writable_target = paths.security_root if paths.security_root.exists() else paths.security_root.parent
    self_facts = GuardianSelfFacts(
        durable_state_readable=durable_readable,
        durable_state_writable=os.access(writable_target, os.W_OK),
        schema_consistent=not schema_errors and not incident_errors,
        historical_evidence_integrity=(not incident_errors and int(recovery.get("invalid_history_records", 0)) == 0),
        runtime_identity_verified=(True if runtime.get("verified") is True else False if runtime.get("reasons") != ["release_unavailable"] else None),
        clock_sane=_clock_sane(evidence, current),
        boot_identity_available=boot_id is not None,
        recovery_provider_available=Path(__file__).with_name("guardian_recovery_registry.py").is_file(),
        security_provider_available=len(security_current) == len(SECURITY_SPECS),
        journal_continuity=(stream.continuity is StreamContinuity.CONTINUOUS) if stream is not None else None,
        dropped_events=stream.dropped_events if stream is not None else None,
    )
    world = build_world_state(
        evidence,
        required_provider_ids=required,
        self_facts=self_facts,
        trust_signals=_trust_signals(evidence, runtime, now=current),
        severity=severity,
        recovering=bool(transaction and transaction.get("state") == UpdateState.RECOVERING.value),
        now=current,
    )

    package_generation = None
    if transaction and isinstance(transaction.get("package_generation"), Mapping):
        package_generation = transaction["package_generation"].get("id")
    freshness = {
        item.provider_id: {
            "freshness": item.freshness(now=current).value,
            "health": item.health.value,
            "observed_at": item.observed_at,
            "decision_usable": item.decision_usable(now=current),
        }
        for item in evidence
    }
    boot_evidence = next((item for item in evidence if item.provider_id == "boot.authority"), None)
    boot_data = dict(boot_evidence.data) if boot_evidence is not None else {}
    return {
        "schema_version": 1,
        "kind": "guardian-live-status",
        "captured_at": utc_stamp(current),
        "world_state": world.as_dict(),
        "system": {
            "current_system_generation": None,
            "current_kernel_generation": None,
            "generation_note": "exact live generation authority unavailable; historical recovery proof is not promoted to current trust",
            "active_package_transaction_generation": package_generation,
            "maho_runtime": runtime,
        },
        "boot": {
            "boot_id": boot_id,
            "kernel_release": platform.release(),
            "signed_boot_authority": boot_data.get("trust_state", SignedBootTrust.UNKNOWN.value),
            "provider_health": boot_evidence.health.value if boot_evidence is not None else ProviderHealth.UNKNOWN.value,
            "boot_generation_id": boot_data.get("boot_generation_id"),
            "boot_authority_id": boot_data.get("boot_authority_id"),
            "boot_environment_id": boot_data.get("boot_environment_id"),
            "release_sequence": boot_data.get("release_sequence"),
            "security_epoch": boot_data.get("security_epoch"),
            "secure_boot": boot_data.get("secure_boot"),
            "setup_mode": boot_data.get("setup_mode"),
            "trust_reason": boot_data.get("trust_reason"),
        },
        "recovery": recovery,
        "active_incidents": incidents,
        "retained_incidents": retained_incidents,
        "evidence_freshness": freshness,
        "authorized_operation_evidence": authority_records,
        "containment": {"state": "none", "active": [], "automatic_authority": False},
        "recent_activity": _recent_activity(incidents, recovery, transaction),
        "errors": sorted(set(schema_errors + incident_errors + authority_errors)),
    }


def render_status(payload: Mapping[str, Any]) -> str:
    world = payload.get("world_state") if isinstance(payload.get("world_state"), Mapping) else {}
    guardian = world.get("guardian") if isinstance(world.get("guardian"), Mapping) else {}
    trust = guardian.get("trust") if isinstance(guardian.get("trust"), Mapping) else {}
    self_health = guardian.get("self_health") if isinstance(guardian.get("self_health"), Mapping) else {}
    severity = guardian.get("severity") if isinstance(guardian.get("severity"), Mapping) else {}
    system = payload.get("system") if isinstance(payload.get("system"), Mapping) else {}
    boot = payload.get("boot") if isinstance(payload.get("boot"), Mapping) else {}
    recovery = payload.get("recovery") if isinstance(payload.get("recovery"), Mapping) else {}
    incidents = payload.get("active_incidents") if isinstance(payload.get("active_incidents"), list) else []
    containment = payload.get("containment") if isinstance(payload.get("containment"), Mapping) else {}

    lines = [
        "Maho Guardian status",
        "",
        f"System                  L{severity.get('level', 0)} {severity.get('label', 'normal')}",
        f"Trust                   {trust.get('state', 'UNKNOWN')}",
        f"Guardian self-health    {self_health.get('state', 'UNKNOWN')}",
        f"Boot                    {boot.get('boot_id') or 'unknown'}  kernel={boot.get('kernel_release') or 'unknown'}",
        f"SystemGeneration        {system.get('current_system_generation') or 'unknown'}",
        f"KernelGeneration        {system.get('current_kernel_generation') or 'unknown'}",
        f"Recovery                {recovery.get('current_generation_trust', 'UNRESOLVED')}",
        f"Containment             {containment.get('state', 'none')}",
        f"Active incidents        {len(incidents)}",
        "",
        "Evidence freshness",
    ]
    freshness = payload.get("evidence_freshness")
    if isinstance(freshness, Mapping):
        for provider_id, row in sorted(freshness.items()):
            if not isinstance(row, Mapping):
                continue
            lines.append(f"  {provider_id:<26} {row.get('freshness', 'unknown'):<14} health={row.get('health', 'unknown')}")
    operations = payload.get("authorized_operation_evidence")
    lines.extend(("", "Authorized operations"))
    if isinstance(operations, list) and operations:
        for row in operations:
            if isinstance(row, Mapping):
                lines.append(f"  {row.get('kind')} {row.get('operation_id')} state={row.get('state')} suppression={'ready' if row.get('suppression_ready') else 'blocked'}")
    else:
        lines.append("  none")
    if payload.get("errors"):
        lines.extend(("", "Errors"))
        for error in payload.get("errors", []):
            lines.append(f"  {error}")
    return "\n".join(lines)
