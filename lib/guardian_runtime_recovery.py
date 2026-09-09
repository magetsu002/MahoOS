#!/usr/bin/env python3
"""Guardian L2 history/authority for Maho runtime activation recovery.

This module never mutates runtime wiring. maho-setup owns the transaction and
reports the observed rollback postcondition back here for durable recording.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from guardian_engine import evaluate_guardian
from maho_runtime_release import verify_release


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def runtime_incident_identity(transaction_id: str, failed: str, replacement: str) -> str:
    raw = f"{transaction_id}\0{failed}\0{replacement}".encode()
    return "inc-runtime-" + hashlib.sha256(raw).hexdigest()[:24]


def _atomic_private(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
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
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _same_release(left: str, right: str) -> bool:
    try:
        return Path(left).resolve(strict=True) == Path(right).resolve(strict=True)
    except OSError:
        return False


def _identified_failed_release(reasons: tuple[str, ...]) -> bool:
    """The failed target may be corrupt, but its runtime identity must be bounded."""
    identity_failures = {
        "release_unavailable",
        "release_not_direct_child",
        "release_identity_invalid",
    }
    return not bool(identity_failures.intersection(reasons))


def _normalized(*, resolved: bool, certified: bool, previous_failures: int = 0) -> dict[str, Any]:
    return {
        "incident": {
            "scope": "runtime",
            "ownership": "maho",
            "impact": "degraded",
            "evidence_confidence": "confirmed",
            "persistent": not resolved,
            "occurrence_count": 0 if resolved else 1,
            "correlated_failures": 0,
            "resolved": resolved,
        },
        "recovery": {
            "confidence": "certified" if certified else "none",
            "certified_path": certified,
            "previous_failures": previous_failures,
            "verified": resolved,
        },
        "context": {"maintenance": False, "expected_transition": False},
    }


def _recovery_state(*, previous_verified: bool, transaction_in_progress: bool) -> dict[str, Any]:
    return {
        "failure": {
            "domain": "maho-runtime",
            "domain_confidence": "confirmed",
            "transaction_in_progress": transaction_in_progress,
            "graphical_available": True,
        },
        "availability": {"previous_runtime_verified": previous_verified},
    }


class RuntimeRecoveryStore:
    def __init__(self, state_root: Path, releases_root: Path):
        self.root = state_root / "guardian"
        self.active = self.root / "active"
        self.archive = self.root / "archive"
        self.history = self.root / "recovery-history"
        self.runtime_state = self.root / "runtime-state"
        self.releases_root = releases_root
        for path in (self.root, self.active, self.archive, self.history, self.runtime_state):
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, 0o700)

    def _state_path(self, iid: str) -> Path:
        return self.runtime_state / f"{iid}.json"

    def _history_path(self, iid: str) -> Path:
        return self.history / f"{iid}.json"

    def _active_path(self, iid: str) -> Path:
        return self.active / f"{iid}.json"

    def begin(
        self,
        *,
        transaction_id: str,
        failed: str,
        replacement: str,
        failure_evidence: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        failed_v = verify_release(failed, self.releases_root)
        replacement_v = verify_release(replacement, self.releases_root)
        failed_identified = _identified_failed_release(failed_v.reasons)
        distinct = failed_identified and not _same_release(failed_v.path, replacement_v.path)
        previous_verified = bool(replacement_v.verified and distinct)
        normalized = _normalized(resolved=False, certified=previous_verified)
        decision = evaluate_guardian(
            normalized,
            _recovery_state(previous_verified=previous_verified, transaction_in_progress=True),
        )
        authorized = bool(
            previous_verified
            and decision.severity.get("level") == 2
            and decision.execution_mode == "automatic"
            and decision.mutating_recovery_allowed
            and decision.recovery.get("action") == "rollback-previous"
            and decision.recovery.get("provider") == "maho-runtime"
            and decision.recovery.get("recovery_mode") == "transactional"
        )
        iid = runtime_incident_identity(transaction_id, failed_v.path, replacement_v.path)
        now = utc_now()
        state = {
            "version": 1,
            "kind": "guardian-runtime-recovery-state",
            "incident_id": iid,
            "transaction_id": transaction_id,
            "severity": 2,
            "domain": "maho-runtime",
            "provider": "maho-runtime",
            "recovery_mode": "transactional",
            "action": "rollback-previous",
            "executor": "maho-setup",
            "guardian_mutation": False,
            "automatic_authorized": authorized,
            "lifecycle": "recovering" if authorized else "unresolved",
            "verified": False,
            "failed_runtime": failed_v.as_dict(),
            "failed_runtime_identified": failed_identified,
            "replacement_runtime": replacement_v.as_dict(),
            "distinct_releases": distinct,
            "decision": decision.as_dict(),
            "failure_evidence": dict(failure_evidence or {}),
            "postcondition": {
                "expected": {
                    "current_equals_replacement": True,
                    "replacement_release_verified": True,
                    "managed_wiring_matches_current": True,
                    "systemd_reload_accepted_if_available": True,
                },
                "observed": None,
            },
            "transitions": [
                {"state": "detected", "at": now},
                {"state": "recovering" if authorized else "unresolved", "at": now},
            ],
            "opened_at": now,
            "updated_at": now,
            "recovered_at": None,
        }
        self._persist(state, active=True)
        return state

    def finish(
        self,
        *,
        incident_id: str,
        observed_current: str,
        wiring_verified: bool,
        systemd_reload_verified: bool,
    ) -> dict[str, Any]:
        state = _read(self._state_path(incident_id))
        if state is None:
            raise ValueError("runtime recovery incident not found")
        replacement_raw = state.get("replacement_runtime")
        replacement = replacement_raw if isinstance(replacement_raw, Mapping) else {}
        expected_path = str(replacement.get("path") or "")
        observed_v = verify_release(observed_current, self.releases_root)
        current_matches = bool(expected_path and observed_v.verified and _same_release(observed_v.path, expected_path))
        verified = bool(
            state.get("automatic_authorized")
            and current_matches
            and wiring_verified
            and systemd_reload_verified
        )
        now = utc_now()
        transitions = list(state.get("transitions") or [])
        transitions.append({"state": "verifying", "at": now})
        transitions.append({"state": "recovered" if verified else "verification-failed", "at": now})
        observed = {
            "current": observed_v.as_dict(),
            "current_equals_replacement": current_matches,
            "managed_wiring_matches_current": wiring_verified,
            "systemd_reload_accepted_if_available": systemd_reload_verified,
        }
        state.update(
            {
                "lifecycle": "recovered" if verified else "unresolved",
                "verified": verified,
                "postcondition": {**dict(state.get("postcondition") or {}), "observed": observed},
                "transitions": transitions,
                "updated_at": now,
                "recovered_at": now if verified else None,
            }
        )
        self._persist(state, active=not verified)
        if verified:
            try:
                self._active_path(incident_id).unlink()
            except FileNotFoundError:
                pass
            _atomic_private(self.archive / f"{incident_id}.json", self._guardian_record(state, resolved=True))
        return state

    def supersede_unresolved(self, *, current_runtime: str) -> dict[str, Any]:
        """Archive stale unresolved runtime incidents after a later verified activation.

        This never rewrites recovery history as successful. It only retires an
        old active latch when the currently committed runtime independently
        verifies and is distinct from both runtimes recorded by that incident.
        """
        current_v = verify_release(current_runtime, self.releases_root)
        if not current_v.verified:
            raise ValueError("current runtime is not a verified immutable release")
        superseded: list[str] = []
        now = utc_now()
        for active_path in sorted(self.active.glob("inc-runtime-*.json")):
            incident_id = active_path.stem
            state = _read(self._state_path(incident_id))
            if state is None or state.get("lifecycle") != "unresolved":
                continue
            failed_raw = state.get("failed_runtime")
            replacement_raw = state.get("replacement_runtime")
            failed = failed_raw if isinstance(failed_raw, Mapping) else {}
            replacement = replacement_raw if isinstance(replacement_raw, Mapping) else {}
            failed_path = str(failed.get("path") or "")
            replacement_path = str(replacement.get("path") or "")
            if not failed_path or not replacement_path:
                continue
            if _same_release(current_v.path, failed_path) or _same_release(current_v.path, replacement_path):
                continue
            transitions = list(state.get("transitions") or [])
            transitions.append({"state": "superseded", "at": now})
            state.update({
                "lifecycle": "superseded",
                "verified": False,
                "transitions": transitions,
                "updated_at": now,
                "superseded_at": now,
                "superseded_by_runtime": current_v.as_dict(),
            })
            self._persist(state, active=False)
            try:
                active_path.unlink()
            except FileNotFoundError:
                pass
            _atomic_private(self.archive / f"{incident_id}.json", self._guardian_record(state, resolved=True))
            superseded.append(incident_id)
        return {
            "version": 1,
            "kind": "guardian-runtime-supersession",
            "current_runtime": current_v.as_dict(),
            "superseded": superseded,
            "count": len(superseded),
        }

    def _guardian_record(self, state: Mapping[str, Any], *, resolved: bool) -> dict[str, Any]:
        certified = bool(state.get("automatic_authorized"))
        normalized = _normalized(
            resolved=resolved,
            certified=certified and resolved,
            previous_failures=0 if resolved else (1 if state.get("lifecycle") == "unresolved" else 0),
        )
        replacement_raw = state.get("replacement_runtime")
        replacement = replacement_raw if isinstance(replacement_raw, Mapping) else {}
        recovery = _recovery_state(
            previous_verified=bool(replacement.get("verified")),
            transaction_in_progress=bool(not resolved and state.get("lifecycle") == "recovering"),
        )
        decision = evaluate_guardian(normalized, recovery)
        failed_raw = state.get("failed_runtime")
        failed = failed_raw if isinstance(failed_raw, Mapping) else {}
        return {
            "version": 1,
            "kind": "guardian-runtime-assessment",
            "incident_id": state["incident_id"],
            "source_kind": "maho-runtime-activation",
            "status": "resolved" if resolved else "active",
            "subject": {"type": "runtime", "id": str(failed.get("content_sha256") or Path(str(failed.get("path") or "maho-runtime")).name)},
            "normalized": normalized,
            "decision": decision.as_dict(),
            "runtime_recovery": dict(state),
            "opened_at": state.get("opened_at"),
            "updated_at": state.get("updated_at"),
            "resolved_at": (state.get("recovered_at") or state.get("superseded_at")) if resolved else None,
            "resolution": (
                {"kind": "superseded-by-verified-runtime", "runtime": state.get("superseded_by_runtime")}
                if resolved and state.get("lifecycle") == "superseded" else None
            ),
        }

    def _history_record(self, state: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "version": 1,
            "kind": "guardian-transactional-runtime-recovery",
            "incident_id": state["incident_id"],
            "transaction_id": state.get("transaction_id"),
            "severity": state.get("severity"),
            "domain": state.get("domain"),
            "provider": state.get("provider"),
            "recovery_mode": state.get("recovery_mode"),
            "action": state.get("action"),
            "executor": state.get("executor"),
            "guardian_mutation": False,
            "automatic": bool(state.get("automatic_authorized")),
            "status": state.get("lifecycle"),
            "verified": bool(state.get("verified")),
            "failed_runtime": state.get("failed_runtime"),
            "replacement_runtime": state.get("replacement_runtime"),
            "decision": state.get("decision"),
            "failure_evidence": state.get("failure_evidence"),
            "postcondition": state.get("postcondition"),
            "transitions": state.get("transitions"),
            "opened_at": state.get("opened_at"),
            "updated_at": state.get("updated_at"),
            "recovered_at": state.get("recovered_at"),
            "superseded_at": state.get("superseded_at"),
            "superseded_by_runtime": state.get("superseded_by_runtime"),
        }

    def _persist(self, state: dict[str, Any], *, active: bool) -> None:
        _atomic_private(self._state_path(state["incident_id"]), state)
        _atomic_private(self._history_path(state["incident_id"]), self._history_record(state))
        if active:
            _atomic_private(self._active_path(state["incident_id"]), self._guardian_record(state, resolved=False))


def main() -> None:
    parser = argparse.ArgumentParser(prog="guardian_runtime_recovery.py")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--releases-root", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    begin = sub.add_parser("begin")
    begin.add_argument("--transaction-id", required=True)
    begin.add_argument("--failed", required=True)
    begin.add_argument("--replacement", required=True)
    begin.add_argument("--failure-evidence")
    finish = sub.add_parser("finish")
    finish.add_argument("--incident-id", required=True)
    finish.add_argument("--observed-current", required=True)
    finish.add_argument("--wiring-verified", action="store_true")
    finish.add_argument("--systemd-reload-verified", action="store_true")
    supersede = sub.add_parser("supersede")
    supersede.add_argument("--current-runtime", required=True)
    args = parser.parse_args()
    store = RuntimeRecoveryStore(Path(args.state_root), Path(args.releases_root))
    if args.command == "begin":
        evidence: Mapping[str, Any] | None = None
        if args.failure_evidence:
            raw = json.loads(Path(args.failure_evidence).read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                raise SystemExit("failure evidence must be a JSON object")
            evidence = raw
        result = store.begin(
            transaction_id=args.transaction_id,
            failed=args.failed,
            replacement=args.replacement,
            failure_evidence=evidence,
        )
    elif args.command == "finish":
        result = store.finish(
            incident_id=args.incident_id,
            observed_current=args.observed_current,
            wiring_verified=args.wiring_verified,
            systemd_reload_verified=args.systemd_reload_verified,
        )
    else:
        result = store.supersede_unresolved(current_runtime=args.current_runtime)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
