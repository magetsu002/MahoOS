#!/usr/bin/env python3
"""Policy-blind execution adapter for exact Guardian process containment."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import signal
import time
from typing import Any, Callable, Protocol

from guardian_containment import ContainmentPlan, ContainmentPlanState, ContainmentTarget, ProcessIdentity
from security_containment import ancestor_chain, process_start_ticks, process_state, session_id
from security_probe import atomic_private, normalized_package_paths, package_record, read_process


class ContainmentDriver(Protocol):
    def freeze_exact(self, target: ContainmentTarget) -> dict[str, Any]: ...
    def release_exact(self, session_id: str, target: ContainmentTarget) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ContainmentReceipt:
    result: str
    authority_id: str | None
    target_digest: str
    session_id: str | None
    contained: tuple[ProcessIdentity, ...]
    failed: tuple[dict[str, Any], ...]
    rollback: dict[str, Any]
    verified: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "authority_id": self.authority_id,
            "target_digest": self.target_digest,
            "session_id": self.session_id,
            "contained": [asdict(item) for item in self.contained],
            "failed": [dict(item) for item in self.failed],
            "rollback": dict(self.rollback),
            "verified": self.verified,
            "reason": self.reason,
        }


class ExactProcessContainmentDriver:
    """Execute only exact stable process identities; never selects policy targets."""

    def __init__(
        self,
        *,
        db_root: Path,
        proc_root: Path,
        fs_root: Path,
        state_root: Path,
        uid: int,
        signaler: Callable[[int, int], None] = os.kill,
        sleeper: Callable[[float], None] = time.sleep,
        protected_pids: set[int] | None = None,
    ) -> None:
        self.db_root = db_root
        self.proc_root = proc_root
        self.fs_root = fs_root
        self.state_root = state_root
        self.uid = uid
        self.signaler = signaler
        self.sleeper = sleeper
        self.protected_pids = protected_pids

    def _protected(self) -> set[int]:
        if self.protected_pids is not None:
            return set(self.protected_pids)
        return ancestor_chain(self.proc_root, os.getpid())

    def _validate(self, target: ContainmentTarget) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        record = package_record(self.db_root, target.package)
        if not record or record.get("version") != target.version:
            return record, [{"reason": "package-version-mismatch"}]
        package_paths = normalized_package_paths(record)
        failures: list[dict[str, Any]] = []
        protected = self._protected()
        for identity in target.processes:
            if identity.pid in protected:
                failures.append({"pid": identity.pid, "reason": "protected-ancestor"})
                continue
            proc = self.proc_root / str(identity.pid)
            current = read_process(proc, self.fs_root)
            if not current or current.get("uid") != self.uid:
                failures.append({"pid": identity.pid, "reason": "process-identity-unavailable"})
                continue
            if current.get("exe") != identity.exe:
                failures.append({"pid": identity.pid, "reason": "executable-mismatch"})
                continue
            if current.get("relative_exe") not in package_paths:
                failures.append({"pid": identity.pid, "reason": "package-ownership-mismatch"})
                continue
            start = process_start_ticks(self.proc_root, identity.pid)
            if start != identity.start_time_ticks:
                failures.append({"pid": identity.pid, "reason": "process-start-mismatch"})
        return record, failures

    def freeze_exact(self, target: ContainmentTarget) -> dict[str, Any]:
        record, failures = self._validate(target)
        if failures:
            return {"result": "refused", "session_id": None, "contained": [], "failed": failures}
        assert record is not None
        stopped: list[ProcessIdentity] = []
        execution_failures: list[dict[str, Any]] = []
        for identity in target.processes:
            try:
                self.signaler(identity.pid, signal.SIGSTOP)
                self.sleeper(0.03)
            except (ProcessLookupError, PermissionError, OSError) as exc:
                execution_failures.append({"pid": identity.pid, "reason": type(exc).__name__})
                break
            state = process_state(self.proc_root, identity.pid)
            if state is None or not state.startswith(("T", "t")):
                execution_failures.append({"pid": identity.pid, "reason": f"stop-not-verified:{state}"})
                break
            stopped.append(identity)

        if execution_failures:
            rollback_failed: list[dict[str, Any]] = []
            for identity in reversed(stopped):
                try:
                    self.signaler(identity.pid, signal.SIGCONT)
                    self.sleeper(0.03)
                except (ProcessLookupError, PermissionError, OSError) as exc:
                    rollback_failed.append({"pid": identity.pid, "reason": type(exc).__name__})
            return {
                "result": "failed-rolled-back" if not rollback_failed else "failed-rollback-incomplete",
                "session_id": None,
                "contained": [],
                "failed": execution_failures + rollback_failed,
            }

        sid = session_id()
        session = {
            "version": 1,
            "kind": "process-containment-session",
            "session_id": sid,
            "package": target.package,
            "installed_version": target.version,
            "finding_id": target.finding_id,
            "guardian_exact_target_digest": target.digest,
            "processes": [asdict(item) for item in target.processes],
        }
        path = self.state_root / "containment" / f"{sid}.json"
        atomic_private(path, (json.dumps(session, indent=2, sort_keys=True) + "\n").encode())
        return {
            "result": "contained",
            "session_id": sid,
            "contained": [asdict(item) for item in target.processes],
            "failed": [],
        }

    def release_exact(self, session_id_value: str, target: ContainmentTarget) -> dict[str, Any]:
        path = self.state_root / "containment" / f"{session_id_value}.json"
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"result": "refused", "released": [], "failed": [{"reason": "session-unavailable"}]}
        if data.get("guardian_exact_target_digest") != target.digest:
            return {"result": "refused", "released": [], "failed": [{"reason": "session-target-mismatch"}]}
        released: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for identity in target.processes:
            if process_start_ticks(self.proc_root, identity.pid) != identity.start_time_ticks:
                failed.append({"pid": identity.pid, "reason": "process-start-mismatch"})
                continue
            try:
                self.signaler(identity.pid, signal.SIGCONT)
                self.sleeper(0.03)
            except (ProcessLookupError, PermissionError, OSError) as exc:
                failed.append({"pid": identity.pid, "reason": type(exc).__name__})
                continue
            state = process_state(self.proc_root, identity.pid)
            if state and state.startswith(("T", "t")):
                failed.append({"pid": identity.pid, "reason": f"resume-not-verified:{state}"})
                continue
            released.append({"pid": identity.pid, "state": state})
        return {"result": "released" if not failed else "partial", "released": released, "failed": failed}


def _parse_identities(rows: Any) -> tuple[ProcessIdentity, ...]:
    if not isinstance(rows, list):
        return ()
    parsed: list[ProcessIdentity] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            parsed.append(ProcessIdentity(int(row["pid"]), int(row["start_time_ticks"]), str(row["exe"])))
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(sorted(parsed))


def execute_containment(plan: ContainmentPlan, driver: ContainmentDriver) -> ContainmentReceipt:
    if plan.state is not ContainmentPlanState.READY:
        return ContainmentReceipt("refused", plan.authority_id, plan.target.digest, None, (), (), {}, False, plan.reason)
    result = driver.freeze_exact(plan.target)
    contained = _parse_identities(result.get("contained"))
    expected = tuple(sorted(plan.target.processes))
    session = result.get("session_id") if isinstance(result.get("session_id"), str) else None
    if contained != expected:
        if session:
            driver.release_exact(session, plan.target)
        return ContainmentReceipt(
            "verification-failed",
            plan.authority_id,
            plan.target.digest,
            None,
            contained,
            tuple(result.get("failed") or ()),
            {},
            False,
            "adapter result did not match the exact authorized process set; rollback requested",
        )
    return ContainmentReceipt(
        "contained",
        plan.authority_id,
        plan.target.digest,
        session,
        contained,
        tuple(result.get("failed") or ()),
        {"action": "resume-exact-session", "session_id": session, "target_digest": plan.target.digest},
        bool(session),
        "exact authorized target contained and rollback metadata recorded" if session else "containment session was not persisted",
    )


def release_containment(receipt: ContainmentReceipt, target: ContainmentTarget, driver: ContainmentDriver) -> dict[str, Any]:
    if not receipt.verified or not receipt.session_id or receipt.target_digest != target.digest:
        return {"result": "refused", "reason": "release receipt does not bind the exact containment target"}
    return driver.release_exact(receipt.session_id, target)
