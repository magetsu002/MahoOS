#!/usr/bin/env python3
"""S2.2 automatic execution owner for exact normal-impact Maho updates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import subprocess
from typing import Any, Callable, Mapping

from guardian_native_admission import CandidateRoots
from maho_live_generation import GENERATION_ROOT
from maho_update_admission import (
    evaluate_normal_production_candidate,
    freeze_admission_evidence,
    guardian_transaction_id,
    issue_frozen_activation_authority,
    verify_frozen_activation_authority,
)
from maho_update_candidate_generation import (
    load_current_verified_generations,
    promote_normal_candidate_generation,
    publish_normal_candidate_generation,
    read_candidate_publication,
)
from maho_update_execution_authority import (
    consume_activation_handoff,
    consume_execution_authority,
    executor_identity,
    handoff_consumption_path,
    handoff_path,
    issue_activation_handoff,
    issue_execution_authority,
    parse_activation_handoff,
    publish_activation_handoff,
    publish_execution_authority,
    read_activation_handoff_consumption,
    verify_activation_handoff,
    verify_activation_handoff_reconciliation,
    verify_execution_authority,
)
from maho_update_native import NativeBtrfsOps
from maho_update_normal import NormalExecutionPlan, execute_normal_candidate
from maho_update_normal_authority import load_normal_execution_authority
from maho_update_normal_host import NormalProductionOps
from maho_update_staging import validate_manifest
from maho_update_state import (
    UpdateState,
    publish_transaction,
    read_transaction,
    transaction_path,
    transition_transaction,
    validate_transaction,
)

SAFE_RESERVE_MIN_BYTES = 20 * 1024**3
SAFE_RESERVE_FRACTION = 0.15
PREPARATION_OVERHEAD_BYTES = 512 * 1024**2
MAINTENANCE_EVIDENCE_MAX_AGE = timedelta(seconds=90)


EXECUTOR_MODULES = (
    "guardian_admission.py",
    "guardian_native_admission.py",
    "maho_update_admission.py",
    "maho_update_automatic_execution.py",
    "maho_update_candidate_generation.py",
    "maho_update_execution_authority.py",
    "maho_update_native.py",
    "maho_update_normal.py",
    "maho_update_normal_authority.py",
    "maho_update_normal_host.py",
    "maho_update_state.py",
)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    data = (json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n").encode()
    tmp = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"automatic execution evidence unavailable:{path}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("automatic execution evidence is not an object")
    return dict(raw)


def record_path(state_root: Path, transaction_id: str) -> Path:
    return state_root / "automatic-executions" / f"{transaction_id}.json"


def read_execution_record(state_root: Path, transaction_id: str) -> dict[str, Any] | None:
    path = record_path(state_root, transaction_id)
    try:
        return _read_json(path)
    except ValueError:
        return None


def _plan(transaction: Mapping[str, Any]) -> NormalExecutionPlan:
    tx = validate_transaction(transaction)
    for event in reversed(tx["history"]):
        if event.get("state") != UpdateState.PREPARED.value:
            continue
        evidence = event.get("evidence")
        raw = evidence.get("normal_plan") if isinstance(evidence, Mapping) else None
        if not isinstance(raw, Mapping):
            continue
        required = {
            "transaction_id", "package_generation_id", "source_provenance_id",
            "payload_paths", "effects", "activation_requirements", "selection_kind",
            "execution_environment", "safe_reserve_bytes",
            "reserve_after_preparation_bytes",
        }
        if set(raw) != required:
            raise ValueError("prepared normal execution plan fields are invalid")
        plan = NormalExecutionPlan(
            transaction_id=str(raw["transaction_id"]),
            package_generation_id=str(raw["package_generation_id"]),
            source_provenance_id=str(raw["source_provenance_id"]),
            payload_paths=tuple(str(item) for item in raw["payload_paths"]),
            effects=tuple(str(item) for item in raw["effects"]),
            activation_requirements=tuple(str(item) for item in raw["activation_requirements"]),
            selection_kind=str(raw["selection_kind"]),
            execution_environment=str(raw["execution_environment"]),
            safe_reserve_bytes=int(raw["safe_reserve_bytes"]),
            reserve_after_preparation_bytes=int(raw["reserve_after_preparation_bytes"]),
        )
        if (
            plan.transaction_id != tx["transaction_id"]
            or plan.package_generation_id != tx["package_generation"]["id"]
            or plan.source_provenance_id != tx["source_provenance"]["id"]
            or plan.execution_environment != "production"
        ):
            raise ValueError("prepared normal execution plan binding drifted")
        return plan
    raise ValueError("prepared normal execution plan is unavailable")


def _parse_stamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _maintenance_binding(
    value: Mapping[str, Any], *, now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if value.get("safe") is True:
        snapshot = value.get("snapshot_id")
        captured = value.get("captured_at")
        authority = value.get("authority")
        decision_at = value.get("decision_at")
        repository_observed_at = value.get("repository_observed_at")
    elif value.get("ready") is True:
        snapshot = value.get("adaptive_snapshot_id")
        captured = value.get("adaptive_captured_at")
        authority = value.get("authority")
        decision_at = value.get("decision_at")
        repository_observed_at = value.get("repository_observed_at")
    else:
        raise ValueError("maintenance evidence is no longer ready")
    observed = _parse_stamp(captured)
    if (
        not isinstance(snapshot, str) or not snapshot
        or observed is None
        or observed > current + timedelta(seconds=5)
        or current - observed > MAINTENANCE_EVIDENCE_MAX_AGE
    ):
        raise ValueError("fresh maintenance snapshot identity is unavailable")
    return {
        "safe": True,
        "snapshot_id": snapshot,
        "captured_at": captured,
        "decision_at": decision_at,
        "authority": authority,
        "repository_observed_at": repository_observed_at,
    }


def disk_reserve_evidence(
    transaction: Mapping[str, Any],
    cache_root: Path,
    *,
    disk_usage: Callable[[str | os.PathLike[str]], Any] = shutil.disk_usage,
) -> dict[str, Any]:
    tx = validate_transaction(transaction)
    root_usage = disk_usage("/")
    cache_usage = disk_usage(cache_root)
    required = (
        sum(
            int(item["download_size"]) + int(item["installed_size"])
            for item in tx["package_generation"]["packages"]
        )
        + PREPARATION_OVERHEAD_BYTES
    )
    reserve = max(
        SAFE_RESERVE_MIN_BYTES,
        int(math.ceil(root_usage.total * SAFE_RESERVE_FRACTION)),
    )
    available = min(root_usage.free, cache_usage.free)
    return {
        "ok": available >= required and available - required >= reserve,
        "required_bytes": required,
        "available_bytes": available,
        "reserve_bytes": reserve,
        "reserve_policy": "max(20GiB,15%-root-filesystem)",
    }


def _installed_generation_current(
    transaction: Mapping[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    tx = validate_transaction(transaction)
    names = [item["name"] for item in tx["package_generation"]["packages"]]
    completed = runner(
        ["pacman", "-Q", "--", *names],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return False
    observed: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        name, sep, version = line.partition(" ")
        if sep:
            observed[name] = version.strip()
    expected = {
        item["name"]: item["installed_version"]
        for item in tx["package_generation"]["packages"]
    }
    return observed == expected


def _repository_binding(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> dict[str, Any]:
    hashes = expected.get("repository_hashes")
    if not isinstance(hashes, Mapping) or not hashes:
        raise ValueError("repository generation evidence is unavailable")
    if dict(hashes) != dict(observed):
        raise ValueError("repository_generation_drifted")
    return {"ok": True, "hashes": dict(observed)}


def _recovery_evidence(live: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    required_live = (
        "system_generation_id", "kernel_generation_id",
        "root_subvolume_uuid", "filesystem_uuid",
    )
    required_candidate = ("parent_root_uuid", "admission_base_uuid")
    if any(not isinstance(live.get(name), str) or not live.get(name) for name in required_live):
        raise ValueError("verified recovery generation evidence is incomplete")
    if any(not isinstance(candidate.get(name), str) or not candidate.get(name) for name in required_candidate):
        raise ValueError("candidate recovery prerequisite evidence is incomplete")
    if candidate["parent_root_uuid"] != live["root_subvolume_uuid"]:
        raise ValueError("candidate recovery parent does not match current verified generation")
    return {
        "ready": True,
        "kind": "verified-current-generation-plus-admission-base-v1",
        "generation_id": live.get("recovery_generation_id"),
        "current_system_generation_id": live["system_generation_id"],
        "current_kernel_generation_id": live["kernel_generation_id"],
        "root_subvolume_uuid": live["root_subvolume_uuid"],
        "filesystem_uuid": live["filesystem_uuid"],
        "candidate_parent_root_uuid": candidate["parent_root_uuid"],
        "admission_base_uuid": candidate["admission_base_uuid"],
    }


def _boot_identity(btrfs: NativeBtrfsOps) -> dict[str, Any]:
    cmdline = Path("/proc/cmdline").read_text(encoding="utf-8").strip()
    return {
        "unchanged": True,
        "sha256": btrfs.live_boot_hashes(),
        "cmdline_sha256": hashlib.sha256(cmdline.encode()).hexdigest(),
    }


class _OneShotNormalOps:
    fixture_safe = False
    production_safe = True

    def __init__(
        self, delegate: NormalProductionOps, *, state_root: Path,
        execution_authority: Any, candidate: Mapping[str, Any],
    ) -> None:
        self.delegate = delegate
        self.state_root = state_root
        self.execution_authority = execution_authority
        self.candidate = dict(candidate)
        self.consumed = False

    def install_candidate(self, plan: NormalExecutionPlan) -> Mapping[str, Any]:
        if self.consumed:
            raise RuntimeError("transaction execution authority replayed in-process")
        consume_execution_authority(
            self.state_root,
            self.execution_authority,
            candidate_uuid=str(self.candidate["uuid"]),
            candidate_root_identity=f"btrfs-uuid:{self.candidate['uuid']}",
        )
        self.consumed = True
        return self.delegate.install_candidate(plan)

    def guardian_admit(self, plan: NormalExecutionPlan) -> Mapping[str, Any]:
        return self.delegate.guardian_admit(plan)



def _freeze_normal_activation_bundle(
    admission: Any,
    *,
    transaction: Mapping[str, Any],
    candidate: Mapping[str, Any],
    source_revision: str,
    boot_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind one already-scanned immutable normal candidate for bounded reboot activation."""
    if admission.decision.outcome.value != "ALLOW" or admission.promotion_authority is None:
        raise RuntimeError("normal Guardian Admission did not authorize activation")
    boot_hashes = boot_identity.get("sha256")
    if not isinstance(boot_hashes, Mapping) or not boot_hashes:
        raise ValueError("normal activation boot identity is incomplete")
    payload = admission.as_dict()
    frozen = freeze_admission_evidence(
        admission,
        update_transaction_id=transaction["transaction_id"],
        transaction=transaction,
        source_revision=source_revision,
        candidate_btrfs_uuid=str(candidate["uuid"]),
        base_btrfs_uuid=str(candidate["admission_base_uuid"]),
        candidate_boot_sha256=boot_hashes,
        admission_payload=payload,
    )
    authority = issue_frozen_activation_authority(
        admission,
        frozen.as_dict(),
        update_transaction_id=transaction["transaction_id"],
        transaction=transaction,
        source_revision=source_revision,
    )
    approval = {
        "decision": admission.decision.as_dict(),
        "promotion_authority": admission.promotion_authority.as_dict(),
        "frozen_admission_evidence_id": str(frozen.evidence_id),
    }
    return {
        "activation_authority": authority.as_dict(),
        "admission_payload": payload,
        "frozen_admission": frozen.as_dict(),
        "admission_approval": approval,
    }

def execute_ready_normal(
    transaction: Mapping[str, Any],
    *,
    cache_root: Path,
    manifest_path: Path,
    maintenance_evidence: Mapping[str, Any],
    repository_evidence: Mapping[str, Any],
    repository_reobserve: Callable[[], Mapping[str, Any]],
    maintenance_reobserve: Callable[[], Mapping[str, Any]],
    state_root: Path,
    campaign_root: Path,
    generation_root: Path = GENERATION_ROOT,
    now: datetime | None = None,
    btrfs_factory: Callable[[str], NativeBtrfsOps] = NativeBtrfsOps,
    ops_factory: Callable[..., NormalProductionOps] = NormalProductionOps,
    installed_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    disk_usage: Callable[[str | os.PathLike[str]], Any] = shutil.disk_usage,
    package_lock_present: Callable[[], bool] = lambda: Path("/var/lib/pacman/db.lck").exists(),
    executor_value: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current = validate_transaction(transaction)
    if current["state"] != UpdateState.MAINTENANCE_READY.value:
        raise ValueError("automatic normal execution requires MAINTENANCE_READY")
    manifest = _read_json(manifest_path)
    validate_manifest(manifest, current, cache_root)
    plan = _plan(current)
    static_authority = load_normal_execution_authority(
        source_revision=current["source_revision"],
    )
    if read_execution_record(state_root, current["transaction_id"]) is not None:
        raise ValueError("automatic execution record already exists; restart recovery is required")
    live, system, kernel = load_current_verified_generations(generation_root)
    if not live.get("root_subvolume_uuid"):
        raise ValueError("verified live root identity is unavailable")

    btrfs = btrfs_factory(current["transaction_id"])
    candidate: dict[str, Any] | None = None
    pending_committed = False
    try:
        identity = btrfs.root_identity()
        if (
            identity.subvolume_uuid != live["root_subvolume_uuid"]
            or identity.filesystem_uuid.lower() != str(live.get("filesystem_uuid", "")).lower()
            or identity.fsroot != "/@"
        ):
            raise ValueError("live root drifted from current verified SystemGeneration")
        if not _installed_generation_current(current, runner=installed_runner):
            raise ValueError("live package generation drifted before candidate allocation")
        if package_lock_present():
            raise ValueError("concurrent_package_or_build_operation")
        disk = disk_reserve_evidence(current, cache_root, disk_usage=disk_usage)
        if disk["ok"] is not True:
            raise ValueError("safe_disk_reserve_unsatisfied")
        _repository_binding(repository_evidence, repository_reobserve())
        _maintenance_binding(maintenance_evidence, now=now)

        # Candidate allocation is reversible preparation. Package mutation has
        # not begun yet, so any final observation drift discards this candidate.
        candidate = btrfs.create_candidate()
        if candidate["parent_root_uuid"] != live["root_subvolume_uuid"]:
            raise ValueError("candidate parent is not current verified SystemGeneration")

        # Final pre-mutation re-observation. MAINTENANCE_READY does not live
        # forever: current generation, package state, repository metadata,
        # disk reserve and Adaptive safety are all re-proven here.
        live2, system2, kernel2 = load_current_verified_generations(generation_root)
        if (
            live2["system_generation_id"] != live["system_generation_id"]
            or live2["kernel_generation_id"] != live["kernel_generation_id"]
            or live2["root_subvolume_uuid"] != live["root_subvolume_uuid"]
        ):
            raise ValueError("current generation drifted before candidate mutation")
        identity2 = btrfs.root_identity()
        if identity2.subvolume_uuid != live2["root_subvolume_uuid"]:
            raise ValueError("live root drifted before candidate mutation")
        if not _installed_generation_current(current, runner=installed_runner):
            raise ValueError("live package generation drifted before candidate mutation")
        if package_lock_present():
            raise ValueError("concurrent_package_or_build_operation")
        disk = disk_reserve_evidence(current, cache_root, disk_usage=disk_usage)
        if disk["ok"] is not True:
            raise ValueError("safe_disk_reserve_unsatisfied")
        repository = _repository_binding(repository_evidence, repository_reobserve())
        maintenance = _maintenance_binding(maintenance_reobserve(), now=now)
        recovery = _recovery_evidence(live2, candidate)
        executor = dict(executor_value) if executor_value is not None else executor_identity(
            campaign_root, EXECUTOR_MODULES,
        )
        exact = issue_execution_authority(
            current,
            manifest,
            current_system_generation_id=str(system2.generation_id),
            current_kernel_generation_id=str(kernel2.kernel_generation_id),
            execution_mode="normal-candidate",
            effects=plan.effects,
            activation_requirements=plan.activation_requirements,
            candidate_target={
                "name": candidate["name"],
                "uuid": candidate["uuid"],
                "filesystem_uuid": candidate["filesystem_uuid"],
                "parent_root_uuid": candidate["parent_root_uuid"],
            },
            recovery_evidence=recovery,
            maintenance_evidence=maintenance,
            executor=executor,
            now=now,
        )
        publish_execution_authority(state_root, exact)
        verify_execution_authority(
            exact.as_dict(),
            current,
            manifest,
            current_system_generation_id=str(system2.generation_id),
            current_kernel_generation_id=str(kernel2.kernel_generation_id),
            execution_mode="normal-candidate",
            effects=plan.effects,
            activation_requirements=plan.activation_requirements,
            candidate_target=dict(exact.candidate_target),
            recovery_evidence=recovery,
            maintenance_evidence=maintenance,
            executor=executor,
            now=now,
        )
        record = {
            "schema_version": 1,
            "kind": "maho-automatic-normal-execution",
            "transaction_id": current["transaction_id"],
            "source_revision": current["source_revision"],
            "phase": "AUTHORIZED",
            "candidate": candidate,
            "plan": plan.as_dict(),
            "execution_authority": exact.as_dict(),
            "recovery_evidence": recovery,
            "maintenance_evidence": maintenance,
            "repository_evidence": repository,
            "disk_evidence": disk,
            "created_at": _stamp(now or datetime.now(timezone.utc)),
        }
        _atomic_json(record_path(state_root, current["transaction_id"]), record)

        delegate = ops_factory(
            transaction=current,
            cache_root=cache_root,
            btrfs=btrfs,
            candidate=candidate,
        )
        ops = _OneShotNormalOps(
            delegate,
            state_root=state_root,
            execution_authority=exact,
            candidate=candidate,
        )
        result = execute_normal_candidate(
            current,
            plan,
            ops,
            authority=static_authority,
            journal_path=transaction_path(state_root, current["transaction_id"]),
            candidate_state_root=btrfs.offline_root / "var/lib/maho/update",
            now=now,
        )
        if result.transaction["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value:
            cleanup = btrfs.cleanup_candidate(candidate["uuid"])
            failed = result.transaction
            publish_transaction(state_root, failed)
            record.update({
                "phase": failed["state"],
                "transaction_state": failed["state"],
                "candidate_cleanup": cleanup,
                "s3_recovery_invoked": False,
            })
            _atomic_json(record_path(state_root, current["transaction_id"]), record)
            return record

        if delegate.admission is None or delegate.roots is None:
            raise RuntimeError("normal Guardian Admission result is unavailable")
        boot_identity = _boot_identity(btrfs)
        frozen_bundle = _freeze_normal_activation_bundle(
            delegate.admission,
            transaction=result.transaction,
            candidate=candidate,
            source_revision=current["source_revision"],
            boot_identity=boot_identity,
        )
        activation_authority = frozen_bundle["activation_authority"]
        candidate_publication = publish_normal_candidate_generation(
            result.transaction,
            candidate=candidate,
            activation_authority=activation_authority,
            recovery_evidence=recovery,
            candidate_boot_identity=boot_identity,
            root=generation_root,
        )
        handoff = issue_activation_handoff(
            result.transaction,
            current_system_generation_id=str(system2.generation_id),
            candidate_system_generation_id=candidate_publication["system_generation_id"],
            candidate_kernel_generation_id=candidate_publication["kernel_generation_id"],
            candidate_uuid=candidate["uuid"],
            previous_root_uuid=candidate["parent_root_uuid"],
            activation_authority=activation_authority,
            recovery_evidence=recovery,
            candidate_boot_identity=boot_identity,
            reboot_required=True,
            reboot_reason="normal candidate root activation requires an explicit reboot",
            now=now,
        )
        publish_activation_handoff(state_root, handoff)
        record.update({
            "phase": "INSTALLED_PENDING_ACTIVATION",
            "transaction_state": result.transaction["state"],
            "activation_authority": activation_authority,
            "admission_payload": frozen_bundle["admission_payload"],
            "frozen_admission": frozen_bundle["frozen_admission"],
            "admission_approval": frozen_bundle["admission_approval"],
            "candidate_generation": candidate_publication,
            "activation_handoff": handoff.as_dict(),
            "reboot_performed": False,
        })
        _atomic_json(record_path(state_root, current["transaction_id"]), record)
        # Only after exact candidate generation + activation handoff are durable
        # does the host transaction become pending activation.
        publish_transaction(state_root, result.transaction)
        pending_committed = True
        return record
    except Exception as exc:
        try:
            durable = read_transaction(
                transaction_path(state_root, current["transaction_id"])
            )
        except Exception:
            durable = None

        # The last publish can be interrupted after the transaction file is
        # durable but before publish_transaction returns.  Because the current
        # pointer already names this exact transaction, a durable pending state
        # plus durable generation/handoff record is an idempotent completed
        # commit, not a reason to delete the candidate.
        if (
            candidate is not None
            and durable is not None
            and durable["state"] == UpdateState.INSTALLED_PENDING_ACTIVATION.value
        ):
            committed = read_execution_record(state_root, current["transaction_id"])
            handoff = handoff_path(state_root, current["transaction_id"])
            if (
                isinstance(committed, Mapping)
                and committed.get("phase") == "INSTALLED_PENDING_ACTIVATION"
                and isinstance(committed.get("candidate_generation"), Mapping)
                and isinstance(committed.get("activation_handoff"), Mapping)
                and handoff.is_file()
            ):
                pending_committed = True
                reconciled = dict(committed)
                reconciled["final_publish_reconciled"] = True
                reconciled["final_publish_error"] = str(exc)
                _atomic_json(
                    record_path(state_root, current["transaction_id"]),
                    reconciled,
                )
                return reconciled

        cleanup: Mapping[str, Any] | None = None
        if candidate is not None and not pending_committed:
            try:
                cleanup = btrfs.cleanup_candidate(str(candidate["uuid"]))
            except Exception as cleanup_exc:
                cleanup = {"ok": False, "error": str(cleanup_exc)}
        if (
            durable is not None
            and cleanup is not None
            and cleanup.get("ok") is True
        ):
            try:
                if durable["state"] == UpdateState.INSTALLING.value:
                    failed = transition_transaction(
                        durable,
                        UpdateState.FAILED_RECOVERABLE,
                        reason="isolated normal candidate execution aborted before activation handoff",
                        evidence={
                            "failure_code": "normal_candidate_execution_aborted",
                            "error": str(exc),
                            "candidate_cleanup": dict(cleanup),
                            "live_root_mutation": False,
                            "s3_recovery_invoked": False,
                        },
                        now=now,
                    )
                    publish_transaction(state_root, failed)
                elif durable["state"] == UpdateState.MAINTENANCE_READY.value:
                    blocked = transition_transaction(
                        durable,
                        UpdateState.BLOCKED,
                        reason="one-shot execution attempt aborted before mutation completed",
                        blockers=["normal_execution_attempt_aborted"],
                        evidence={
                            "error": str(exc),
                            "candidate_cleanup": dict(cleanup),
                            "live_root_mutation": False,
                        },
                        now=now,
                    )
                    publish_transaction(state_root, blocked)
            except Exception:
                pass
        if candidate is not None:
            failed_record = read_execution_record(
                state_root, current["transaction_id"]
            ) or {
                "schema_version": 1,
                "kind": "maho-automatic-normal-execution",
                "transaction_id": current["transaction_id"],
                "source_revision": current["source_revision"],
                "created_at": _stamp(now or datetime.now(timezone.utc)),
            }
            failed_record.update({
                "phase": "ABORTED_BEFORE_ACTIVATION",
                "candidate": candidate,
                "candidate_cleanup": dict(cleanup or {}),
                "error": str(exc),
                "s3_recovery_invoked": False,
            })
            try:
                _atomic_json(
                    record_path(state_root, current["transaction_id"]),
                    failed_record,
                )
            except Exception:
                pass
        raise
    finally:
        btrfs.close()



def _restore_record_from_previous_root(
    transaction: Mapping[str, Any],
    *,
    state_root: Path,
    generation_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = validate_transaction(transaction)
    relative = (
        f"var/lib/maho/update/automatic-executions/"
        f"{current['transaction_id']}.json"
    )
    btrfs = NativeBtrfsOps(current["transaction_id"])
    try:
        evidence = btrfs.read_activation_source_file(relative)
    finally:
        btrfs.close()
    try:
        value = json.loads(bytes(evidence["content"]).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("previous-root automatic execution record is invalid") from exc
    if not isinstance(value, Mapping):
        raise ValueError("previous-root automatic execution record is not an object")
    record = dict(value)
    candidate = record.get("candidate")
    handoff = record.get("activation_handoff")
    if (
        record.get("schema_version") != 1
        or record.get("kind") != "maho-automatic-normal-execution"
        or record.get("transaction_id") != current["transaction_id"]
        or record.get("source_revision") != current["source_revision"]
        or record.get("phase") not in {
            "INSTALLED_PENDING_ACTIVATION", "ACTIVATION_ARMED",
        }
        or not isinstance(candidate, Mapping)
        or not isinstance(handoff, Mapping)
        or candidate.get("uuid") != evidence.get("active_root_uuid")
        or candidate.get("parent_root_uuid") != evidence.get("previous_root_uuid")
    ):
        raise ValueError("previous-root automatic execution record binding mismatch")
    _live, system, _kernel = load_current_verified_generations(generation_root)
    parsed_handoff = verify_activation_handoff_reconciliation(
        handoff,
        current,
        current_system_generation_id=str(system.generation_id),
    )
    if (
        parsed_handoff.candidate_uuid != candidate.get("uuid")
        or parsed_handoff.previous_root_uuid != candidate.get("parent_root_uuid")
    ):
        raise ValueError("previous-root activation handoff binding mismatch")
    _atomic_json(record_path(state_root, current["transaction_id"]), record)
    return record


def _ensure_candidate_generation_after_activation(
    transaction: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    generation_root: Path,
) -> dict[str, Any]:
    current = validate_transaction(transaction)
    expected = record.get("candidate_generation")
    candidate = record.get("candidate")
    authority = record.get("activation_authority")
    recovery = record.get("recovery_evidence")
    boot = record.get("candidate_boot_identity")
    if not all(isinstance(item, Mapping) for item in (
        expected, candidate, authority, recovery, boot,
    )):
        raise ValueError("post-activation candidate generation evidence is incomplete")
    publication = read_candidate_publication(current["transaction_id"], generation_root)
    if publication is None:
        live, _system, _kernel = load_current_verified_generations(generation_root)
        if (
            live.get("system_generation_id") == expected.get("system_generation_id")
            and live.get("kernel_generation_id") == expected.get("kernel_generation_id")
            and live.get("root_subvolume_uuid") == candidate.get("uuid")
        ):
            publication = dict(expected)
        else:
            publication = publish_normal_candidate_generation(
                current,
                candidate=candidate,
                activation_authority=authority,
                recovery_evidence=recovery,
                candidate_boot_identity=boot,
                root=generation_root,
            )
    if (
        publication.get("system_generation_id") != expected.get("system_generation_id")
        or publication.get("kernel_generation_id") != expected.get("kernel_generation_id")
        or publication.get("candidate_uuid") != candidate.get("uuid")
    ):
        raise ValueError("reconstructed candidate generation identity mismatch")
    return publication


def _finalize_pending_record(
    transaction: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    state_root: Path,
    generation_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = validate_transaction(transaction)
    if current["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value:
        raise ValueError("normal handoff finalization requires pending activation")
    candidate = record.get("candidate")
    if not isinstance(candidate, Mapping):
        raise ValueError("normal pending candidate evidence is unavailable")
    live, system, kernel = load_current_verified_generations(generation_root)
    if live["root_subvolume_uuid"] != candidate.get("parent_root_uuid"):
        raise ValueError("verified live generation drifted before handoff finalization")
    recovery = record.get("recovery_evidence")
    if not isinstance(recovery, Mapping) or recovery.get("ready") is not True:
        recovery = _recovery_evidence(live, candidate)

    btrfs = NativeBtrfsOps(current["transaction_id"])
    try:
        paths = btrfs.admission_roots(
            str(candidate["uuid"]),
            str(candidate["admission_base_uuid"]),
        )
        roots = CandidateRoots.create(
            transaction_id=guardian_transaction_id(current["transaction_id"]),
            candidate_id=str(candidate["uuid"]),
            base_root=paths["base_root"],
            candidate_root=paths["candidate_root"],
        )
        admission = evaluate_normal_production_candidate(
            roots,
            current,
            operational_paths=(
                f"/var/lib/maho/update/transactions/{current['transaction_id']}.json",
                "/var/lib/maho/update/current",
            ),
        )
        if admission.decision.outcome.value != "ALLOW" or admission.promotion_authority is None:
            raise RuntimeError("frozen normal candidate no longer has Guardian ALLOW")
        boot_identity = _boot_identity(btrfs)
        frozen_bundle = _freeze_normal_activation_bundle(
            admission,
            transaction=current,
            candidate=candidate,
            source_revision=current["source_revision"],
            boot_identity=boot_identity,
        )
        activation_authority = frozen_bundle["activation_authority"]
        candidate_publication = publish_normal_candidate_generation(
            current,
            candidate=candidate,
            activation_authority=activation_authority,
            recovery_evidence=recovery,
            candidate_boot_identity=boot_identity,
            root=generation_root,
        )
        handoff = issue_activation_handoff(
            current,
            current_system_generation_id=str(system.generation_id),
            candidate_system_generation_id=candidate_publication["system_generation_id"],
            candidate_kernel_generation_id=str(kernel.kernel_generation_id),
            candidate_uuid=str(candidate["uuid"]),
            previous_root_uuid=str(candidate["parent_root_uuid"]),
            activation_authority=activation_authority,
            recovery_evidence=recovery,
            candidate_boot_identity=boot_identity,
            reboot_required=True,
            reboot_reason="normal candidate root activation requires an explicit reboot",
            now=now,
        )
        publish_activation_handoff(state_root, handoff)
    finally:
        btrfs.close()
    updated = dict(record)
    updated.update({
        "phase": "INSTALLED_PENDING_ACTIVATION",
        "transaction_state": current["state"],
        "activation_authority": activation_authority,
        "admission_payload": frozen_bundle["admission_payload"],
        "frozen_admission": frozen_bundle["frozen_admission"],
        "admission_approval": frozen_bundle["admission_approval"],
        "candidate_generation": candidate_publication,
        "activation_handoff": handoff.as_dict(),
        "reboot_performed": False,
        "handoff_reconstructed": record.get("phase") != "INSTALLED_PENDING_ACTIVATION",
    })
    _atomic_json(record_path(state_root, current["transaction_id"]), updated)
    return updated


def finalize_pending_normal(
    transaction_id: str,
    *,
    state_root: Path,
    generation_root: Path = GENERATION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    transaction = read_transaction(transaction_path(state_root, transaction_id))
    record = read_execution_record(state_root, transaction_id)
    if not record:
        record = _restore_record_from_previous_root(
            transaction,
            state_root=state_root,
            generation_root=generation_root,
            now=now,
        )
    if (
        record.get("phase") in {"INSTALLED_PENDING_ACTIVATION", "ACTIVATION_ARMED"}
        and isinstance(record.get("activation_handoff"), Mapping)
    ):
        if record.get("phase") == "INSTALLED_PENDING_ACTIVATION":
            candidate = record.get("candidate")
            if not isinstance(candidate, Mapping):
                raise ValueError("normal pending candidate evidence is unavailable")
            btrfs = NativeBtrfsOps(transaction_id)
            try:
                topology = btrfs.normal_activation_topology(
                    expected_candidate_uuid=str(candidate.get("uuid")),
                    expected_parent_root_uuid=str(candidate.get("parent_root_uuid")),
                )
            finally:
                btrfs.close()
            if topology == "PREPARED_MUTABLE":
                raise RuntimeError(
                    "normal activation candidate became mutable before root exchange; "
                    "frozen activation authority is no longer valid"
                )
            if topology in {"EXCHANGED_PENDING_BACKUP", "ARMED"}:
                arm_normal_activation(
                    transaction_id,
                    state_root=state_root,
                    generation_root=generation_root,
                    now=now,
                )
                record = read_execution_record(state_root, transaction_id) or record
        if record.get("phase") == "ACTIVATION_ARMED":
            publication = _ensure_candidate_generation_after_activation(
                transaction, record, generation_root=generation_root,
            )
            updated = dict(record)
            updated["candidate_generation"] = publication
            updated["post_activation_evidence_restored"] = True
            _atomic_json(record_path(state_root, transaction_id), updated)
            return updated
        return record
    return _finalize_pending_record(
        transaction,
        record,
        state_root=state_root,
        generation_root=generation_root,
        now=now,
    )


def recover_interrupted_normal_execution(
    transaction_id: str,
    *,
    state_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    transaction = read_transaction(transaction_path(state_root, transaction_id))
    if transaction["state"] != UpdateState.INSTALLING.value:
        raise ValueError("interrupted normal recovery requires INSTALLING state")
    record = read_execution_record(state_root, transaction_id)
    candidate = record.get("candidate") if isinstance(record, Mapping) else None
    if not isinstance(candidate, Mapping):
        attention = transition_transaction(
            transaction,
            UpdateState.ATTENTION_REQUIRED,
            reason="interrupted normal execution lost exact candidate identity",
            blockers=["normal_interrupted_candidate_identity_missing"],
            now=now,
        )
        publish_transaction(state_root, attention)
        return {"phase": attention["state"], "transaction": attention}

    btrfs = NativeBtrfsOps(transaction_id)
    try:
        cleanup = btrfs.cleanup_candidate(str(candidate["uuid"]))
    finally:
        btrfs.close()
    if cleanup.get("ok") is not True:
        attention = transition_transaction(
            transaction,
            UpdateState.ATTENTION_REQUIRED,
            reason="interrupted normal candidate could not be safely discarded",
            blockers=["normal_interrupted_candidate_cleanup_failed"],
            evidence={"candidate_cleanup": cleanup},
            now=now,
        )
        publish_transaction(state_root, attention)
        return {"phase": attention["state"], "transaction": attention, "candidate_cleanup": cleanup}
    failed = transition_transaction(
        transaction,
        UpdateState.FAILED_RECOVERABLE,
        reason="normal execution interrupted before activation; isolated candidate discarded",
        evidence={
            "failure_code": "normal_execution_interrupted",
            "candidate_cleanup": cleanup,
            "live_root_mutation": False,
            "s3_recovery_invoked": False,
        },
        now=now,
    )
    publish_transaction(state_root, failed)
    if isinstance(record, Mapping):
        updated = dict(record)
        updated.update({
            "phase": UpdateState.FAILED_RECOVERABLE.value,
            "transaction_state": failed["state"],
            "candidate_cleanup": cleanup,
            "s3_recovery_invoked": False,
        })
        _atomic_json(record_path(state_root, transaction_id), updated)
    return {
        "phase": UpdateState.FAILED_RECOVERABLE.value,
        "transaction": failed,
        "candidate_cleanup": cleanup,
        "replayed": False,
        "s3_recovery_invoked": False,
    }

def arm_normal_activation(
    transaction_id: str,
    *,
    state_root: Path,
    generation_root: Path = GENERATION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    transaction = read_transaction(transaction_path(state_root, transaction_id))
    if transaction["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value:
        raise ValueError("normal activation requires INSTALLED_PENDING_ACTIVATION")
    record = read_execution_record(state_root, transaction_id)
    if not record or record.get("phase") not in {"INSTALLED_PENDING_ACTIVATION", "ACTIVATION_ARMED"}:
        raise ValueError("normal automatic execution record is unavailable")
    candidate = record.get("candidate")
    authority = record.get("activation_authority")
    handoff_value = record.get("activation_handoff")
    candidate_generation = record.get("candidate_generation")
    if not all(isinstance(item, Mapping) for item in (
        candidate, authority, handoff_value, candidate_generation,
    )):
        raise ValueError("normal activation evidence is incomplete")

    live, system, _kernel = load_current_verified_generations(generation_root)
    parsed_handoff = parse_activation_handoff(handoff_value)
    if (
        parsed_handoff.candidate_system_generation_id
        != candidate_generation.get("system_generation_id")
        or parsed_handoff.candidate_kernel_generation_id
        != candidate_generation.get("kernel_generation_id")
        or parsed_handoff.candidate_uuid != candidate.get("uuid")
        or parsed_handoff.previous_root_uuid != candidate.get("parent_root_uuid")
    ):
        raise ValueError("activation handoff candidate generation binding mismatch")

    btrfs = NativeBtrfsOps(transaction_id)
    try:
        topology = btrfs.normal_activation_topology(
            expected_candidate_uuid=parsed_handoff.candidate_uuid,
            expected_parent_root_uuid=parsed_handoff.previous_root_uuid,
        )
        if topology == "PREPARED":
            handoff = verify_activation_handoff(
                handoff_value,
                transaction,
                current_system_generation_id=str(system.generation_id),
                now=now,
            )
            if live["root_subvolume_uuid"] != handoff.previous_root_uuid:
                raise ValueError("live root drifted before explicit activation")
            prepared_state_root = btrfs.prepared_candidate_state_root(
                expected_candidate_uuid=handoff.candidate_uuid,
                expected_parent_root_uuid=handoff.previous_root_uuid,
            )
            if handoff_consumption_path(prepared_state_root, handoff.handoff_id).exists():
                raise ValueError("unperformed activation already has a consumption receipt")
            paths = btrfs.admission_roots(
                str(candidate["uuid"]),
                str(candidate["admission_base_uuid"]),
            )
            roots = CandidateRoots.create(
                transaction_id=guardian_transaction_id(transaction_id),
                candidate_id=str(candidate["uuid"]),
                base_root=paths["base_root"],
                candidate_root=paths["candidate_root"],
            )
            frozen_admission = record.get("frozen_admission")
            admission_payload = record.get("admission_payload")
            admission_approval = record.get("admission_approval")
            if not all(isinstance(item, Mapping) for item in (
                frozen_admission, admission_payload, admission_approval,
            )):
                raise ValueError("normal activation frozen Admission evidence is incomplete")
            expected_boot_hashes = dict(handoff.candidate_boot_identity.get("sha256", {}))
            verified = verify_frozen_activation_authority(
                authority,
                frozen_admission,
                admission_payload,
                admission_approval,
                roots=roots,
                update_transaction_id=transaction_id,
                transaction=transaction,
                source_revision=transaction["source_revision"],
                candidate_btrfs_uuid=str(paths["candidate_uuid"]),
                base_btrfs_uuid=str(paths["base_uuid"]),
                candidate_boot_sha256=expected_boot_hashes,
            )
            if btrfs.live_boot_hashes() != expected_boot_hashes:
                raise ValueError("live boot identity drifted before normal activation")
            activation = btrfs.arm_root_activation(
                expected_candidate_uuid=handoff.candidate_uuid,
                expected_parent_root_uuid=handoff.previous_root_uuid,
            )
            activation["admission_authority_id"] = str(verified.authority_id)
        elif topology == "EXCHANGED_PENDING_BACKUP":
            handoff = verify_activation_handoff_reconciliation(
                handoff_value,
                transaction,
                current_system_generation_id=str(system.generation_id),
            )
            activation = btrfs.finalize_normal_activation_exchange(
                expected_candidate_uuid=handoff.candidate_uuid,
                expected_parent_root_uuid=handoff.previous_root_uuid,
                expected_boot_hashes=dict(
                    handoff.candidate_boot_identity.get("sha256", {})
                ),
            )
        elif topology == "ARMED":
            handoff = verify_activation_handoff_reconciliation(
                handoff_value,
                transaction,
                current_system_generation_id=str(system.generation_id),
            )
            activation = {
                "candidate_uuid": handoff.candidate_uuid,
                "previous_root_uuid": handoff.previous_root_uuid,
                "previous_root_name": btrfs.backup,
                "boot_sha256": btrfs.live_boot_hashes(),
                "boot_unchanged": True,
                "package_manager_invoked": False,
                "reboot_performed": False,
                "firmware_mutated": False,
                "reconciled_after_interruption": True,
            }
        else:
            raise RuntimeError("normal activation topology is unsafe")

        activated_state_root = btrfs.activated_state_root(
            expected_candidate_uuid=handoff.candidate_uuid,
            expected_parent_root_uuid=handoff.previous_root_uuid,
        )
        try:
            consumption = consume_activation_handoff(
                activated_state_root,
                handoff,
                activation_evidence=activation,
                now=now,
            )
            consumption = read_activation_handoff_consumption(
                activated_state_root, handoff,
            )
        except ValueError as exc:
            if "already consumed" not in str(exc) or topology != "ARMED":
                raise
            consumption = read_activation_handoff_consumption(
                activated_state_root, handoff,
            )
            consumption["replayed"] = True
        record = dict(record)
        record.update({
            "phase": "ACTIVATION_ARMED",
            "activation": activation,
            "handoff_consumption": consumption,
            "reboot_performed": False,
        })
        _atomic_json(record_path(activated_state_root, transaction_id), record)
        return {
            "transaction_id": transaction_id,
            "phase": "ACTIVATION_ARMED",
            "candidate_uuid": handoff.candidate_uuid,
            "candidate_system_generation_id": handoff.candidate_system_generation_id,
            "reboot_performed": False,
            "next_action": "continue explicit reboot; postboot verification remains separate",
        }
    finally:
        btrfs.close()


def _candidate_package_versions(
    transaction: Mapping[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, str]:
    tx = validate_transaction(transaction)
    names = [item["name"] for item in tx["package_generation"]["packages"]]
    completed = runner(
        ["pacman", "-Q", "--", *names],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("postboot package generation query failed")
    observed: dict[str, str] = {}
    for line in completed.stdout.splitlines():
        name, separator, version = line.partition(" ")
        if separator:
            observed[name] = version.strip()
    expected = {
        item["name"]: item["candidate_version"]
        for item in tx["package_generation"]["packages"]
    }
    if observed != expected:
        raise RuntimeError("postboot package generation does not match candidate")
    return observed


def verify_activated_normal(
    transaction_id: str,
    *,
    state_root: Path,
    generation_root: Path = GENERATION_ROOT,
    now: datetime | None = None,
    package_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    running_kernel: Callable[[], str] = lambda: os.uname().release,
    cmdline_path: Path = Path("/proc/cmdline"),
) -> dict[str, Any]:
    """Independently verify and publish one already-armed normal candidate."""
    transaction = read_transaction(transaction_path(state_root, transaction_id))
    if transaction["state"] not in {
        UpdateState.INSTALLED_PENDING_ACTIVATION.value,
        UpdateState.ACTIVE_VERIFYING.value,
        UpdateState.HEALTHY.value,
    }:
        raise ValueError("normal postboot verification requires an activated transaction")
    record = read_execution_record(state_root, transaction_id)
    if not record or record.get("phase") not in {"ACTIVATION_ARMED", "POSTBOOT_VERIFIED"}:
        raise ValueError("normal postboot activation record is unavailable")
    candidate = record.get("candidate")
    handoff_value = record.get("activation_handoff")
    if not isinstance(candidate, Mapping) or not isinstance(handoff_value, Mapping):
        raise ValueError("normal postboot activation evidence is incomplete")
    handoff = parse_activation_handoff(handoff_value)
    if (
        handoff.transaction_id != transaction_id
        or handoff.source_revision != transaction["source_revision"]
        or handoff.package_generation_id != transaction["package_generation"]["id"]
        or handoff.candidate_uuid != candidate.get("uuid")
        or handoff.previous_root_uuid != candidate.get("parent_root_uuid")
    ):
        raise ValueError("normal postboot handoff binding mismatch")

    btrfs = NativeBtrfsOps(transaction_id)
    try:
        topology = btrfs.normal_activation_topology(
            expected_candidate_uuid=handoff.candidate_uuid,
            expected_parent_root_uuid=handoff.previous_root_uuid,
        )
        if topology != "ARMED":
            raise RuntimeError("normal postboot root topology is not armed")
        identity = btrfs.root_identity()
        if (
            identity.subvolume_uuid != handoff.candidate_uuid
            or identity.filesystem_uuid.lower() != str(candidate.get("filesystem_uuid", "")).lower()
            or identity.fsroot != "/@"
        ):
            raise RuntimeError("normal postboot active root identity mismatch")
        receipt = read_activation_handoff_consumption(state_root, handoff)
        expected_boot = dict(handoff.candidate_boot_identity.get("sha256", {}))
        observed_boot = btrfs.live_boot_hashes()
        if observed_boot != expected_boot:
            raise RuntimeError("normal postboot boot identity drifted")
    finally:
        btrfs.close()

    cmdline = cmdline_path.read_text(encoding="utf-8").split()
    if "maho.recovery_snapshot=1" in cmdline:
        raise RuntimeError("normal postboot verification observed recovery boot")
    packages = _candidate_package_versions(transaction, runner=package_runner)
    live, _system, kernel = load_current_verified_generations(generation_root)
    candidate_publication = _ensure_candidate_generation_after_activation(
        transaction, record, generation_root=generation_root,
    )
    if (
        live.get("root_subvolume_uuid") not in {
            handoff.previous_root_uuid, handoff.candidate_uuid,
        }
        or candidate_publication.get("system_generation_id")
        != handoff.candidate_system_generation_id
        or candidate_publication.get("kernel_generation_id")
        != handoff.candidate_kernel_generation_id
    ):
        raise RuntimeError("normal postboot generation binding mismatch")
    observed_kernel = running_kernel()
    if observed_kernel != kernel.kernel_abi:
        raise RuntimeError("normal postboot running kernel drifted")

    verifier_identity = f"maho-normal-postboot:{transaction['source_revision']}"
    if transaction["state"] == UpdateState.INSTALLED_PENDING_ACTIVATION.value:
        transaction = transition_transaction(
            transaction,
            UpdateState.ACTIVE_VERIFYING,
            reason="exact normal candidate booted; independent verification started",
            evidence={
                "candidate_uuid": handoff.candidate_uuid,
                "previous_root_uuid": handoff.previous_root_uuid,
                "previous_root_read_only": True,
                "handoff_id": handoff.handoff_id,
            },
            now=now,
        )
        publish_transaction(state_root, transaction)
    if transaction["state"] == UpdateState.ACTIVE_VERIFYING.value:
        transaction = transition_transaction(
            transaction,
            UpdateState.HEALTHY,
            reason="normal candidate passed exact postboot verification",
            evidence={
                "candidate_uuid": handoff.candidate_uuid,
                "package_versions": packages,
                "boot_sha256": observed_boot,
                "recovery_invoked": False,
                "handoff_consumption": receipt,
            },
            now=now,
        )
        publish_transaction(state_root, transaction)
    live = promote_normal_candidate_generation(
        transaction,
        live_root_uuid=handoff.candidate_uuid,
        filesystem_uuid=str(candidate["filesystem_uuid"]),
        running_kernel_abi=observed_kernel,
        package_versions=packages,
        boot_sha256=observed_boot,
        verifier_identity=verifier_identity,
        root=generation_root,
    )
    verified_record = dict(record)
    verified_record.update({
        "phase": "POSTBOOT_VERIFIED",
        "transaction_state": UpdateState.HEALTHY.value,
        "postboot_verification": {
            "root_uuid": handoff.candidate_uuid,
            "previous_root_uuid": handoff.previous_root_uuid,
            "previous_root_read_only": True,
            "package_versions": packages,
            "boot_sha256": observed_boot,
            "system_generation_id": live["system_generation_id"],
            "verifier_identity": verifier_identity,
            "recovery_invoked": False,
        },
        "reboot_performed": True,
    })
    _atomic_json(record_path(state_root, transaction_id), verified_record)
    return {
        "transaction_id": transaction_id,
        "phase": UpdateState.HEALTHY.value,
        "root_uuid": handoff.candidate_uuid,
        "previous_root_uuid": handoff.previous_root_uuid,
        "previous_root_read_only": True,
        "system_generation_id": live["system_generation_id"],
        "package_versions": packages,
        "recovery_invoked": False,
    }


def activate_current_pending(
    *,
    state_root: Path,
    generation_root: Path = GENERATION_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    pointer = state_root / "current"
    try:
        transaction_id = pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return {"phase": "NO_PENDING_ACTIVATION", "activation_attempted": False}
    transaction = read_transaction(transaction_path(state_root, transaction_id))
    if transaction["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value:
        return {
            "transaction_id": transaction_id,
            "phase": transaction["state"],
            "activation_attempted": False,
        }
    record = read_execution_record(state_root, transaction_id)
    if not record:
        return {
            "transaction_id": transaction_id,
            "phase": "PENDING_WITHOUT_LOCAL_HANDOFF",
            "activation_attempted": False,
        }
    if record.get("phase") == "ACTIVATION_ARMED":
        return {
            "transaction_id": transaction_id,
            "phase": "ACTIVATION_ARMED",
            "activation_attempted": False,
        }
    return arm_normal_activation(
        transaction_id,
        state_root=state_root,
        generation_root=generation_root,
        now=now,
    )
