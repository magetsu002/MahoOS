#!/usr/bin/env python3
"""Guardian reliability incidents for delegated systemd-user recovery."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from guardian_engine import evaluate_guardian
from guardian_recovery_registry import certified_service_recovery


UNIT_FAILED = "d9b373ed55a64feb8242e02dbe79a49c"
RESTART_SCHEDULED = "5eb03494b6584870a536b337290809b3"
UNIT_STARTED = "39f53479d3a045ac8e11786248231fbf"
_HEX32 = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class ServiceSnapshot:
    unit: str
    load_state: str
    active_state: str
    sub_state: str
    result: str
    invocation_id: str
    restart: str
    health_check: str = "unavailable"
    health_ok: bool = False
    health_evidence: tuple[str, ...] = ()
    boot_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_identity(value: object) -> bool:
    return isinstance(value, str) and _HEX32.fullmatch(value) is not None


def normalize_journal_event(entry: Mapping[str, Any]) -> dict[str, str] | None:
    """Accept only structured systemd manager events for exact certified units."""
    unit = entry.get("USER_UNIT")
    contract = certified_service_recovery(unit)
    if contract is None or entry.get("_COMM") != "systemd":
        return None
    boot_id = entry.get("_BOOT_ID")
    invocation_id = entry.get("USER_INVOCATION_ID")
    if not _valid_identity(boot_id) or not _valid_identity(invocation_id):
        return None

    message_id = entry.get("MESSAGE_ID")
    kind = ""
    if message_id == UNIT_FAILED:
        result = entry.get("UNIT_RESULT")
        if not isinstance(result, str) or result in {"", "success"}:
            return None
        kind = "failed"
    elif message_id == RESTART_SCHEDULED:
        result = entry.get("UNIT_RESULT")
        result = result if isinstance(result, str) and result else "provider-restart-scheduled"
        kind = "recovering"
    elif (
        message_id == UNIT_STARTED
        and entry.get("JOB_TYPE") == "start"
        and entry.get("JOB_RESULT") == "done"
    ):
        result = "success"
        kind = "started"
    else:
        return None

    timestamp = entry.get("__REALTIME_TIMESTAMP")
    return {
        "kind": kind,
        "unit": str(unit),
        "boot_id": str(boot_id),
        "invocation_id": str(invocation_id),
        "result": result,
        "timestamp_usec": str(timestamp) if str(timestamp).isdigit() else "0",
        "cursor": str(entry.get("__CURSOR") or ""),
    }


def incident_identity(boot_id: str, unit: str, invocation_id: str) -> str:
    raw = f"{boot_id}\0{unit}\0{invocation_id}".encode()
    return "inc-service-" + hashlib.sha256(raw).hexdigest()[:24]


def _atomic_private(path: Path, payload: Mapping[str, Any] | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    data = payload if isinstance(payload, str) else json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _timestamp(event: Mapping[str, str]) -> str:
    try:
        timestamp = int(event["timestamp_usec"])
        if timestamp <= 0:
            return utc_now()
        return datetime.fromtimestamp(timestamp / 1_000_000, timezone.utc).isoformat()
    except (KeyError, TypeError, ValueError, OverflowError):
        return utc_now()


class ServiceIncidentStore:
    def __init__(self, state_root: Path):
        self.root = state_root / "guardian"
        self.active = self.root / "active"
        self.archive = self.root / "archive"
        self.history = self.root / "recovery-history"
        self.service_state = self.root / "service-state"
        for path in (self.root, self.active, self.archive, self.history, self.service_state):
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, 0o700)

    def _state_path(self, incident_id: str) -> Path:
        return self.service_state / f"{incident_id}.json"

    def _history_path(self, incident_id: str) -> Path:
        return self.history / f"{incident_id}.json"

    def _active_path(self, incident_id: str) -> Path:
        return self.active / f"{incident_id}.json"

    def _states(self) -> list[dict[str, Any]]:
        return [row for path in self.service_state.glob("inc-service-*.json") if (row := _read(path))]

    def _guardian_record(self, state: Mapping[str, Any], *, resolved: bool) -> dict[str, Any]:
        contract = certified_service_recovery(state.get("unit"))
        if contract is None:
            raise ValueError("service lost its certified recovery contract")
        unresolved = state.get("lifecycle") == "unresolved"
        superseded = state.get("lifecycle") == "superseded"
        superseded_service = state.get("superseded_by_service")
        supersession_verified = (
            superseded
            and isinstance(superseded_service, Mapping)
            and superseded_service.get("health_ok") is True
        )
        normalized = {
            "incident": {
                "scope": "component",
                "ownership": contract.ownership,
                "impact": "minor" if not unresolved else "degraded",
                "evidence_confidence": "confirmed",
                "persistent": unresolved,
                "occurrence_count": 0 if resolved else 1,
                "correlated_failures": 0,
                "resolved": resolved,
            },
            "recovery": {
                "confidence": "certified",
                "certified_path": True,
                "previous_failures": 0,
                "verified": bool(resolved and (state.get("verified") or supersession_verified)),
            },
            "context": {"maintenance": False, "expected_transition": False},
        }
        recovery_state = {
            "failure": {"domain": "service", "graphical_available": True},
            "service": {
                "name": state["unit"],
                "consecutive_failures": 1,
                "provider_recovery_unresolved": unresolved,
            },
        }
        decision = evaluate_guardian(normalized, recovery_state)
        return {
            "version": 1,
            "kind": "guardian-service-assessment",
            "incident_id": state["incident_id"],
            "source_kind": "systemd-user-service",
            "status": "resolved" if resolved else "active",
            "subject": {"type": "service", "id": state["unit"]},
            "normalized": normalized,
            "decision": decision.as_dict(),
            "service_recovery": dict(state),
            "opened_at": state.get("opened_at"),
            "updated_at": state.get("updated_at"),
            "resolved_at": (state.get("recovered_at") or state.get("superseded_at")) if resolved else None,
            "resolution": (
                {
                    "kind": "superseded-by-verified-service-invocation",
                    "service": state.get("superseded_by_service"),
                }
                if resolved and state.get("lifecycle") == "superseded" else None
            ),
        }

    def _persist(self, state: dict[str, Any], *, active: bool = True) -> None:
        _atomic_private(self._state_path(state["incident_id"]), state)
        _atomic_private(self._history_path(state["incident_id"]), self._history_record(state))
        if active:
            _atomic_private(self._active_path(state["incident_id"]), self._guardian_record(state, resolved=False))

    def _history_record(self, state: Mapping[str, Any]) -> dict[str, Any]:
        incident_state = dict(state)
        if state.get("lifecycle") == "superseded":
            incident_state["lifecycle"] = "unresolved"
        incident_decision = self._guardian_record(incident_state, resolved=False)["decision"]
        terminal_decision = self._guardian_record(
            state, resolved=bool(state.get("verified") or state.get("lifecycle") == "superseded")
        )["decision"]
        contract = certified_service_recovery(state.get("unit"))
        return {
            "version": 1,
            "kind": "guardian-delegated-recovery",
            "incident_id": state["incident_id"],
            "identity": {
                "boot_id": state["boot_id"],
                "unit": state["unit"],
                "failed_invocation_id": state["failed_invocation_id"],
            },
            "failure_result": state.get("failure_result"),
            "replacement_invocation_id": state.get("replacement_invocation_id"),
            "status": state["lifecycle"],
            "verified": bool(state.get("verified")),
            "provider": contract.provider if contract else None,
            "recovery_mode": contract.mode if contract else None,
            "provider_action": contract.provider_action if contract else None,
            "guardian_severity": incident_decision.get("severity"),
            "terminal_guardian_severity": terminal_decision.get("severity"),
            "recovery_decision": incident_decision.get("recovery"),
            "guardian_mutation": False,
            "postcondition": state.get("postcondition"),
            "opened_at": state.get("opened_at"),
            "recovered_at": state.get("recovered_at"),
            "superseded_at": state.get("superseded_at"),
            "superseded_by_service": state.get("superseded_by_service"),
            "supersession": state.get("supersession"),
            "updated_at": state.get("updated_at"),
        }

    def arm_supersession(
        self, *, unit: str, boot_id: str, invocation_id: str, now: float, timestamp: str | None = None
    ) -> list[str]:
        """Arm bounded verification that may retire stale unresolved active incidents.

        This does not make the original delegated recovery successful. A later
        service invocation, including one from a later boot, must remain
        independently healthy for the normal stability window before the old
        active latch can be archived as superseded. Candidate boot identity is
        persisted and verified with the service snapshot.
        """
        contract = certified_service_recovery(unit)
        if contract is None or not _valid_identity(invocation_id):
            return []
        armed: list[str] = []
        stamp = timestamp or utc_now()
        for state in self._states():
            if (
                state.get("unit") != unit
                or state.get("lifecycle") != "unresolved"
                or invocation_id == state.get("failed_invocation_id")
            ):
                continue
            existing = state.get("supersession")
            if (
                isinstance(existing, Mapping)
                and existing.get("candidate_boot_id") == boot_id
                and existing.get("candidate_invocation_id") == invocation_id
            ):
                continue
            state["supersession"] = {
                "candidate_boot_id": boot_id,
                "candidate_invocation_id": invocation_id,
                "verify_after_epoch": now + contract.stability_seconds,
                "stability_seconds": contract.stability_seconds,
                "health_check": contract.health_check,
                "armed_at": stamp,
            }
            state["updated_at"] = stamp
            self._persist(state)
            armed.append(str(state["incident_id"]))
        return armed

    def process(self, event: Mapping[str, str], *, now: float) -> dict[str, Any] | None:
        contract = certified_service_recovery(event.get("unit"))
        if contract is None:
            return None
        iid = incident_identity(event["boot_id"], event["unit"], event["invocation_id"])
        path = self._state_path(iid)
        state = _read(path)
        timestamp = _timestamp(event)

        if event["kind"] == "failed":
            if state is None:
                state = {
                    "version": 1,
                    "incident_id": iid,
                    "unit": event["unit"],
                    "boot_id": event["boot_id"],
                    "failed_invocation_id": event["invocation_id"],
                    "failure_result": event["result"],
                    "lifecycle": "detected",
                    "verified": False,
                    "recover_by_epoch": now + contract.replacement_timeout_seconds,
                    "opened_at": timestamp,
                    "updated_at": timestamp,
                    "postcondition": {
                        "expected": {
                            "replacement_differs": True,
                            "active_state": contract.healthy_active_state,
                            "sub_state": contract.healthy_sub_state,
                            "replacement_timeout_seconds": contract.replacement_timeout_seconds,
                            "stability_seconds": contract.stability_seconds,
                            "health_check": contract.health_check,
                        },
                        "observed": None,
                    },
                }
                self._persist(state)
            return state

        if event["kind"] == "recovering":
            if state is None:
                state = {
                    "version": 1,
                    "incident_id": iid,
                    "unit": event["unit"],
                    "boot_id": event["boot_id"],
                    "failed_invocation_id": event["invocation_id"],
                    "failure_result": event["result"],
                    "opened_at": timestamp,
                }
            if state.get("lifecycle") in {"succeeded", "unresolved"}:
                return state
            state.update({
                "lifecycle": "recovering",
                "verified": False,
                "recover_by_epoch": now + contract.replacement_timeout_seconds,
                "updated_at": timestamp,
                "postcondition": {
                    "expected": {
                        "replacement_differs": True,
                        "active_state": contract.healthy_active_state,
                        "sub_state": contract.healthy_sub_state,
                        "replacement_timeout_seconds": contract.replacement_timeout_seconds,
                        "stability_seconds": contract.stability_seconds,
                        "health_check": contract.health_check,
                    },
                    "observed": None,
                },
            })
            self._persist(state)
            return state

        if event["kind"] == "started":
            candidates = [
                row for row in self._states()
                if row.get("unit") == event["unit"]
                and row.get("boot_id") == event["boot_id"]
                and row.get("lifecycle") == "recovering"
                and row.get("failed_invocation_id") != event["invocation_id"]
            ]
            state = None
            if candidates:
                state = max(candidates, key=lambda row: str(row.get("updated_at") or ""))
                state.update({
                    "lifecycle": "verifying",
                    "replacement_invocation_id": event["invocation_id"],
                    "verify_after_epoch": now + contract.stability_seconds,
                    "updated_at": timestamp,
                    "postcondition": {
                        "expected": {
                            "replacement_differs": True,
                            "active_state": contract.healthy_active_state,
                            "sub_state": contract.healthy_sub_state,
                            "stability_seconds": contract.stability_seconds,
                            "health_check": contract.health_check,
                        },
                        "observed": None,
                    },
                })
                self._persist(state)
            self.arm_supersession(
                unit=event["unit"],
                boot_id=event["boot_id"],
                invocation_id=event["invocation_id"],
                now=now,
                timestamp=timestamp,
            )
            return state
        return None

    def due_verifications(self, now: float) -> list[dict[str, Any]]:
        return [
            row for row in self._states()
            if (
                row.get("lifecycle") in {"detected", "recovering"}
                and isinstance(row.get("recover_by_epoch"), (int, float))
                and float(row["recover_by_epoch"]) <= now
            ) or (
                row.get("lifecycle") == "verifying"
                and isinstance(row.get("verify_after_epoch"), (int, float))
                and float(row["verify_after_epoch"]) <= now
            ) or (
                row.get("lifecycle") == "unresolved"
                and isinstance(row.get("supersession"), Mapping)
                and isinstance(row["supersession"].get("verify_after_epoch"), (int, float))
                and float(row["supersession"]["verify_after_epoch"]) <= now
            )
        ]

    def next_deadline(self) -> float | None:
        values: list[float] = []
        for row in self._states():
            if row.get("lifecycle") in {"detected", "recovering"} and isinstance(row.get("recover_by_epoch"), (int, float)):
                values.append(float(row["recover_by_epoch"]))
            elif row.get("lifecycle") == "verifying" and isinstance(row.get("verify_after_epoch"), (int, float)):
                values.append(float(row["verify_after_epoch"]))
            elif row.get("lifecycle") == "unresolved" and isinstance(row.get("supersession"), Mapping):
                deadline = row["supersession"].get("verify_after_epoch")
                if isinstance(deadline, (int, float)):
                    values.append(float(deadline))
        return min(values) if values else None

    def verify(self, state: dict[str, Any], snapshot: ServiceSnapshot, *, timestamp: str | None = None) -> bool:
        contract = certified_service_recovery(state.get("unit"))
        if contract is None:
            return False
        if state.get("lifecycle") == "unresolved":
            supersession = state.get("supersession")
            if not isinstance(supersession, Mapping):
                return False
            candidate_boot = supersession.get("candidate_boot_id")
            candidate = supersession.get("candidate_invocation_id")
            healthy_later = (
                snapshot.unit == state["unit"]
                and snapshot.boot_id == candidate_boot
                and snapshot.load_state == "loaded"
                and snapshot.active_state == contract.healthy_active_state
                and snapshot.sub_state == contract.healthy_sub_state
                and snapshot.invocation_id == candidate
                and snapshot.invocation_id != state.get("failed_invocation_id")
                and snapshot.restart == contract.expected_restart
                and snapshot.health_check == contract.health_check
                and snapshot.health_ok is True
            )
            stamp = timestamp or utc_now()
            if not healthy_later:
                state.pop("supersession", None)
                state["updated_at"] = stamp
                self._persist(state)
                return False
            state.update({
                "lifecycle": "superseded",
                "verified": False,
                "updated_at": stamp,
                "superseded_at": stamp,
                "superseded_by_service": snapshot.as_dict(),
            })
            state.pop("supersession", None)
            self._persist(state, active=False)
            try:
                self._active_path(state["incident_id"]).unlink()
            except FileNotFoundError:
                pass
            resolved = self._guardian_record(state, resolved=True)
            _atomic_private(self.archive / f"{state['incident_id']}-superseded.json", resolved)
            return False
        if state.get("lifecycle") not in {"detected", "recovering", "verifying"}:
            return bool(state.get("lifecycle") == "succeeded" and state.get("verified"))
        healthy = (
            snapshot.unit == state["unit"]
            and snapshot.boot_id == state.get("boot_id")
            and snapshot.load_state == "loaded"
            and snapshot.active_state == contract.healthy_active_state
            and snapshot.sub_state == contract.healthy_sub_state
            and snapshot.invocation_id == state.get("replacement_invocation_id")
            and snapshot.invocation_id != state.get("failed_invocation_id")
            and snapshot.restart == contract.expected_restart
            and snapshot.health_check == contract.health_check
            and snapshot.health_ok is True
        )
        stamp = timestamp or utc_now()
        state["updated_at"] = stamp
        state["verified"] = healthy
        state["lifecycle"] = "succeeded" if healthy else "unresolved"
        state.setdefault("postcondition", {})["observed"] = snapshot.as_dict()
        if healthy:
            state["recovered_at"] = stamp
        self._persist(state, active=not healthy)
        if healthy:
            resolved = self._guardian_record(state, resolved=True)
            _atomic_private(self.archive / f"{state['incident_id']}-recovered.json", resolved)
            try:
                self._active_path(state["incident_id"]).unlink()
            except FileNotFoundError:
                pass
        return healthy
