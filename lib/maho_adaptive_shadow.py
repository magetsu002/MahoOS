#!/usr/bin/env python3
"""Live, read-only adaptive-policy evaluator and durable shadow history."""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Sequence

from maho_adaptive_battery import battery_proposals
from maho_adaptive_integrations import guardian_proposals
from maho_adaptive_actuators import (
    CERTIFIED_EFFECTS, executable_policy_effects, executable_proposal_effects,
    execute_certified_actuators,
)
from maho_adaptive_leases import (
    LeaseBook, active_posture, book_from_dict, posture_for_mode, reconcile_leases,
    verify_executable, verify_shadow,
)
from maho_adaptive_maintenance import maintenance_proposals
from maho_adaptive_maintenance_state import MaintenanceVetoError, read_state as read_maintenance_veto
from maho_adaptive_network import network_proposals
from maho_adaptive_notifications import notification_context_proposals
from maho_adaptive_observers import observe_live
from maho_adaptive_proposal import AdaptationProposal
from maho_adaptive_resolver import ResolvedPosture, resolve_posture
from maho_adaptive_situation import SituationSnapshot, UNKNOWN, build_situation
from maho_adaptive_thermal import thermal_proposals
from maho_adaptive_workload import workload_proposals
from guardian_completion_status import enrich_status as enrich_guardian_status
from guardian_live_state import LivePaths, live_status as guardian_live_status

SCHEMA_VERSION = 1
DEFAULT_INTERVAL = 30.0

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def parse_stamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)

def state_root() -> Path:
    override = os.environ.get("MAHO_ADAPTIVE_STATE_ROOT")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return base / "maho" / "adaptive"

def repo_root() -> Path:
    override = os.environ.get("MAHO_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[1]

def adaptive_execution_policy(root: Path) -> dict[str, Any]:
    path = root / "config/platform.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"certified": False, "effects": (), "service_enabled": False, "reason": "platform-policy-unreadable"}
    adaptive = payload.get("adaptive") if isinstance(payload, Mapping) else None
    if not isinstance(adaptive, Mapping):
        return {"certified": False, "effects": (), "service_enabled": False, "reason": "adaptive-policy-absent"}
    effects = adaptive.get("certified_effects")
    if not isinstance(effects, list) or any(not isinstance(item, str) for item in effects):
        return {"certified": False, "effects": (), "service_enabled": False, "reason": "adaptive-effects-invalid"}
    normalized = tuple(sorted(set(effects)))
    expected = tuple(sorted(CERTIFIED_EFFECTS))
    a15_certified = adaptive.get("a15_execution_certified") is True
    a16_certified = adaptive.get("a16_maintenance_execution_certified") is True
    certified = a15_certified and a16_certified and normalized == expected
    return {
        "certified": certified,
        "a15_certified": a15_certified,
        "a16_certified": a16_certified,
        "effects": normalized,
        "service_enabled": adaptive.get("service_enabled") is True,
        "reason": None if certified else "adaptive-execution-uncertified",
    }

def read_json(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None

def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass

def append_history(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    line = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8", closefd=False) as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)

def read_observer_domain(root: Path, domain: str, now: datetime) -> Mapping[str, Any] | None:
    command = ["bash", str(root / "bin" / "maho-observe"), "current", domain]
    environment = dict(os.environ)
    environment["MAHO_ROOT"] = str(root)
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=2.5, env=environment)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    if not isinstance(data, Mapping):
        return None
    return {"observed_at": stamp(now), "data": dict(data)}

def read_live_session_workload(now: datetime) -> dict[str, Mapping[str, Any]]:
    try:
        live = observe_live()
    except Exception:
        return {}
    return {key: {"observed_at": stamp(now), "data": value} for key, value in live.items() if isinstance(value, Mapping)}

def read_network(now: datetime) -> Mapping[str, Any]:
    default_route = False
    try:
        lines = Path("/proc/net/route").read_text().splitlines()[1:]
        for line in lines:
            fields = line.split()
            if len(fields) >= 4 and fields[1] == "00000000" and int(fields[3], 16) & 0x1:
                default_route = True
                break
    except (OSError, ValueError):
        return {"observed_at": stamp(now), "data": {}}

    connectivity = "online" if default_route else "offline"
    reachable: bool | str = UNKNOWN
    # NetworkManager connectivity is a read-only signal and is stronger than
    # assuming a default route proves Internet reachability. Missing nmcli is
    # capability loss only; the snapshot remains usable with unknown reachability.
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "CONNECTIVITY", "general"],
            check=False, capture_output=True, text=True, timeout=1.5,
        )
        if result.returncode == 0:
            state = result.stdout.strip().lower()
            if state == "full":
                connectivity, reachable = "online", True
            elif state in {"limited", "portal"}:
                connectivity, reachable = "limited", False
            elif state == "none":
                connectivity, reachable = "offline", False
    except (OSError, subprocess.SubprocessError):
        pass
    data = {
        "connectivity": connectivity,
        "default_route": default_route,
        "reachable": reachable,
        "stability": "stable" if default_route and connectivity == "online" else "unstable",
        "recent_transition": UNKNOWN,
    }
    return {"observed_at": stamp(now), "data": data}

def _current_update_transaction() -> Mapping[str, Any] | None:
    base = Path(os.environ.get("MAHO_UPDATE_STATE_ROOT", "/var/lib/maho/update"))
    pointer = base / "current"
    try:
        transaction_id = pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not transaction_id.startswith("upd-"):
        return None
    return read_json(base / "transactions" / f"{transaction_id}.json")

def read_maintenance(now: datetime) -> Mapping[str, Any] | None:
    tx = _current_update_transaction()
    if tx is None:
        return None
    state = tx.get("state")
    if not isinstance(state, str):
        return None
    staged_states = {"STAGED", "PREPARED", "MAINTENANCE_READY", "INSTALLING", "INSTALLED_PENDING_ACTIVATION", "ACTIVE_VERIFYING", "HEALTHY"}
    terminal = {"HEALTHY", "RECOVERED", "ATTENTION_REQUIRED"}
    prepared = state == "PREPARED"
    data = {
        "transaction_state": state,
        "pending": state not in terminal,
        "staged": state in staged_states,
        "prepared": prepared,
        "recovery_prerequisites": True if prepared else UNKNOWN,
        "in_critical_section": state == "INSTALLING",
        "interruption_safe": False if state == "INSTALLING" else True,
        "enough_disk": True if prepared else UNKNOWN,
    }
    return {"observed_at": stamp(now), "data": data}

def read_guardian(now: datetime) -> Mapping[str, Any] | None:
    try:
        paths = LivePaths.defaults()
        payload = enrich_guardian_status(guardian_live_status(paths, now=now), paths.security_root)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    rows = payload.get("active_incidents") if isinstance(payload.get("active_incidents"), list) else []
    world = payload.get("world_state") if isinstance(payload.get("world_state"), Mapping) else {}
    guardian = world.get("guardian") if isinstance(world.get("guardian"), Mapping) else {}
    severity = guardian.get("severity") if isinstance(guardian.get("severity"), Mapping) else {}
    reliability = payload.get("reliability") if isinstance(payload.get("reliability"), Mapping) else {}
    recovery = payload.get("recovery") if isinstance(payload.get("recovery"), Mapping) else {}
    level = severity.get("level")
    if not isinstance(level, int) or isinstance(level, bool):
        level = 0
    trust = guardian.get("trust") if isinstance(guardian.get("trust"), Mapping) else {}
    recovering = trust.get("state") == "RECOVERING" or recovery.get("in_progress") is True
    # Canonical reliability is its own authority. Guardian self-health and trust
    # remain visible elsewhere, but missing boot/trust proof must not be
    # re-labelled as a reliability failure and permanently veto maintenance.
    unresolved_reliability = reliability.get("state") != "healthy"
    data = {
        "active_incident": bool(rows),
        "severity_level": level,
        "recovery_in_progress": recovering,
        "unresolved_reliability": unresolved_reliability,
    }
    return {"observed_at": payload.get("captured_at") or stamp(now), "data": data}

def _intent_values(root: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in (root / "config/intent.json", Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home()/'.config'))) / "maho/intent.json"):
        data = read_json(path)
        values = data.get("values") if data else None
        if isinstance(values, Mapping):
            merged.update(values)
    return merged

def read_user_intent(root: Path, now: datetime) -> Mapping[str, Any]:
    values = _intent_values(root)
    runtime = Path(os.environ.get("MAHO_NOTIFY_RUNTIME_DIR", str(Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "maho")))
    notify = read_json(runtime / "notify-status.json")
    dnd = notify.get("dnd") if notify and isinstance(notify.get("dnd"), bool) else UNKNOWN
    power_mode = values.get("power.mode", values.get("adaptive.power_mode", UNKNOWN))
    opt_outs = values.get("adaptive.opt_outs", [])
    if not isinstance(opt_outs, list) or any(not isinstance(item, str) for item in opt_outs):
        opt_outs = []
    data = {
        "power_mode": power_mode if isinstance(power_mode, str) else UNKNOWN,
        "adaptation_opt_outs": opt_outs,
        "dnd": dnd,
        "explicit_maintenance": values.get("maintenance.explicit", UNKNOWN),
        "foreground_performance": power_mode == "performance" if isinstance(power_mode, str) else UNKNOWN,
    }
    return {"observed_at": stamp(now), "data": data}

def _elapsed_since(raw: Any, now: datetime) -> float:
    parsed = parse_stamp(raw)
    if parsed is None:
        return 0.0
    return max(0.0, (now - parsed).total_seconds())

def update_dwell(tracker: dict[str, Any], key: str, value: Any, now: datetime) -> float:
    current = tracker.get(key)
    if isinstance(current, Mapping) and current.get("value") == value:
        return _elapsed_since(current.get("changed_at"), now)
    tracker[key] = {"value": value, "changed_at": stamp(now)}
    return 0.0

def power_ac_value(envelope: Mapping[str, Any] | None) -> bool | None:
    if envelope is None or not isinstance(envelope.get("data"), Mapping):
        return None
    data = envelope["data"]
    supplies = data.get("supplies") if isinstance(data.get("supplies"), list) else []
    external = [item.get("online") for item in supplies if isinstance(item, Mapping) and item.get("type") != "Battery" and isinstance(item.get("online"), bool)]
    if external:
        return any(external)
    return data.get("ac_online") if isinstance(data.get("ac_online"), bool) else None

def _battery_percentage(data: Mapping[str, Any]) -> int | None:
    supplies = data.get("supplies") if isinstance(data.get("supplies"), list) else []
    for item in supplies:
        if not isinstance(item, Mapping) or item.get("type") != "Battery":
            continue
        value = item.get("capacity_percent")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100:
            return int(value)
    value = data.get("percentage")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 100:
        return int(value)
    return None

def _thermal_level(maximum: int) -> str:
    if maximum >= 95000:
        return "critical"
    if maximum >= 85000:
        return "hot"
    if maximum >= 75000:
        return "warm"
    return "normal"

def _sample_trend(previous: Mapping[str, Any] | None, value: float, now: datetime, *, threshold: float) -> str:
    if not isinstance(previous, Mapping):
        return "stable"
    old = previous.get("value")
    observed = parse_stamp(previous.get("at"))
    if not isinstance(old, (int, float)) or isinstance(old, bool) or observed is None or now <= observed:
        return "stable"
    delta = value - float(old)
    if delta >= threshold:
        return "rising"
    if delta <= -threshold:
        return "falling"
    return "stable"

def apply_dwell(observations: dict[str, Any], tracker: dict[str, Any], now: datetime) -> None:
    power = observations.get("power")
    ac = power_ac_value(power if isinstance(power, Mapping) else None)
    if ac is not None and isinstance(power, Mapping) and isinstance(power.get("data"), Mapping):
        data = power["data"]
        data["ac_stable_seconds"] = update_dwell(tracker, "power_ac", ac, now)
        percentage = _battery_percentage(data)
        if percentage is not None:
            previous = tracker.get("battery_sample")
            trend = _sample_trend(previous if isinstance(previous, Mapping) else None, percentage, now, threshold=1.0)
            if ac is False:
                if trend == "falling" and isinstance(previous, Mapping):
                    observed = parse_stamp(previous.get("at"))
                    old = previous.get("value")
                    if observed is not None and isinstance(old, (int, float)) and now > observed:
                        per_minute = (float(old) - percentage) / max((now - observed).total_seconds(), 1.0) * 60.0
                        if per_minute >= 2.0:
                            trend = "rapid-fall"
                data["drain_trend"] = trend
            tracker["battery_sample"] = {"value": percentage, "at": stamp(now)}

    thermal = observations.get("thermal")
    if isinstance(thermal, Mapping) and isinstance(thermal.get("data"), Mapping):
        data = thermal["data"]
        maximum = data.get("max_millidegree_c")
        if isinstance(maximum, (int, float)) and not isinstance(maximum, bool) and -100000 <= maximum <= 250000:
            maximum_i = int(maximum)
            level = _thermal_level(maximum_i)
            prior_level = tracker.get("thermal_level")
            prior_value = prior_level.get("value") if isinstance(prior_level, Mapping) else None
            data["sustained_seconds"] = update_dwell(tracker, "thermal_level", level, now)
            previous_sample = tracker.get("thermal_sample")
            data["trend"] = _sample_trend(previous_sample if isinstance(previous_sample, Mapping) else None, maximum_i, now, threshold=1000.0)
            tracker["thermal_sample"] = {"value": maximum_i, "at": stamp(now)}
            transitions = tracker.get("thermal_transitions")
            if not isinstance(transitions, list):
                transitions = []
            if isinstance(prior_value, str) and prior_value != level:
                transitions.append(f"{prior_value}->{level}@{stamp(now)}")
                transitions = transitions[-8:]
                tracker["thermal_transitions"] = transitions
            data["recent_transitions"] = list(transitions)

    session = observations.get("session")
    if isinstance(session, Mapping) and isinstance(session.get("data"), Mapping):
        data = session["data"]
        locked = data.get("locked")
        if isinstance(locked, bool):
            dwell = update_dwell(tracker, "session_locked", locked, now)
            data["lock_dwell_seconds"] = dwell if locked else 0.0

    network = observations.get("network")
    if isinstance(network, Mapping) and isinstance(network.get("data"), Mapping):
        data = network["data"]
        signature = [data.get("connectivity"), data.get("default_route"), data.get("stability")]
        previous = tracker.get("network")
        previous_signature = previous.get("value") if isinstance(previous, Mapping) else None
        data["stability_seconds"] = update_dwell(tracker, "network", signature, now)
        if previous_signature is not None and list(previous_signature) != signature:
            data["recent_transition"] = f"{previous_signature}->{signature}"
        elif data.get("recent_transition") == UNKNOWN:
            data["recent_transition"] = "stable"

def collect_observations(root: Path, runtime_root: Path, now: datetime) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    for domain in ("power", "thermal"):
        value = read_observer_domain(root, domain, now)
        if value is not None:
            observations[domain] = value
    observations.update(read_live_session_workload(now))
    observations["network"] = read_network(now)
    for name, value in (("maintenance", read_maintenance(now)), ("guardian", read_guardian(now))):
        if value is not None:
            observations[name] = value
    observations["user_intent"] = read_user_intent(root, now)
    tracker_path = runtime_root / "context.json"
    raw_tracker = read_json(tracker_path)
    tracker = dict(raw_tracker) if raw_tracker and raw_tracker.get("schema_version") == SCHEMA_VERSION else {"schema_version": SCHEMA_VERSION}
    apply_dwell(observations, tracker, now)
    atomic_json(tracker_path, tracker)
    return observations

def load_book(runtime_root: Path) -> tuple[LeaseBook, str | None]:
    path = runtime_root / "leases.json"
    if not path.exists():
        return LeaseBook(), None
    raw = read_json(path)
    if raw is None:
        return LeaseBook(), "lease-state-unreadable"
    try:
        return book_from_dict(raw), None
    except ValueError as exc:
        return LeaseBook(), f"lease-state-invalid:{exc}"

def save_book(runtime_root: Path, book: LeaseBook) -> None:
    atomic_json(runtime_root / "leases.json", book.as_dict())

def posture_observation(book: LeaseBook, now: datetime) -> dict[str, Any]:
    active = [lease for lease in book.leases if lease.state in {"PROPOSED", "ACTIVE_SHADOW", "VERIFIED_SHADOW", "ACTIVE_EXECUTABLE", "VERIFIED_EXECUTABLE"}]
    ages = [_elapsed_since(lease.entered_at, now) for lease in active]
    return {
        "active_leases": [lease.lease_id for lease in active],
        "effective_posture": active_posture(book),
        "oldest_lease_age_seconds": max(ages, default=0.0),
        "source_policies": sorted({lease.source_policy for lease in active}),
    }

def policy_proposals(snapshot: SituationSnapshot, *, now: datetime) -> tuple[AdaptationProposal, ...]:
    proposals: list[AdaptationProposal] = []
    for policy in (
        battery_proposals,
        thermal_proposals,
        workload_proposals,
        network_proposals,
        maintenance_proposals,
        guardian_proposals,
        notification_context_proposals,
    ):
        try:
            proposals.extend(policy(snapshot, created_at=now))
        except (TypeError, ValueError):
            # One optional policy capability must not invalidate all other policy families.
            continue
    unique = {proposal.proposal_id: proposal for proposal in proposals}
    return tuple(unique[key] for key in sorted(unique))

def source_evidence_fresh(snapshot: SituationSnapshot, source: str) -> bool | None:
    if source.startswith("battery."):
        values = (snapshot.power.freshness,)
    elif source.startswith("thermal."):
        values = (snapshot.thermal.freshness,)
    elif source.startswith(("gaming.", "workload.", "media.", "compile.", "render.")):
        values = (snapshot.workload.freshness, snapshot.session.freshness)
    elif source.startswith("network."):
        values = (snapshot.network.freshness,)
    elif source.startswith("maintenance."):
        values = (snapshot.session.freshness, snapshot.power.freshness, snapshot.thermal.freshness,
                  snapshot.workload.freshness, snapshot.network.freshness, snapshot.maintenance.freshness,
                  snapshot.guardian.freshness)
    elif source.startswith("guardian."):
        values = (snapshot.guardian.freshness,)
    elif source.startswith(("notification.", "notifications.")):
        values = (snapshot.workload.freshness, snapshot.user_intent.freshness)
    else:
        return None
    return True if all(value == "fresh" for value in values) else None

def lease_conditions(book: LeaseBook, proposals: Sequence[AdaptationProposal], snapshot: SituationSnapshot) -> dict[str, bool | None]:
    result: dict[str, bool | None] = {}
    for lease in book.leases:
        if lease.state not in {"PROPOSED", "ACTIVE_SHADOW", "VERIFIED_SHADOW", "ACTIVE_EXECUTABLE", "VERIFIED_EXECUTABLE"}:
            continue
        equivalent = any(
            proposal.source_policy == lease.source_policy
            and lease.effect in proposal.requested_effects
            for proposal in proposals
        )
        if equivalent:
            result[lease.source_proposal_id] = True
        else:
            fresh = source_evidence_fresh(snapshot, lease.source_policy)
            result[lease.source_proposal_id] = False if fresh is True else None
    for proposal in proposals:
        result[proposal.proposal_id] = True
    return result

def proposal_summary(proposals: Sequence[AdaptationProposal]) -> list[dict[str, Any]]:
    rows = []
    for proposal in proposals:
        rows.append({
            "source_policy": proposal.source_policy,
            "priority_domain": proposal.priority_domain,
            "disruption_class": proposal.disruption_class,
            "confidence": proposal.confidence,
            "reason": proposal.reason,
            "requested_effects": [asdict(effect) for effect in proposal.requested_effects],
            "requires_human_review": proposal.requires_human_review,
            "automatic_execution_eligible": proposal.automatic_execution_eligible,
        })
    return rows

def situation_summary(snapshot: SituationSnapshot) -> dict[str, Any]:
    return {
        "power": {"ac_online": snapshot.power.ac_online, "battery_present": snapshot.power.battery_present,
                  "percentage": snapshot.power.percentage, "severity_band": snapshot.power.severity_band,
                  "freshness": snapshot.power.freshness},
        "thermal": {"level": snapshot.thermal.level, "maximum_millidegree_c": snapshot.thermal.maximum_millidegree_c,
                    "freshness": snapshot.thermal.freshness},
        "session": {"locked": snapshot.session.locked, "lock_dwell_seconds": snapshot.session.lock_dwell_seconds,
                    "idle_seconds": snapshot.session.idle_seconds, "freshness": snapshot.session.freshness},
        "workload": {"gaming": snapshot.workload.probable_gaming, "compile": snapshot.workload.probable_compile,
                     "rendering": snapshot.workload.probable_rendering, "media": snapshot.workload.probable_media,
                     "interactive": snapshot.workload.interactive, "confidence": snapshot.workload.confidence,
                     "freshness": snapshot.workload.freshness},
        "network": {"connectivity": snapshot.network.connectivity, "stability": snapshot.network.stability,
                    "freshness": snapshot.network.freshness},
        "maintenance": {"transaction_state": snapshot.maintenance.transaction_state,
                        "in_critical_section": snapshot.maintenance.in_critical_section,
                        "freshness": snapshot.maintenance.freshness},
        "guardian": {"active_incident": snapshot.guardian.active_incident,
                     "severity_level": snapshot.guardian.severity_level,
                     "recovery_in_progress": snapshot.guardian.recovery_in_progress,
                     "freshness": snapshot.guardian.freshness},
        "user_intent": {"power_mode": snapshot.user_intent.power_mode, "dnd": snapshot.user_intent.dnd,
                        "adaptation_opt_outs": list(snapshot.user_intent.adaptation_opt_outs)},
    }

def semantic_signature(record: Mapping[str, Any]) -> str:
    situation = record["situation"]
    semantic = {
        "power": {"ac_online": situation["power"]["ac_online"], "severity_band": situation["power"]["severity_band"],
                  "freshness": situation["power"]["freshness"]},
        "thermal": {"level": situation["thermal"]["level"], "freshness": situation["thermal"]["freshness"]},
        "session": {"locked": situation["session"]["locked"], "freshness": situation["session"]["freshness"]},
        "workload": situation["workload"],
        "network": situation["network"],
        "maintenance": situation["maintenance"],
        "guardian": situation["guardian"],
        "user_intent": situation["user_intent"],
        "proposals": [
            {"source_policy": row["source_policy"], "requested_effects": row["requested_effects"],
             "requires_human_review": row["requires_human_review"]}
            for row in record["proposals"]
        ],
        "desired_posture": record["resolved_posture"],
        "active_shadow_posture": record["active_shadow_posture"],
        "active_executable_posture": record.get("active_executable_posture", {}),
        "action_mode": (record.get("actions") or {}).get("mode", "SHADOW_ONLY"),
        "review_required": record["review_required"],
        "blocked": record.get("blocked"),
    }
    encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()

def count_history(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, Mapping) and value.get("schema_version") == SCHEMA_VERSION:
                    count += 1
    except OSError:
        return 0
    return count

def evaluate_shadow(runtime_root: Path, *, now: datetime | None = None,
                    observations: Mapping[str, Any] | None = None,
                    execute_certified: bool = False, actuator_runner=None) -> dict[str, Any]:
    current = (now or utc_now()).astimezone(timezone.utc)
    root = repo_root()
    runtime_root.mkdir(parents=True, exist_ok=True)
    os.chmod(runtime_root, 0o700)
    book, book_error = load_book(runtime_root)
    live = dict(observations) if observations is not None else collect_observations(root, runtime_root, current)
    live["adaptive_posture"] = posture_observation(book, current)
    snapshot = build_situation(live, captured_at=current)
    proposals = policy_proposals(snapshot, now=current)
    resolved = resolve_posture(snapshot, proposals)
    execution_policy = adaptive_execution_policy(root)
    execution_authorized = execute_certified and execution_policy["certified"] is True
    eligible_pairs = executable_proposal_effects(proposals) if execution_authorized else frozenset()
    eligible_policy_pairs = executable_policy_effects(proposals) if execution_authorized else frozenset()
    actuation = None
    actuation_blocker = None if not execute_certified or execution_authorized else str(execution_policy["reason"])

    if book_error is None:
        conditions = lease_conditions(book, proposals, snapshot)
        updated_book = reconcile_leases(
            book,
            resolved,
            proposals,
            condition_state=conditions,
            previous_posture=active_posture(book),
            now=current,
            executable_effects=CERTIFIED_EFFECTS if execution_authorized else frozenset(),
            executable_proposal_effects=eligible_pairs,
        )
        # Shadow verification proves only internal posture consistency.
        for lease in tuple(updated_book.leases):
            if lease.state == "ACTIVE_SHADOW" and posture_for_mode(updated_book, "shadow").get(lease.effect.key) == lease.effective_state:
                updated_book = verify_shadow(updated_book, lease.lease_id)

        if execution_authorized:
            try:
                actuation = execute_certified_actuators(
                    root, updated_book, runner=actuator_runner, now=current,
                    eligible_policy_effects=eligible_policy_pairs,
                    lease_condition_state={
                        lease.lease_id: conditions.get(lease.source_proposal_id)
                        for lease in updated_book.leases
                        if lease.state in {"ACTIVE_EXECUTABLE", "VERIFIED_EXECUTABLE"}
                    },
                )
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                actuation_blocker = f"certified-actuator-error:{exc}"
            else:
                for lease_id in actuation.verified_lease_ids:
                    updated_book = verify_executable(updated_book, lease_id)
                if not actuation.ok:
                    failed = [
                        f"{result.resource}:{result.detail or 'unknown'}"
                        for result in actuation.results if not result.ok
                    ]
                    actuation_blocker = "certified-actuator-failed:" + ",".join(failed)
        save_book(runtime_root, updated_book)
    else:
        # Corrupted durable lease state is uncertainty: observe and explain, but
        # do not create, release, or execute leases until a human repairs state.
        updated_book = book

    blocked = book_error or actuation_blocker
    if execute_certified:
        actions = {
            "mode": "A16_CERTIFIED" if execution_authorized else "A16_BLOCKED",
            "mutation_executed": bool(actuation and actuation.ok and actuation.mutation_executed),
            "verified": bool(actuation and actuation.ok),
            "resources": [result.resource for result in actuation.results] if actuation is not None else [],
            "cycle_ids": list(actuation.cycle_ids) if actuation is not None else [],
            "results": [result.as_dict() for result in actuation.results] if actuation is not None else [],
        }
    else:
        actions = {"mode": "SHADOW_ONLY", "mutation_executed": False}

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": stamp(current),
        "snapshot_id": snapshot.snapshot_id,
        "situation": situation_summary(snapshot),
        "proposals": proposal_summary(proposals),
        "resolved_posture": dict(resolved.effective_posture),
        "active_shadow_posture": posture_for_mode(updated_book, "shadow"),
        "active_executable_posture": posture_for_mode(updated_book, "executable"),
        "active_posture": active_posture(updated_book),
        "review_required": [list(item) for item in resolved.review_required],
        "rejected_proposals": [list(item) for item in resolved.rejected],
        "leases": [lease.as_dict() for lease in updated_book.leases if lease.state != "EXPIRED"],
        "blocked": blocked,
        "actions": actions,
    }
    signature = semantic_signature(record)
    history_path = runtime_root / "history.jsonl"
    current_path = runtime_root / "current.json"
    previous = read_json(current_path)
    previous_signature = previous.get("semantic_signature") if previous else None
    transition = signature != previous_signature
    transition_count = count_history(history_path)
    if transition:
        transition_count += 1
        history_record = dict(record)
        history_record["semantic_signature"] = signature
        history_record["transition_number"] = transition_count
        append_history(history_path, history_record)
    status = dict(record)
    status["semantic_signature"] = signature
    status["meaningful_transition"] = transition
    status["transition_count"] = transition_count
    atomic_json(current_path, status)
    return status

def history_rows(runtime_root: Path, limit: int = 20) -> list[dict[str, Any]]:
    if limit < 0 or limit > 500:
        raise ValueError("history limit must be between zero and 500")
    path = runtime_root / "history.jsonl"
    if not path.is_file() or limit == 0:
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=limit)
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and value.get("schema_version") == SCHEMA_VERSION:
                    rows.append(value)
    except OSError:
        return []
    return list(rows)

def current_status(runtime_root: Path) -> Mapping[str, Any] | None:
    value = read_json(runtime_root / "current.json")
    if value is None or value.get("schema_version") != SCHEMA_VERSION:
        return None
    return value

def doctor_report(root: Path, runtime_root: Path) -> dict[str, Any]:
    required = [
        root / "bin/maho-observe",
        root / "bin/maho-adaptive",
        root / "systemd/user/maho-adaptive.service",
        root / "lib/maho_adaptive_situation.py",
        root / "lib/maho_adaptive_resolver.py",
        root / "lib/maho_adaptive_leases.py",
        root / "lib/maho_adaptive_actuators.py",
        root / "lib/maho_adaptive_maintenance_state.py",
        root / "adapters/notifications/adaptive-quiet.sh",
        root / "adapters/updates/adaptive-maintenance-veto.sh",
    ]
    checks = {str(path.relative_to(root)): path.is_file() for path in required}
    policy = adaptive_execution_policy(root)
    lease_book, lease_error = load_book(runtime_root)
    lease_shadow_only = lease_error is None and all(lease.mode == "shadow" for lease in lease_book.leases)
    lease_authority_safe = lease_error is None and all(
        lease.mode == "shadow" or (
            policy["certified"] is True
            and lease.mode == "executable"
            and lease.effect.key in set(policy["effects"])
        )
        for lease in lease_book.leases
    )
    current = current_status(runtime_root)
    current_shadow_only = current is None or current.get("actions") == {"mode": "SHADOW_ONLY", "mutation_executed": False}
    if current is None:
        current_authority_safe = True
    else:
        actions = current.get("actions") if isinstance(current.get("actions"), Mapping) else {}
        mode = actions.get("mode")
        current_authority_safe = (
            mode == "SHADOW_ONLY"
            or (policy["certified"] is True and mode == "A16_CERTIFIED" and actions.get("verified") is True)
        )
    active_executable = [
        lease for lease in lease_book.leases
        if lease.mode == "executable" and lease.state in {"ACTIVE_EXECUTABLE", "VERIFIED_EXECUTABLE"}
    ]
    verified_executable = all(lease.state == "VERIFIED_EXECUTABLE" for lease in active_executable)
    maintenance_leases = [lease for lease in active_executable if lease.effect.key == "maintenance"]
    veto_path = runtime_root / "maintenance-veto.json"
    try:
        veto = read_maintenance_veto(veto_path)
        maintenance_projection_safe = (
            (not maintenance_leases and veto is None)
            or (
                len(maintenance_leases) == 1
                and veto is not None
                and veto["lease_id"] == maintenance_leases[0].lease_id
                and veto["source_policy"] == maintenance_leases[0].source_policy
            )
        )
        maintenance_projection_state = "active" if veto is not None else "absent"
    except MaintenanceVetoError as exc:
        maintenance_projection_safe = False
        maintenance_projection_state = f"invalid:{exc}"
    results = []
    if current is not None:
        actions = current.get("actions") if isinstance(current.get("actions"), Mapping) else {}
        results = actions.get("results") if isinstance(actions.get("results"), list) else []
    verified_actuator_results = all(isinstance(item, Mapping) and item.get("ok") is True for item in results)
    service_policy_safe = policy["service_enabled"] is not True or policy["certified"] is True
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "A16_CERTIFIED" if policy["certified"] else "SHADOW_ONLY",
        "source_checks": checks,
        "lease_state": "ok" if lease_error is None else lease_error,
        "lease_shadow_only": lease_shadow_only,
        "lease_authority_safe": lease_authority_safe,
        "live_executable_leases": len(active_executable),
        "verified_executable_leases": verified_executable,
        "verified_actuator_results": verified_actuator_results,
        "maintenance_projection_state": maintenance_projection_state,
        "maintenance_projection_safe": maintenance_projection_safe,
        "shadow_only_effects": sorted(posture_for_mode(lease_book, "shadow")),
        "current_record_shadow_only": current_shadow_only,
        "current_record_authority_safe": current_authority_safe,
        "execution_certified": policy["certified"],
        "a15_execution_certified": policy.get("a15_certified", False),
        "a16_maintenance_execution_certified": policy.get("a16_certified", False),
        "certified_effects": list(policy["effects"]),
        "service_enabled_by_policy": policy["service_enabled"],
        "healthy": (
            all(checks.values()) and lease_authority_safe and current_authority_safe
            and service_policy_safe and verified_executable and verified_actuator_results
            and maintenance_projection_safe
        ),
    }

def _print_status(status: Mapping[str, Any]) -> None:
    situation = status.get("situation") if isinstance(status.get("situation"), Mapping) else {}
    print("Adaptive: active")
    print(f"Captured:    {status.get('captured_at', 'unknown')}")
    print(f"Mode:        {(status.get('actions') or {}).get('mode', 'SHADOW_ONLY')}")
    print(f"Transitions: {status.get('transition_count', 0)}")
    executable = status.get("active_executable_posture") if isinstance(status.get("active_executable_posture"), Mapping) else {}
    shadow = status.get("active_shadow_posture") if isinstance(status.get("active_shadow_posture"), Mapping) else {}
    if status.get("blocked"):
        print(f"Blocked:     {status['blocked']}")
    thermal = situation.get("thermal") if isinstance(situation.get("thermal"), Mapping) else {}
    power = situation.get("power") if isinstance(situation.get("power"), Mapping) else {}
    workload = situation.get("workload") if isinstance(situation.get("workload"), Mapping) else {}
    contexts: list[str] = []
    if workload.get("gaming") is True: contexts.append("Gaming")
    if workload.get("compile") is True: contexts.append("Compiling")
    if workload.get("rendering") is True: contexts.append("Rendering")
    if power.get("severity_band") in {"LOW", "CONSERVING", "CRITICAL"}: contexts.append(f"Battery {power.get('severity_band')}")
    if thermal.get("level") in {"hot", "critical"}: contexts.append(f"Thermal {str(thermal.get('level')).title()}")
    print("Context:     " + (", ".join(contexts) if contexts else "Normal"))
    changes: list[str] = []
    if executable.get("notifications") in {"quiet", "defer-noncritical"}: changes.append("Notifications quiet")
    if executable.get("maintenance") == "suspended": changes.append("Maintenance suspended")
    print("Temporary changes: " + (", ".join(changes) if changes else "None"))
    shadow_rows = [f"{key.replace('_', ' ').title()} {value}" for key, value in sorted(shadow.items())]
    print("Shadow-only: " + (", ".join(shadow_rows) if shadow_rows else "None"))
    if changes:
        print("Returns to normal: after the condition clears and cooldown expires")

def watch(runtime_root: Path, *, interval: float = DEFAULT_INTERVAL, iterations: int = 0, execute_certified: bool = False) -> int:
    if interval < 1.0:
        raise ValueError("shadow watch interval must be at least one second")
    if iterations < 0:
        raise ValueError("iterations must be non-negative")
    completed = 0
    try:
        while iterations == 0 or completed < iterations:
            status = evaluate_shadow(runtime_root, execute_certified=execute_certified)
            completed += 1
            if status.get("meaningful_transition"):
                print(
                    f"maho-adaptive: {'a16' if execute_certified else 'shadow'} transition {status.get('transition_count')} "
                    f"posture={json.dumps(status.get('active_shadow_posture', {}), sort_keys=True, separators=(',', ':'))}",
                    flush=True,
                )
            if iterations != 0 and completed >= iterations:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0
    return 0

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maho-adaptive", description="Maho adaptive policy shadow evaluator")
    parser.add_argument("--state-root", type=Path, default=None, help="override adaptive state root")
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--json", action="store_true")
    evaluate.add_argument("--execute-certified", action="store_true", help="execute only certified reversible actuators")
    for name in ("status", "doctor"):
        command = sub.add_parser(name)
        command.add_argument("--json", action="store_true")
    history = sub.add_parser("history")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--json", action="store_true")
    watcher = sub.add_parser("watch")
    watcher.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    watcher.add_argument("--iterations", type=int, default=0, help=argparse.SUPPRESS)
    watcher.add_argument("--execute-certified", action="store_true", help="execute only certified reversible actuators")
    args = parser.parse_args(argv)
    runtime_root = (args.state_root or state_root()).expanduser()

    if args.command == "evaluate":
        result = evaluate_shadow(runtime_root, execute_certified=args.execute_certified)
        if args.json:
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        else:
            _print_status(result)
        return 0
    if args.command == "status":
        result = current_status(runtime_root)
        if result is None:
            print("maho-adaptive: no shadow evaluation has been recorded", file=os.sys.stderr)
            return 1
        if args.json:
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        else:
            _print_status(result)
        return 0
    if args.command == "history":
        try:
            rows = history_rows(runtime_root, args.limit)
        except ValueError as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(rows, sort_keys=True, separators=(",", ":")))
        else:
            for row in rows:
                print(f"{row.get('transition_number', '?')} {row.get('captured_at', 'unknown')} posture={json.dumps(row.get('active_shadow_posture', {}), sort_keys=True)}")
        return 0
    if args.command == "doctor":
        report = doctor_report(repo_root(), runtime_root)
        if args.json:
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        else:
            print("Maho adaptive policy doctor")
            for name, ok in report["source_checks"].items():
                print(f"{'PASS' if ok else 'FAIL'}  {name}")
            print(f"{'PASS' if report['lease_authority_safe'] else 'FAIL'}  certified lease authority")
            print(f"{'PASS' if report['verified_executable_leases'] else 'FAIL'}  executable leases verified")
            print(f"{'PASS' if report['verified_actuator_results'] else 'FAIL'}  actuator results verified")
            print(f"{'PASS' if report['maintenance_projection_safe'] else 'FAIL'}  maintenance veto projection {report['maintenance_projection_state']}")
            print(f"PASS  unsupported effects remain shadow-only: {', '.join(report['shadow_only_effects']) or 'none'}")
            print(f"{'PASS' if report['service_enabled_by_policy'] else 'INFO'}  maho-adaptive.service policy enabled")
        return 0 if report["healthy"] else 1
    if args.command == "watch":
        return watch(runtime_root, interval=args.interval, iterations=args.iterations, execute_certified=args.execute_certified)
    raise AssertionError("unreachable")

if __name__ == "__main__":
    raise SystemExit(main())
