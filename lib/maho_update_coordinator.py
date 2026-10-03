#!/usr/bin/env python3
"""Always-on S2.1 coordinator for safe automatic MahoOS update preparation."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import stat
from typing import Any, Mapping

from maho_runtime_release import verify_release
from maho_update_campaign import (
    _generation_is_current,
    _power_evidence,
    _repo_contract,
    _root,
    _source_revision,
    prepare_native_campaign,
)
from maho_update_discovery import (
    IsolatedPacmanDiscovery,
    discover_independent_normal_updates,
    discover_updates,
)
from maho_update_maintenance import MaintenanceContext, evaluate_maintenance
from maho_update_native import NativeBtrfsOps
from maho_update_normal import NormalPreparationEvidence, prepare_normal_transaction
from maho_update_normal_authority import authorize_normal_plan, load_normal_execution_authority
from maho_update_staging import IsolatedPacmanStaging, stage_transaction, validate_manifest
from maho_update_state import (
    UpdateState,
    new_transaction_id,
    publish_transaction,
    read_transaction,
    transaction_path,
    transition_transaction,
    validate_transaction,
)

SCHEMA_VERSION = 1
CAMPAIGN_LOCK = Path("/run/lock/maho-update-campaign.lock")
DEFAULT_STATE_ROOT = Path("/var/lib/maho/update")
DEFAULT_WORK_ROOT = Path("/var/cache/maho/update-auto")
DISCOVERY_INTERVAL = timedelta(minutes=30)
REPOSITORY_EVIDENCE_MAX_AGE = timedelta(minutes=30)
ADAPTIVE_EVIDENCE_MAX_AGE = timedelta(seconds=90)
SAFE_STORAGE_RESERVE_BYTES = 2 * 1024 * 1024 * 1024
PREPARATION_OVERHEAD_BYTES = 512 * 1024 * 1024
MAX_RETRY = timedelta(hours=1)
_TXID = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")


class CoordinatorBusy(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    return Path(os.environ.get("MAHO_UPDATE_STATE_ROOT", str(DEFAULT_STATE_ROOT)))


def work_root() -> Path:
    return Path(os.environ.get("MAHO_UPDATE_AUTO_WORK_ROOT", str(DEFAULT_WORK_ROOT)))


def campaign_root() -> Path:
    return Path(__file__).resolve().parent.parent


def coordinator_path(root: Path | None = None) -> Path:
    return (root or state_root()) / "coordinator.json"


def _require_root() -> None:
    if os.geteuid() != 0 and os.environ.get("MAHO_UPDATE_COORDINATOR_TEST") != "1":
        raise PermissionError("automatic maintenance coordinator requires root")


def _atomic_json(path: Path, payload: Mapping[str, Any], mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, mode)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return dict(value) if isinstance(value, Mapping) else None


def read_coordinator_state(root: Path | None = None) -> dict[str, Any] | None:
    value = _read_json(coordinator_path(root))
    if value is None or value.get("schema_version") != SCHEMA_VERSION:
        return None
    return value


def _base_state(now: datetime, source_revision: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "maho-automatic-maintenance-coordinator",
        "source_revision": source_revision,
        "phase": "IDLE",
        "last_attempt_at": stamp(now),
        "last_success_at": None,
        "last_discovery_success_at": None,
        "last_preparation_success_at": None,
        "repository_observed_at": None,
        "repository_hashes": {},
        "active_transaction_id": None,
        "package_generation_id": None,
        "lane": None,
        "candidate_count": 0,
        "deferred_boot_packages": [],
        "first_observed_at": None,
        "update_debt_seconds": 0,
        "blockers": [],
        "last_error": None,
        "failure_count": 0,
        "next_retry_at": None,
        "next_discovery_at": None,
        "maintenance_evidence": None,
        "runtime_identity": None,
        "normal_execution_authority": "unknown",
        "live_root_mutation_started": False,
        "reboot_performed": False,
    }


def _save(state: Mapping[str, Any], root: Path | None = None) -> dict[str, Any]:
    value = dict(state)
    _atomic_json(coordinator_path(root), value, 0o644)
    return value


def _debt_seconds(state: Mapping[str, Any], now: datetime) -> int:
    first = parse_stamp(state.get("first_observed_at"))
    if first is None:
        return 0
    return max(0, int((now - first).total_seconds()))


def _with_debt(state: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    value = dict(state)
    value["update_debt_seconds"] = _debt_seconds(value, now)
    return value


def _retry_delay(failures: int) -> timedelta:
    seconds = min(int(MAX_RETRY.total_seconds()), 300 * (2 ** max(0, min(failures - 1, 8))))
    return timedelta(seconds=seconds)


def _record_failure(
    state: Mapping[str, Any],
    now: datetime,
    source_revision: str,
    blocker: str,
    detail: str,
) -> dict[str, Any]:
    value = dict(state) if state else _base_state(now, source_revision)
    failures = int(value.get("failure_count") or 0) + 1
    value.update({
        "schema_version": SCHEMA_VERSION,
        "source_revision": source_revision,
        "phase": "BLOCKED",
        "last_attempt_at": stamp(now),
        "blockers": [blocker],
        "last_error": detail[:4000],
        "failure_count": failures,
        "next_retry_at": stamp(now + _retry_delay(failures)),
        "live_root_mutation_started": False,
        "reboot_performed": False,
    })
    return _save(_with_debt(value, now))


@contextmanager
def coordinator_mutex(path: Path = CAMPAIGN_LOCK):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CoordinatorBusy("update_campaign_busy") from exc
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _validate_user(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}", name):
        raise RuntimeError("automatic maintenance user identity is invalid")
    record = pwd.getpwnam(name)
    if record.pw_uid == 0 or record.pw_dir != f"/home/{name}":
        raise RuntimeError("automatic maintenance user home is unsafe")
    return name


def _coordinator_user() -> str:
    explicit = os.environ.get("MAHO_UPDATE_USER") or os.environ.get("SUDO_USER")
    if explicit:
        return _validate_user(explicit)
    candidates: list[str] = []
    home_root = Path("/home")
    if home_root.is_dir():
        for home in sorted(home_root.iterdir()):
            if not home.is_dir():
                continue
            try:
                name = _validate_user(home.name)
                verification = verify_release(
                    home / ".local/share/maho/runtime/current",
                    home / ".local/share/maho/runtime/releases",
                )
            except (KeyError, OSError, RuntimeError, ValueError):
                continue
            if verification.verified:
                candidates.append(name)
    if len(candidates) != 1:
        raise RuntimeError("automatic maintenance requires exactly one verified Maho user")
    return candidates[0]


def _runtime_identity(user: str) -> dict[str, Any]:
    base = Path("/home") / user / ".local/share/maho/runtime"
    verification = verify_release(base / "current", base / "releases")
    if not verification.verified or not verification.content_sha256 or not verification.source_revision:
        raise RuntimeError("current immutable Maho runtime is not verified")
    return verification.as_dict()


def _normal_plan_scope(transaction: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    current = validate_transaction(transaction)
    for event in reversed(current["history"]):
        if event.get("state") != UpdateState.PREPARED.value:
            continue
        evidence = event.get("evidence")
        plan = evidence.get("normal_plan") if isinstance(evidence, Mapping) else None
        if not isinstance(plan, Mapping):
            break
        effects = plan.get("effects")
        activation = plan.get("activation_requirements")
        if (
            not isinstance(effects, (list, tuple))
            or not effects
            or any(not isinstance(item, str) or not item for item in effects)
            or not isinstance(activation, (list, tuple))
            or any(not isinstance(item, str) or not item for item in activation)
        ):
            break
        return tuple(effects), tuple(activation)
    raise ValueError("prepared normal plan scope is unavailable")


def _authority_state(
    source_revision: str,
    lane: str | None,
    *,
    transaction: Mapping[str, Any] | None = None,
) -> str:
    if lane == "native":
        return "native-execution-certified"
    try:
        authority = load_normal_execution_authority(source_revision=source_revision)
    except FileNotFoundError:
        return "absent"
    except (OSError, ValueError):
        return "stale-or-invalid"
    if transaction is not None:
        try:
            effects, activation = _normal_plan_scope(transaction)
            authorize_normal_plan(
                authority,
                source_revision=source_revision,
                effects=effects,
                activation_requirements=activation,
            )
        except ValueError:
            return "scope-mismatch"
    return "current"


def _current_transaction(root: Path) -> dict[str, Any] | None:
    pointer = root / "current"
    try:
        transaction_id = pointer.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if _TXID.fullmatch(transaction_id) is None:
        raise ValueError("current update pointer identity is invalid")
    return read_transaction(transaction_path(root, transaction_id))


def _work_for(transaction_id: str) -> tuple[Path, Path, Path]:
    base = work_root() / transaction_id
    return base, base / "discovery", base / "staging"


def _manifest_for(cache: Path, transaction: Mapping[str, Any]) -> Path:
    generation = validate_transaction(transaction)["package_generation"]["id"]
    return cache / f"manifest-{generation}.json"


def _candidate_capability(transaction_id: str) -> bool:
    ops = NativeBtrfsOps(transaction_id)
    try:
        ops.root_identity()
        return True
    except Exception:
        return False
    finally:
        try:
            ops.close()
        except Exception:
            pass


def _discovery_due(state: Mapping[str, Any] | None, now: datetime) -> bool:
    if not state:
        return True
    retry = parse_stamp(state.get("next_retry_at"))
    if retry is not None and now < retry:
        return False
    due = parse_stamp(state.get("next_discovery_at"))
    return due is None or now >= due


def _repo_hashes(repo: Mapping[str, Any], destination: Path) -> dict[str, str]:
    backend = IsolatedPacmanDiscovery(
        destination,
        config_path=str(repo["config_path"]),
        required_repositories=tuple(repo["repositories"]),
    )
    backend.prepare()
    result = backend.run(backend.refresh_command)
    if result.returncode != 0:
        raise RuntimeError(f"isolated_synchronization_failed:{result.stderr.strip()}")
    return backend.sync_database_hashes()


def _observe_boot_only(
    base: Path,
    repo: Mapping[str, Any],
    source_revision: str,
    now: datetime,
) -> dict[str, Any]:
    entropy = secrets.token_hex(6)
    backend = IsolatedPacmanDiscovery(
        base / "boot-observation",
        config_path=str(repo["config_path"]),
        required_repositories=tuple(repo["repositories"]),
    )
    result = discover_updates(
        backend,
        source_revision=source_revision,
        recovery_generation_id=None,
        now=now,
        entropy=entropy,
    )
    return {
        "transaction": result.transaction,
        "candidate_count": result.candidate_count,
        "repository_hashes": backend.sync_database_hashes(),
    }


def _prepare_normal(
    transaction: Mapping[str, Any],
    cache: Path,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = validate_transaction(transaction)
    manifest_path = _manifest_for(cache, current)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest, current, cache)
    generation_current = _generation_is_current(current)
    known_power, power_ok, battery = _power_evidence()
    required = sum(
        int(item["installed_size"]) + int(item["download_size"])
        for item in current["package_generation"]["packages"]
    ) + PREPARATION_OVERHEAD_BYTES
    available = min(shutil.disk_usage("/").free, shutil.disk_usage(cache).free)
    candidate_ok = _candidate_capability(current["transaction_id"])
    evidence = NormalPreparationEvidence(
        discovery_generation_current=generation_current,
        coherent_independent_generation=True,
        required_disk_bytes=required,
        available_disk_bytes=available,
        power_status_known=known_power,
        power_policy_satisfied=power_ok,
        concurrent_package_or_build_operation=Path("/var/lib/pacman/db.lck").exists(),
        candidate_root_available=candidate_ok,
        guardian_admission_available=True,
        execution_environment="production",
        safe_reserve_bytes=SAFE_STORAGE_RESERVE_BYTES,
        gc_authority_current=True,
    )
    prepared = prepare_normal_transaction(current, manifest, cache, evidence, now=now)
    details = {
        "generation_current": generation_current,
        "power_status_known": known_power,
        "power_policy_satisfied": power_ok,
        "battery_percent": battery,
        "required_disk_bytes": required,
        "available_disk_bytes": available,
        "safe_reserve_bytes": SAFE_STORAGE_RESERVE_BYTES,
        "candidate_root_available": candidate_ok,
        "guardian_admission_available": True,
        "manifest_path": str(manifest_path),
    }
    return prepared.transaction, details


def _read_adaptive_status(user: str, now: datetime) -> dict[str, Any]:
    record = pwd.getpwnam(user)
    path = Path(record.pw_dir) / ".local/state/maho/adaptive/current.json"
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError("adaptive_maintenance_evidence_missing") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != record.pw_uid:
            raise RuntimeError("adaptive_maintenance_evidence_unsafe")
        if stat.S_IMODE(info.st_mode) not in {0o600, 0o640, 0o644} or info.st_size > 1024 * 1024:
            raise RuntimeError("adaptive_maintenance_evidence_unsafe")
        with os.fdopen(descriptor, "r", encoding="utf-8", errors="strict") as stream:
            descriptor = -1
            raw = json.load(stream)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        raise RuntimeError("adaptive_maintenance_evidence_invalid")
    captured = parse_stamp(raw.get("captured_at"))
    if captured is None or captured > now + timedelta(seconds=5) or now - captured > ADAPTIVE_EVIDENCE_MAX_AGE:
        raise RuntimeError("adaptive_maintenance_evidence_stale")
    situation = raw.get("situation")
    if not isinstance(situation, Mapping):
        raise RuntimeError("adaptive_maintenance_evidence_invalid")
    for domain in ("session", "power", "thermal", "workload", "network", "maintenance", "guardian"):
        value = situation.get(domain)
        if not isinstance(value, Mapping) or value.get("freshness") != "fresh":
            raise RuntimeError(f"{domain}_evidence_not_fresh")
    return dict(raw)


def _adaptive_ready(raw: Mapping[str, Any]) -> tuple[bool, list[str]]:
    posture = raw.get("active_posture")
    if not isinstance(posture, Mapping) or posture.get("maintenance") != "eligible":
        return False, ["adaptive_maintenance_not_eligible"]
    if raw.get("blocked"):
        return False, ["adaptive_policy_blocked"]
    situation = raw["situation"]
    session = situation["session"]
    power = situation["power"]
    thermal = situation["thermal"]
    workload = situation["workload"]
    network = situation["network"]
    guardian = situation["guardian"]
    reasons: list[str] = []
    if session.get("locked") is not True:
        reasons.append("session_not_locked")
    idle = session.get("idle_seconds")
    if isinstance(idle, bool) or not isinstance(idle, (int, float)) or idle < 20 * 60:
        reasons.append("idle_dwell_too_short_or_unknown")
    if power.get("ac_online") is not True:
        reasons.append("stable_ac_required")
    percentage = power.get("percentage")
    if isinstance(percentage, int) and not isinstance(percentage, bool) and percentage < 25:
        reasons.append("battery_not_healthy")
    if thermal.get("level") not in {"normal", "warm"}:
        reasons.append("thermal_state_not_acceptable")
    if workload.get("gaming") is True or workload.get("interactive") is True:
        reasons.append("interactive_workload")
    if workload.get("compile") is True:
        reasons.append("compile_in_progress")
    if workload.get("rendering") is True:
        reasons.append("render_in_progress")
    if network.get("connectivity") != "online" or network.get("stability") != "stable":
        reasons.append("network_not_stable")
    if guardian.get("active_incident") is True or guardian.get("recovery_in_progress") is True:
        reasons.append("guardian_unhealthy")
    level = guardian.get("severity_level")
    if isinstance(level, int) and not isinstance(level, bool) and level >= 2:
        reasons.append("guardian_severity_blocks_maintenance")
    return not reasons, reasons


def _maintenance_transition(
    transaction: Mapping[str, Any],
    state: Mapping[str, Any],
    user: str,
    runtime: Mapping[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = validate_transaction(transaction)
    authority_state = _authority_state(
        current["source_revision"],
        state.get("lane"),
        transaction=current,
    )
    if state.get("lane") == "normal" and authority_state != "current":
        return current, {
            "ready": False,
            "reasons": ["normal_execution_authority_" + authority_state.replace("-", "_")],
            "normal_execution_authority": authority_state,
        }
    adaptive = _read_adaptive_status(user, now)
    ready, adaptive_reasons = _adaptive_ready(adaptive)
    if not ready:
        return current, {
            "ready": False,
            "reasons": adaptive_reasons,
            "adaptive_snapshot_id": adaptive.get("snapshot_id"),
            "adaptive_captured_at": adaptive.get("captured_at"),
        }
    if not _generation_is_current(current):
        blocked = transition_transaction(
            current,
            UpdateState.BLOCKED,
            reason="prepared update invalidated before maintenance",
            blockers=["stale_update_transaction"],
            now=now,
        )
        return blocked, {"ready": False, "reasons": ["stale_update_transaction"]}
    if state.get("lane") == "native":
        native = state.get("native_preparation")
        journal_path = Path(str(native.get("journal_path"))) if isinstance(native, Mapping) else Path("")
        journal = _read_json(journal_path) if journal_path.is_absolute() else None
        cache = Path(str(journal.get("cache_root"))) if isinstance(journal, Mapping) else Path("")
        if not cache.is_absolute() or not cache.is_dir():
            return current, {"ready": False, "reasons": ["native_preparation_cache_unavailable"]}
    else:
        _, _, cache = _work_for(current["transaction_id"])
    available = min(shutil.disk_usage("/").free, shutil.disk_usage(cache).free)
    required = sum(
        int(item["installed_size"]) + int(item["download_size"])
        for item in current["package_generation"]["packages"]
    ) + PREPARATION_OVERHEAD_BYTES
    disk_ready = available >= required and available - required >= SAFE_STORAGE_RESERVE_BYTES
    recovery_ready = (
        current["recovery"].get("native_l3_certified") is True
        and isinstance(current["recovery"].get("generation_id"), str)
    ) if state.get("lane") == "native" else _candidate_capability(current["transaction_id"])
    if not disk_ready or not recovery_ready:
        reasons = []
        if not disk_ready:
            reasons.append("disk_headroom_unconfirmed")
        if not recovery_ready:
            reasons.append("recovery_prerequisites_unready")
        return current, {"ready": False, "reasons": reasons}
    situation = adaptive["situation"]
    session = situation["session"]
    power = situation["power"]
    workload = situation["workload"]
    guardian = situation["guardian"]
    serious_security = any(
        item.get("security_relevant") is True for item in current["package_generation"]["packages"]
    )
    context = MaintenanceContext(
        intent="none",
        active_user=False,
        fullscreen_or_gaming=workload.get("gaming") is True,
        idle_seconds=int(session["idle_seconds"]),
        locked=True,
        power_status_known=True,
        on_ac=power.get("ac_online") is True,
        battery_percent=power.get("percentage") if isinstance(power.get("percentage"), int) else None,
        system_safe=(
            guardian.get("active_incident") is not True
            and guardian.get("recovery_in_progress") is not True
            and (not isinstance(guardian.get("severity_level"), int) or guardian.get("severity_level") < 2)
        ),
        concurrent_package_or_build_operation=Path("/var/lib/pacman/db.lck").exists(),
        unattended_allowed=True,
        serious_security_issue=serious_security,
        update_debt_days=_debt_seconds(state, now) // 86400,
        adaptive_maintenance="eligible",
    )
    evidence = {
        "transaction_id": current["transaction_id"],
        "package_generation_id": current["package_generation"]["id"],
        "source_revision": current["source_revision"],
        "runtime_identity": dict(runtime),
        "adaptive_snapshot_id": adaptive.get("snapshot_id"),
        "adaptive_captured_at": adaptive.get("captured_at"),
        "evidence_fresh": True,
        "recovery_ready": recovery_ready,
        "disk_ready": disk_ready,
        "available_disk_bytes": available,
        "required_disk_bytes": required,
        "repository_hashes": dict(state.get("repository_hashes") or {}),
        "repository_observed_at": state.get("repository_observed_at"),
        "decision_at": stamp(now),
        "execution_authority_state": authority_state,
    }
    decision = evaluate_maintenance(
        current,
        context,
        now=now,
        authority_evidence=evidence,
    )
    return decision.transaction, {
        "ready": decision.may_begin,
        "reasons": list(decision.reasons),
        "authority": decision.authority,
        **evidence,
    }


def _execution_repository_observation(repo: Mapping[str, Any]) -> dict[str, str]:
    temporary = work_root() / f"execute-observe-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        return _repo_hashes(repo, temporary)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _execution_maintenance_observation(user: str, now: datetime) -> dict[str, Any]:
    raw = _read_adaptive_status(user, now)
    ready, reasons = _adaptive_ready(raw)
    if not ready:
        raise RuntimeError("maintenance_opportunity_revoked:" + ",".join(reasons))
    return {
        "safe": True,
        "snapshot_id": raw.get("snapshot_id"),
        "captured_at": raw.get("captured_at"),
        "decision_at": stamp(now),
    }


def _fresh_ready_normal_evidence(
    transaction: Mapping[str, Any],
    state: Mapping[str, Any],
    user: str,
    repo: Mapping[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = validate_transaction(transaction)
    reasons: list[str] = []
    authority_state = _authority_state(
        current["source_revision"], "normal", transaction=current,
    )
    if authority_state != "current":
        reasons.append("normal_execution_authority_" + authority_state.replace("-", "_"))
    try:
        adaptive = _read_adaptive_status(user, now)
        adaptive_ready, adaptive_reasons = _adaptive_ready(adaptive)
    except RuntimeError as exc:
        adaptive = {}
        adaptive_ready = False
        adaptive_reasons = [str(exc).split(":", 1)[0]]
    if not adaptive_ready:
        reasons.extend(adaptive_reasons)
    if not _generation_is_current(current):
        reasons.append("stale_update_transaction")

    value = dict(state)
    observed_at = parse_stamp(value.get("repository_observed_at"))
    if observed_at is None or now - observed_at > REPOSITORY_EVIDENCE_MAX_AGE:
        temporary = work_root() / f"execute-revalidate-{os.getpid()}-{secrets.token_hex(4)}"
        try:
            observed_hashes = _repo_hashes(repo, temporary)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        expected_hashes = value.get("repository_hashes")
        if not isinstance(expected_hashes, Mapping) or dict(expected_hashes) != observed_hashes:
            reasons.append("repository_generation_drifted")
        else:
            value["repository_observed_at"] = stamp(now)
            value["repository_hashes"] = observed_hashes

    _, _, cache = _work_for(current["transaction_id"])
    if not cache.is_dir() or not _manifest_for(cache, current).is_file():
        reasons.append("staged_preparation_artifacts_missing")
        available = 0
        required = 0
        recovery_ready = False
    else:
        available = min(shutil.disk_usage("/").free, shutil.disk_usage(cache).free)
        required = sum(
            int(item["installed_size"]) + int(item["download_size"])
            for item in current["package_generation"]["packages"]
        ) + PREPARATION_OVERHEAD_BYTES
        if available < required or available - required < SAFE_STORAGE_RESERVE_BYTES:
            reasons.append("disk_headroom_unconfirmed")
        recovery_ready = _candidate_capability(current["transaction_id"])
        if not recovery_ready:
            reasons.append("recovery_prerequisites_unready")

    evidence = {
        "ready": not reasons,
        "reasons": reasons,
        "transaction_id": current["transaction_id"],
        "package_generation_id": current["package_generation"]["id"],
        "source_revision": current["source_revision"],
        "adaptive_snapshot_id": adaptive.get("snapshot_id"),
        "adaptive_captured_at": adaptive.get("captured_at"),
        "repository_hashes": dict(value.get("repository_hashes") or {}),
        "repository_observed_at": value.get("repository_observed_at"),
        "available_disk_bytes": available,
        "required_disk_bytes": required,
        "recovery_ready": recovery_ready,
        "execution_authority_state": authority_state,
        "decision_at": stamp(now),
    }
    return evidence, value


def _revalidate_repository(
    transaction: Mapping[str, Any],
    state: Mapping[str, Any],
    repo: Mapping[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    observed_at = parse_stamp(state.get("repository_observed_at"))
    if observed_at is not None and now - observed_at <= REPOSITORY_EVIDENCE_MAX_AGE:
        return validate_transaction(transaction), dict(state), True
    temporary = work_root() / f"revalidate-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        hashes = _repo_hashes(repo, temporary)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    expected = state.get("repository_hashes")
    if not isinstance(expected, Mapping) or dict(expected) != hashes:
        current = validate_transaction(transaction)
        if current["state"] == UpdateState.PREPARED.value:
            current = transition_transaction(
                current,
                UpdateState.BLOCKED,
                reason="repository generation changed after preparation",
                blockers=["repository_generation_drifted"],
                evidence={"previous": dict(expected or {}), "observed": hashes},
                now=now,
            )
        value = dict(state)
        value.update({
            "phase": "INVALIDATED",
            "blockers": ["repository_generation_drifted"],
            "repository_hashes": hashes,
            "repository_observed_at": stamp(now),
        })
        return current, value, False
    value = dict(state)
    value["repository_observed_at"] = stamp(now)
    return validate_transaction(transaction), value, True


def _resume_owned(
    state: Mapping[str, Any],
    source_revision: str,
    user: str,
    runtime: Mapping[str, Any],
    repo: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any] | None:
    if state.get("phase") == "INVALIDATED":
        return None
    transaction_id = state.get("active_transaction_id")
    if not isinstance(transaction_id, str) or _TXID.fullmatch(transaction_id) is None:
        return None
    root = state_root()
    try:
        transaction = read_transaction(transaction_path(root, transaction_id))
    except (OSError, ValueError):
        return None
    if transaction["source_revision"] != source_revision:
        if transaction["state"] == UpdateState.PREPARED.value:
            transaction = transition_transaction(
                transaction,
                UpdateState.BLOCKED,
                reason="coordinator source revision changed",
                blockers=["coordinator_source_revision_changed"],
                now=now,
            )
            publish_transaction(root, transaction)
        value = dict(state)
        value.update({"phase": "INVALIDATED", "blockers": ["coordinator_source_revision_changed"]})
        return _save(_with_debt(value, now))
    phase = transaction["state"]
    _, _, cache = _work_for(transaction_id)

    if state.get("lane") == "normal" and phase == UpdateState.RECOVERED.value:
        current = _current_transaction(root)
        if current is None or current.get("transaction_id") != transaction_id:
            return None
        from maho_update_bad_recovery import (
            _read_record as read_bad_update_record,
            reverify_recovered_normal,
        )
        try:
            current_recovery = reverify_recovered_normal(
                transaction_id, state_root=root,
                generation_root=Path("/var/lib/maho/generations"),
            )
            recovery_record = read_bad_update_record(root, transaction_id)
        except (OSError, RuntimeError, ValueError) as exc:
            value = dict(state)
            value.update({
                "phase": UpdateState.ATTENTION_REQUIRED.value,
                "blockers": ["recovered_state_evidence_invalid"],
                "last_error": str(exc)[:4000],
                "last_attempt_at": stamp(now),
                "reboot_required": False,
                "reboot_performed": True,
            })
            return _save(_with_debt(value, now))
        verification = recovery_record.get("post_recovery_verification")
        recovery = state.get("recovery")
        if (
            recovery_record.get("phase") != "RECOVERED_VERIFIED"
            or recovery_record.get("transaction_state") != UpdateState.RECOVERED.value
            or recovery_record.get("recovery_attempts") != 1
            or not isinstance(verification, Mapping)
            or not isinstance(recovery, Mapping)
            or recovery.get("transaction_id") != transaction_id
            or recovery.get("phase") != UpdateState.RECOVERED.value
            or recovery.get("recovery_attempts") != 1
            or current_recovery.get("phase") != UpdateState.RECOVERED.value
            or current_recovery.get("recovery_attempts") != 1
            or verification.get("recovery_attempts") != 1
            or verification.get("recovered_root_uuid") != recovery.get("root_uuid")
            or verification.get("recovered_system_generation_id") != recovery.get("system_generation_id")
            or current_recovery.get("root_uuid") != recovery.get("root_uuid")
            or current_recovery.get("system_generation_id") != recovery.get("system_generation_id")
        ):
            value = dict(state)
            value.update({
                "phase": UpdateState.ATTENTION_REQUIRED.value,
                "blockers": ["recovered_state_evidence_invalid"],
                "last_error": "exact recovered-state evidence binding is invalid",
                "last_attempt_at": stamp(now),
                "reboot_required": False,
                "reboot_performed": True,
            })
            return _save(_with_debt(value, now))
        value = dict(state)
        value.update({
            "phase": UpdateState.RECOVERED.value,
            "blockers": [],
            "last_error": None,
            "last_attempt_at": stamp(now),
            "reboot_required": False,
            "reboot_performed": True,
            "user_status": "Previous known-good system recovered and verified.",
        })
        return _save(_with_debt(value, now))

    def _resume_started_recovery() -> dict[str, Any] | None:
        durable = read_transaction(transaction_path(root, transaction_id))
        if durable["state"] != UpdateState.RECOVERING.value:
            return None
        from maho_update_bad_recovery import resume_bad_update_recovery
        return resume_bad_update_recovery(
            transaction_id, state_root=root,
            campaign_root=campaign_root(), now=now,
        )

    def _save_after_recovery(
        value: Mapping[str, Any], result: Mapping[str, Any],
    ) -> dict[str, Any]:
        failed = result.get("failed_candidate_uuid")
        selected = result.get("selected_root_uuid")
        filesystem = result.get("filesystem_uuid")
        if not all(isinstance(item, str) and item for item in (failed, selected, filesystem)):
            return _save(value)
        ops = NativeBtrfsOps(transaction_id)
        try:
            selected_state_root = ops.selected_state_root_for_recovery(
                expected_failed_uuid=failed,
                expected_previous_uuid=selected,
                expected_filesystem_uuid=filesystem,
            )
            return _save(value, selected_state_root)
        finally:
            ops.close()

    if state.get("lane") == "normal" and phase == UpdateState.INSTALLING.value:
        from maho_update_automatic_execution import recover_interrupted_normal_execution
        result = recover_interrupted_normal_execution(
            transaction_id, state_root=root, now=now,
        )
        value = dict(state)
        value.update({
            "phase": str(result.get("phase") or "ATTENTION_REQUIRED"),
            "blockers": list(result.get("transaction", {}).get("blockers") or []),
            "execution": result,
            "last_attempt_at": stamp(now),
            "last_success_at": stamp(now),
        })
        return _save(_with_debt(value, now))

    if state.get("lane") == "normal" and phase == UpdateState.INSTALLED_PENDING_ACTIVATION.value:
        from maho_update_automatic_execution import (
            HealthyPublicationError,
            finalize_pending_normal,
            read_execution_record,
            verify_activated_normal,
        )
        try:
            record = finalize_pending_normal(
                transaction_id, state_root=root, now=now,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            from maho_update_bad_recovery import attention_after_recovery_failure
            attention = attention_after_recovery_failure(
                transaction_id, state_root=root, detail=str(exc),
                blocker="normal_activation_handoff_unavailable", now=now,
            )
            value = dict(state)
            value.update({
                "phase": attention["phase"],
                "blockers": ["normal_activation_handoff_unavailable"],
                "last_error": str(exc)[:4000],
                "last_attempt_at": stamp(now),
            })
            return _save(_with_debt(value, now))
        value = dict(state)
        handoff = record.get("activation_handoff") if isinstance(record, Mapping) else None
        already_armed = record.get("phase") == "ACTIVATION_ARMED"
        postboot = None
        if already_armed:
            try:
                postboot = verify_activated_normal(
                    transaction_id, state_root=root, now=now,
                )
            except HealthyPublicationError as exc:
                value.update({
                    "phase": UpdateState.ACTIVE_VERIFYING.value,
                    "blockers": ["healthy_publication_retry_required"],
                    "last_error": str(exc)[:4000],
                    "last_attempt_at": stamp(now),
                    "reboot_required": False, "reboot_performed": True,
                    "user_status": "Update verified; final status publication will retry automatically.",
                })
                return _save(_with_debt(value, now))
            except (OSError, RuntimeError, ValueError) as exc:
                from maho_update_bad_recovery import (
                    attention_after_recovery_failure,
                    begin_bad_update_recovery,
                )
                try:
                    recovery = begin_bad_update_recovery(
                        transaction_id,
                        failure_code="normal_postboot_verification_failed",
                        failure_detail=str(exc), state_root=root,
                        generation_root=Path("/var/lib/maho/generations"),
                        campaign_root=campaign_root(), now=now,
                    )
                    value.update({
                        "phase": recovery["phase"], "blockers": [],
                        "recovery": recovery, "last_error": str(exc)[:4000],
                        "last_attempt_at": stamp(now),
                        "reboot_required": recovery["reboot_required"],
                        "reboot_performed": recovery["reboot_performed"],
                        "user_status": "Update verification failed. Exact previous system selected; restart to recover.",
                    })
                except (OSError, RuntimeError, ValueError) as recovery_exc:
                    try:
                        resumed = _resume_started_recovery()
                    except (OSError, RuntimeError, ValueError) as resume_exc:
                        recovery_exc = resume_exc
                        resumed = None
                    if resumed is not None:
                        value.update({
                            "phase": UpdateState.RECOVERING.value, "blockers": [],
                            "recovery": resumed, "last_error": str(exc)[:4000],
                            "last_attempt_at": stamp(now),
                            "reboot_required": bool(resumed.get("reboot_required")),
                            "reboot_performed": bool(resumed.get("reboot_performed")),
                            "user_status": "Exact previous system selected; restart to recover.",
                        })
                        return _save_after_recovery(
                            _with_debt(value, now), resumed,
                        )
                    attention = attention_after_recovery_failure(
                        transaction_id, state_root=root, detail=str(recovery_exc),
                        blocker="bad_update_recovery_evidence_invalid", now=now,
                    )
                    value.update({
                        "phase": attention["phase"],
                        "blockers": ["bad_update_recovery_evidence_invalid"],
                        "last_error": str(recovery_exc)[:4000],
                        "last_attempt_at": stamp(now),
                        "reboot_required": False, "reboot_performed": True,
                    })
                    return _save(_with_debt(value, now))
                return _save_after_recovery(
                    _with_debt(value, now), recovery,
                )
            record = read_execution_record(root, transaction_id) or record
        value.update({
            "phase": UpdateState.HEALTHY.value if postboot else "READY_TO_RESTART",
            "blockers": [],
            "last_success_at": stamp(now),
            "execution": record,
            "activation_handoff_id": handoff.get("handoff_id") if isinstance(handoff, Mapping) else None,
            "candidate_system_generation_id": (
                record.get("candidate_generation", {}).get("system_generation_id")
                if isinstance(record.get("candidate_generation"), Mapping) else None
            ),
            "reboot_required": postboot is None,
            "reboot_performed": postboot is not None,
            "postboot_verification": postboot,
            "user_status": (
                "Update verified after restart."
                if postboot else "Update is ready. Restart to finish."
            ),
        })
        return _save(_with_debt(value, now))

    if state.get("lane") == "normal" and phase == UpdateState.RECOVERING.value:
        from maho_update_bad_recovery import (
            _read_record as read_bad_update_record,
            attention_after_recovery_failure,
            resume_bad_update_recovery,
            verify_recovered_normal,
        )
        try:
            recovery_record = read_bad_update_record(root, transaction_id)
            if recovery_record.get("phase") not in {
                "RECOVERY_ARMED", "RECOVERED_VERIFIED_PENDING_TRANSACTION",
            }:
                resumed = resume_bad_update_recovery(
                    transaction_id, state_root=root,
                    campaign_root=campaign_root(), now=now,
                )
                if resumed.get("reboot_performed") is not True:
                    value = dict(state)
                    value.update({
                        "phase": UpdateState.RECOVERING.value, "blockers": [],
                        "recovery": resumed, "last_success_at": stamp(now),
                        "reboot_required": True, "reboot_performed": False,
                        "user_status": "Exact previous system selected; restart to recover.",
                    })
                    return _save_after_recovery(
                        _with_debt(value, now), resumed,
                    )
            recovered = verify_recovered_normal(
                transaction_id, state_root=root,
                generation_root=Path("/var/lib/maho/generations"), now=now,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            try:
                durable = read_transaction(transaction_path(root, transaction_id))
                checkpoint = read_bad_update_record(root, transaction_id)
            except (OSError, RuntimeError, ValueError):
                durable = None
                checkpoint = None
            if (
                isinstance(durable, Mapping)
                and isinstance(checkpoint, Mapping)
                and durable.get("state") in {
                    UpdateState.RECOVERING.value, UpdateState.RECOVERED.value,
                }
                and checkpoint.get("phase") == "RECOVERED_VERIFIED_PENDING_TRANSACTION"
                and checkpoint.get("recovery_attempts") == 1
                and isinstance(checkpoint.get("post_recovery_verification"), Mapping)
            ):
                terminal = durable["state"] == UpdateState.RECOVERED.value
                verification = checkpoint["post_recovery_verification"]
                value = dict(state)
                value.update({
                    "phase": (
                        UpdateState.ATTENTION_REQUIRED.value
                        if terminal else UpdateState.RECOVERING.value
                    ),
                    "blockers": ["recovery_terminal_commit_retry_required"],
                    "last_error": str(exc)[:4000],
                    "last_attempt_at": stamp(now),
                    "reboot_required": False,
                    "reboot_performed": True,
                    "user_status": (
                        "Recovered state is current, but its terminal evidence "
                        "commit must be reconciled."
                    ),
                })
                if terminal:
                    value["recovery"] = {
                        "transaction_id": transaction_id,
                        "phase": UpdateState.RECOVERED.value,
                        "failed_candidate_uuid": verification.get("failed_candidate_uuid"),
                        "failed_system_generation_id": verification.get("failed_system_generation_id"),
                        "root_uuid": verification.get("recovered_root_uuid"),
                        "system_generation_id": verification.get("recovered_system_generation_id"),
                        "kernel_generation_id": verification.get("kernel_generation_id"),
                        "package_versions": verification.get("package_versions"),
                        "recovery_attempts": 1,
                        "reboot_required": False,
                        "reboot_performed": True,
                    }
                return _save(_with_debt(value, now))
            attention = attention_after_recovery_failure(
                transaction_id, state_root=root, detail=str(exc),
                blocker="recovered_generation_verification_failed", now=now,
            )
            value = dict(state)
            value.update({
                "phase": attention["phase"],
                "blockers": ["recovered_generation_verification_failed"],
                "last_error": str(exc)[:4000], "last_attempt_at": stamp(now),
                "reboot_required": False, "reboot_performed": True,
                "user_status": "Recovery could not be verified; attention is required.",
            })
            return _save(_with_debt(value, now))
        value = dict(state)
        waiting = recovered["phase"] == UpdateState.RECOVERING.value
        value.update({
            "phase": recovered["phase"], "blockers": [],
            "recovery": recovered, "last_success_at": stamp(now),
            "reboot_required": bool(recovered.get("reboot_required")),
            "reboot_performed": bool(recovered.get("reboot_performed")),
            "user_status": (
                "Exact previous system selected; restart to recover."
                if waiting else "Previous known-good system recovered and verified."
            ),
        })
        return _save(_with_debt(value, now))

    if state.get("lane") == "normal" and phase in {
        UpdateState.ACTIVE_VERIFYING.value, UpdateState.HEALTHY.value,
    }:
        from maho_update_automatic_execution import (
            HealthyPublicationError, verify_activated_normal,
        )
        try:
            postboot = verify_activated_normal(
                transaction_id, state_root=root, now=now,
            )
        except HealthyPublicationError as exc:
            value = dict(state)
            value.update({
                "phase": UpdateState.ACTIVE_VERIFYING.value,
                "blockers": ["healthy_publication_retry_required"],
                "last_error": str(exc)[:4000],
                "last_attempt_at": stamp(now),
                "reboot_required": False, "reboot_performed": True,
                "user_status": "Update verified; final status publication will retry automatically.",
            })
            return _save(_with_debt(value, now))
        except (OSError, RuntimeError, ValueError) as exc:
            if phase == UpdateState.ACTIVE_VERIFYING.value:
                from maho_update_bad_recovery import (
                    attention_after_recovery_failure,
                    begin_bad_update_recovery,
                )
                try:
                    recovery = begin_bad_update_recovery(
                        transaction_id,
                        failure_code="normal_postboot_verification_failed",
                        failure_detail=str(exc), state_root=root,
                        generation_root=Path("/var/lib/maho/generations"),
                        campaign_root=campaign_root(), now=now,
                    )
                    value = dict(state)
                    value.update({
                        "phase": recovery["phase"], "blockers": [],
                        "recovery": recovery, "last_error": str(exc)[:4000],
                        "last_attempt_at": stamp(now),
                        "reboot_required": True, "reboot_performed": False,
                        "user_status": "Update verification failed. Exact previous system selected; restart to recover.",
                    })
                    return _save_after_recovery(
                        _with_debt(value, now), recovery,
                    )
                except (OSError, RuntimeError, ValueError) as recovery_exc:
                    try:
                        resumed = _resume_started_recovery()
                    except (OSError, RuntimeError, ValueError) as resume_exc:
                        recovery_exc = resume_exc
                        resumed = None
                    if resumed is not None:
                        value = dict(state)
                        value.update({
                            "phase": UpdateState.RECOVERING.value, "blockers": [],
                            "recovery": resumed, "last_error": str(exc)[:4000],
                            "last_attempt_at": stamp(now),
                            "reboot_required": bool(resumed.get("reboot_required")),
                            "reboot_performed": bool(resumed.get("reboot_performed")),
                            "user_status": "Exact previous system selected; restart to recover.",
                        })
                        return _save_after_recovery(
                            _with_debt(value, now), resumed,
                        )
                    attention = attention_after_recovery_failure(
                        transaction_id, state_root=root, detail=str(recovery_exc),
                        blocker="bad_update_recovery_evidence_invalid", now=now,
                    )
                    value = dict(state)
                    value.update({
                        "phase": attention["phase"],
                        "blockers": ["bad_update_recovery_evidence_invalid"],
                        "last_error": str(recovery_exc)[:4000],
                        "last_attempt_at": stamp(now),
                        "reboot_required": False, "reboot_performed": True,
                    })
                    return _save(_with_debt(value, now))
            value = dict(state)
            value.update({
                "phase": "ATTENTION_REQUIRED",
                "blockers": ["normal_postboot_verification_failed"],
                "last_error": str(exc)[:4000],
                "last_attempt_at": stamp(now),
                "reboot_required": False,
                "reboot_performed": True,
            })
            return _save(_with_debt(value, now))
        value = dict(state)
        value.update({
            "phase": UpdateState.HEALTHY.value,
            "blockers": [],
            "last_success_at": stamp(now),
            "postboot_verification": postboot,
            "reboot_required": False,
            "reboot_performed": True,
            "user_status": "Update verified after restart.",
        })
        return _save(_with_debt(value, now))

    if phase == UpdateState.MAINTENANCE_READY.value:
        value = dict(state)
        value.update({
            "phase": "MAINTENANCE_READY",
            "blockers": [],
            "last_success_at": stamp(now),
            "normal_execution_authority": _authority_state(
                source_revision,
                state.get("lane"),
                transaction=transaction if state.get("lane") == "normal" else None,
            ),
        })
        if state.get("lane") == "native":
            blocked = transition_transaction(
                transaction,
                UpdateState.BLOCKED,
                reason=(
                    "automatic native execution requires an exact BootGeneration "
                    "publication authority; production Signed Boot publication is "
                    "outside S2.2 scope"
                ),
                blockers=["native_boot_generation_publication_unavailable"],
                evidence={
                    "lane": "native",
                    "m3b_m4b_prepared": True,
                    "live_root_mutation": False,
                    "signed_boot_mutation_attempted": False,
                    "required_generation": "BootGeneration",
                },
                now=now,
            )
            publish_transaction(root, blocked)
            value.update({
                "phase": "BLOCKED",
                "blockers": ["native_boot_generation_publication_unavailable"],
                "last_attempt_at": stamp(now),
                "native_execution_deferred": True,
                "live_root_mutation_started": False,
                "reboot_performed": False,
                "user_status": "Kernel update prepared; exact boot publication authority is unavailable.",
            })
            return _save(_with_debt(value, now))
        if state.get("lane") != "normal":
            return _save(_with_debt(value, now))
        maintenance, refreshed = _fresh_ready_normal_evidence(
            transaction, value, user, repo, now,
        )
        value.update(refreshed)
        value["maintenance_evidence"] = maintenance
        value["last_attempt_at"] = stamp(now)
        if maintenance["ready"] is not True:
            value.update({
                "phase": "WAITING_MAINTENANCE",
                "blockers": list(maintenance["reasons"]),
            })
            return _save(_with_debt(value, now))
        from maho_update_automatic_execution import execute_ready_normal
        try:
            record = execute_ready_normal(
                transaction,
                cache_root=cache,
                manifest_path=_manifest_for(cache, transaction),
                maintenance_evidence=maintenance,
                repository_evidence={
                    "repository_hashes": dict(value.get("repository_hashes") or {}),
                },
                repository_reobserve=lambda: _execution_repository_observation(repo),
                maintenance_reobserve=lambda: _execution_maintenance_observation(
                    user, utc_now(),
                ),
                state_root=root,
                campaign_root=campaign_root(),
                now=now,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            observed = read_transaction(transaction_path(root, transaction_id))
            if observed["state"] == UpdateState.INSTALLED_PENDING_ACTIVATION.value:
                from maho_update_automatic_execution import finalize_pending_normal
                record = finalize_pending_normal(
                    transaction_id, state_root=root, now=now,
                )
            else:
                value.update({
                    "phase": "MAINTENANCE_READY",
                    "blockers": [str(exc).split(":", 1)[0]],
                    "last_error": str(exc)[:4000],
                })
                return _save(_with_debt(value, now))
        observed = read_transaction(transaction_path(root, transaction_id))
        value["execution"] = record
        value["last_success_at"] = stamp(now)
        if observed["state"] == UpdateState.INSTALLED_PENDING_ACTIVATION.value:
            handoff = record.get("activation_handoff") if isinstance(record, Mapping) else None
            value.update({
                "phase": "READY_TO_RESTART",
                "blockers": [],
                "activation_handoff_id": handoff.get("handoff_id") if isinstance(handoff, Mapping) else None,
                "candidate_system_generation_id": (
                    record.get("candidate_generation", {}).get("system_generation_id")
                    if isinstance(record.get("candidate_generation"), Mapping) else None
                ),
                "reboot_required": True,
                "reboot_performed": False,
                "user_status": "Update is ready. Restart to finish.",
            })
        else:
            value.update({
                "phase": observed["state"],
                "blockers": list(observed.get("blockers") or []),
                "reboot_required": False,
                "reboot_performed": False,
            })
        return _save(_with_debt(value, now))
    if phase in {UpdateState.STAGED.value, UpdateState.BLOCKED.value}:
        if not cache.is_dir() or not _manifest_for(cache, transaction).is_file():
            if phase == UpdateState.STAGED.value:
                transaction = transition_transaction(
                    transaction,
                    UpdateState.BLOCKED,
                    reason="staged preparation artifacts disappeared",
                    blockers=["staged_preparation_artifacts_missing"],
                    now=now,
                )
                publish_transaction(root, transaction)
            value = dict(state)
            value.update({"phase": "INVALIDATED", "blockers": ["staged_preparation_artifacts_missing"]})
            return _save(_with_debt(value, now))
        if not _generation_is_current(transaction):
            if phase == UpdateState.STAGED.value:
                transaction = transition_transaction(
                    transaction,
                    UpdateState.BLOCKED,
                    reason="staged update became stale before preparation",
                    blockers=["stale_update_transaction"],
                    now=now,
                )
                publish_transaction(root, transaction)
            value = dict(state)
            value.update({"phase": "INVALIDATED", "blockers": ["stale_update_transaction"]})
            return _save(_with_debt(value, now))
        if phase == UpdateState.BLOCKED.value:
            try:
                transaction = transition_transaction(
                    transaction,
                    UpdateState.STAGED,
                    reason="automatic coordinator rechecking recoverable preparation blockers",
                    now=now,
                )
            except ValueError:
                value = dict(state)
                value.update({"phase": "BLOCKED", "blockers": list(transaction.get("blockers") or [])})
                return _save(_with_debt(value, now))
        prepared, details = _prepare_normal(transaction, cache, now)
        publish_transaction(root, prepared)
        value = dict(state)
        value["last_attempt_at"] = stamp(now)
        if prepared["state"] == UpdateState.PREPARED.value:
            value.update({
                "phase": "WAITING_MAINTENANCE",
                "last_success_at": stamp(now),
                "last_preparation_success_at": stamp(now),
                "blockers": [],
                "preparation": details,
                "normal_execution_authority": _authority_state(source_revision, state.get("lane")),
            })
        else:
            value.update({
                "phase": "WAITING_PREPARATION",
                "blockers": list(prepared.get("blockers") or []),
                "preparation": details,
            })
        return _save(_with_debt(value, now))
    if phase == UpdateState.PREPARED.value:
        transaction, value, repository_ok = _revalidate_repository(transaction, state, repo, now)
        if not repository_ok:
            publish_transaction(root, transaction)
            return _save(_with_debt(value, now))
        try:
            transitioned, maintenance = _maintenance_transition(transaction, value, user, runtime, now)
        except RuntimeError as exc:
            value.update({
                "phase": "WAITING_MAINTENANCE",
                "blockers": [str(exc).split(":", 1)[0]],
                "maintenance_evidence": {"ready": False, "reasons": [str(exc).split(":", 1)[0]]},
                "last_attempt_at": stamp(now),
                "normal_execution_authority": _authority_state(source_revision, state.get("lane")),
            })
            return _save(_with_debt(value, now))
        if transitioned != transaction:
            publish_transaction(root, transitioned)
        value.update({
            "last_attempt_at": stamp(now),
            "last_success_at": stamp(now),
            "maintenance_evidence": maintenance,
            "normal_execution_authority": _authority_state(source_revision, state.get("lane")),
            "phase": "MAINTENANCE_READY" if transitioned["state"] == UpdateState.MAINTENANCE_READY.value else "WAITING_MAINTENANCE",
            "blockers": [] if transitioned["state"] == UpdateState.MAINTENANCE_READY.value else list(maintenance.get("reasons") or []),
        })
        return _save(_with_debt(value, now))
    return None


def _new_discovery(
    previous: Mapping[str, Any] | None,
    source_revision: str,
    user: str,
    runtime: Mapping[str, Any],
    repo: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    root = state_root()
    entropy = secrets.token_hex(6)
    transaction_id = new_transaction_id(now=now, entropy=entropy)
    base, discovery_root, cache = _work_for(transaction_id)
    base.mkdir(parents=True, exist_ok=False)
    state = dict(previous) if previous else _base_state(now, source_revision)
    state.update({
        "schema_version": SCHEMA_VERSION,
        "source_revision": source_revision,
        "phase": "CHECKING",
        "last_attempt_at": stamp(now),
        "blockers": [],
        "last_error": None,
        "runtime_identity": dict(runtime),
        "next_retry_at": None,
        "live_root_mutation_started": False,
        "reboot_performed": False,
    })
    _save(_with_debt(state, now))
    backend = IsolatedPacmanDiscovery(
        discovery_root,
        config_path=str(repo["config_path"]),
        required_repositories=tuple(repo["repositories"]),
    )
    try:
        discovered = discover_independent_normal_updates(
            backend,
            source_revision=source_revision,
            recovery_generation_id=None,
            now=now,
            entropy=entropy,
        )
    except LookupError as exc:
        text_value = str(exc)
        if "no coherent update candidates were discovered" in text_value:
            repository_hashes = backend.sync_database_hashes()
            shutil.rmtree(base, ignore_errors=True)
            state.update({
                "phase": "UP_TO_DATE",
                "last_success_at": stamp(now),
                "last_discovery_success_at": stamp(now),
                "repository_observed_at": stamp(now),
                "repository_hashes": repository_hashes,
                "active_transaction_id": None,
                "package_generation_id": None,
                "lane": None,
                "candidate_count": 0,
                "deferred_boot_packages": [],
                "first_observed_at": None,
                "update_debt_seconds": 0,
                "blockers": [],
                "failure_count": 0,
                "next_retry_at": None,
                "next_discovery_at": stamp(now + DISCOVERY_INTERVAL),
                "normal_execution_authority": _authority_state(source_revision, None),
            })
            return _save(state)
        if "no coherent non-boot update candidates were discovered" not in text_value:
            raise
        observed = _observe_boot_only(base, repo, source_revision, now)
        full = observed["transaction"]
        names = {item["name"] for item in full["package_generation"]["packages"]}
        can_native_prepare = (
            "linux-cachyos" in names
            and "restart" in full["activation"]["requirements"]
        )
        if can_native_prepare:
            shutil.rmtree(base, ignore_errors=True)
            previous_user = os.environ.get("MAHO_UPDATE_USER")
            os.environ["MAHO_UPDATE_USER"] = user
            try:
                result = prepare_native_campaign()
            finally:
                if previous_user is None:
                    os.environ.pop("MAHO_UPDATE_USER", None)
                else:
                    os.environ["MAHO_UPDATE_USER"] = previous_user
            prepared_id = result["transaction_id"]
            transaction = read_transaction(transaction_path(root, prepared_id))
            native_journal = _read_json(Path(str(result["journal_path"])))
            native_repo = native_journal.get("package_repo") if isinstance(native_journal, Mapping) else None
            native_hashes = native_repo.get("sync_db_sha256") if isinstance(native_repo, Mapping) else None
            if not isinstance(native_hashes, Mapping) or not native_hashes:
                raise RuntimeError("native_preparation_repository_evidence_missing")
            state.update({
                "phase": "WAITING_MAINTENANCE",
                "last_success_at": stamp(now),
                "last_discovery_success_at": stamp(now),
                "last_preparation_success_at": stamp(now),
                "repository_observed_at": stamp(now),
                "repository_hashes": dict(native_hashes),
                "active_transaction_id": prepared_id,
                "package_generation_id": transaction["package_generation"]["id"],
                "lane": "native",
                "candidate_count": len(transaction["package_generation"]["packages"]),
                "deferred_boot_packages": [],
                "first_observed_at": state.get("first_observed_at") or stamp(now),
                "blockers": [],
                "failure_count": 0,
                "next_retry_at": None,
                "next_discovery_at": stamp(now + DISCOVERY_INTERVAL),
                "normal_execution_authority": "native-execution-certified",
                "native_preparation": result,
            })
            return _save(_with_debt(state, now))
        shutil.rmtree(base, ignore_errors=True)
        state.update({
            "phase": "BLOCKED",
            "last_success_at": stamp(now),
            "last_discovery_success_at": stamp(now),
            "repository_observed_at": stamp(now),
            "repository_hashes": observed["repository_hashes"],
            "active_transaction_id": None,
            "package_generation_id": full["package_generation"]["id"],
            "lane": "native-required",
            "candidate_count": observed["candidate_count"],
            "deferred_boot_packages": sorted(names),
            "first_observed_at": state.get("first_observed_at") or stamp(now),
            "blockers": ["boot_only_generation_requires_native_preparation"],
            "failure_count": 0,
            "next_retry_at": None,
            "next_discovery_at": stamp(now + DISCOVERY_INTERVAL),
            "normal_execution_authority": "not-applicable",
        })
        return _save(_with_debt(state, now))
    transaction = discovered.transaction
    if transaction["transaction_id"] != transaction_id:
        raise RuntimeError("automatic discovery transaction identity drifted")
    repository_hashes = backend.sync_database_hashes()
    publish_transaction(root, transaction)
    state.update({
        "phase": "PREPARING",
        "last_discovery_success_at": stamp(now),
        "repository_observed_at": stamp(now),
        "repository_hashes": repository_hashes,
        "active_transaction_id": transaction_id,
        "package_generation_id": transaction["package_generation"]["id"],
        "lane": "normal",
        "candidate_count": discovered.candidate_count,
        "deferred_boot_packages": list(discovered.deferred_boot_packages),
        "first_observed_at": state.get("first_observed_at") or stamp(now),
        "next_discovery_at": stamp(now + DISCOVERY_INTERVAL),
        "normal_execution_authority": _authority_state(source_revision, "normal"),
    })
    _save(_with_debt(state, now))
    staging = IsolatedPacmanStaging(Path(discovered.isolated_db), cache, config_path=str(repo["config_path"]))
    staged = stage_transaction(transaction, staging, now=now)
    publish_transaction(root, staged.transaction)
    if staged.transaction["state"] != UpdateState.STAGED.value or staged.manifest is None:
        state.update({
            "phase": "BLOCKED",
            "blockers": list(staged.transaction.get("blockers") or ["package_staging_incomplete"]),
        })
        return _save(_with_debt(state, now))
    state["phase"] = "PREPARING"
    _save(_with_debt(state, now))
    prepared, details = _prepare_normal(staged.transaction, cache, now)
    publish_transaction(root, prepared)
    if prepared["state"] == UpdateState.PREPARED.value:
        state.update({
            "phase": "WAITING_MAINTENANCE",
            "last_success_at": stamp(now),
            "last_preparation_success_at": stamp(now),
            "blockers": [],
            "preparation": details,
            "failure_count": 0,
            "next_retry_at": None,
        })
    else:
        state.update({
            "phase": "WAITING_PREPARATION",
            "blockers": list(prepared.get("blockers") or []),
            "preparation": details,
        })
    return _save(_with_debt(state, now))


def run_once(*, now: datetime | None = None) -> dict[str, Any]:
    _require_root()
    current = (now or utc_now()).astimezone(timezone.utc)
    root = _root()
    source_revision = _source_revision(root)
    previous = read_coordinator_state()
    retry = parse_stamp((previous or {}).get("next_retry_at"))
    if (
        previous
        and previous.get("source_revision") == source_revision
        and retry is not None
        and current < retry
    ):
        value = dict(previous)
        value["last_attempt_at"] = stamp(current)
        value["phase"] = "RETRY_DEFERRED"
        return _save(_with_debt(value, current))
    with coordinator_mutex():
        user = _coordinator_user()
        runtime = _runtime_identity(user)
        if runtime.get("source_revision") != source_revision:
            raise RuntimeError("immutable_runtime_source_revision_mismatch")
        policy = json.loads((root / "config/platform.json").read_text(encoding="utf-8"))
        repo = _repo_contract(policy)
        if previous and previous.get("source_revision") == source_revision:
            resumed = _resume_owned(previous, source_revision, user, runtime, repo, current)
            if resumed is not None and resumed.get("phase") not in {"INVALIDATED"}:
                return resumed
        active = _current_transaction(state_root())
        if active is not None and active["state"] not in {
            UpdateState.HEALTHY.value,
            UpdateState.RECOVERED.value,
            UpdateState.ATTENTION_REQUIRED.value,
            UpdateState.BLOCKED.value,
        }:
            value = dict(previous) if previous else _base_state(current, source_revision)
            value.update({
                "phase": "BLOCKED",
                "last_attempt_at": stamp(current),
                "blockers": ["non_coordinator_update_transaction_active"],
                "runtime_identity": dict(runtime),
                "normal_execution_authority": _authority_state(source_revision, value.get("lane")),
            })
            return _save(_with_debt(value, current))
        if previous and not _discovery_due(previous, current) and previous.get("phase") in {"UP_TO_DATE", "BLOCKED"}:
            value = dict(previous)
            value["last_attempt_at"] = stamp(current)
            return _save(_with_debt(value, current))
        return _new_discovery(previous, source_revision, user, runtime, repo, current)


def status_payload() -> dict[str, Any]:
    state = read_coordinator_state()
    if state is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "phase": "UNAVAILABLE",
            "blockers": ["coordinator_state_unavailable"],
        }
    return state


def main() -> None:
    parser = argparse.ArgumentParser(prog="maho-update-coordinator")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    sub.add_parser("activate-current")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "status":
        payload = status_payload()
        if args.json:
            print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        else:
            print(payload.get("phase", "UNAVAILABLE"))
            blockers = payload.get("blockers") or []
            if blockers:
                print("Blockers: " + ", ".join(str(item) for item in blockers))
        return
    if args.command == "activate-current":
        from maho_update_automatic_execution import activate_current_pending
        _require_root()
        try:
            with coordinator_mutex():
                payload = activate_current_pending(state_root=state_root())
        except CoordinatorBusy:
            payload = {
                "schema_version": SCHEMA_VERSION,
                "phase": "COALESCED",
                "blockers": ["update_campaign_busy"],
                "activation_attempted": False,
                "reboot_performed": False,
            }
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return
    try:
        payload = run_once()
    except CoordinatorBusy:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "phase": "COALESCED",
            "blockers": ["update_campaign_busy"],
            "live_root_mutation_started": False,
            "reboot_performed": False,
        }
    except (OSError, RuntimeError, ValueError, LookupError, PermissionError, json.JSONDecodeError) as exc:
        root = _root()
        try:
            source_revision = _source_revision(root)
        except Exception:
            source_revision = "0" * 40
        previous = read_coordinator_state() or _base_state(utc_now(), source_revision)
        payload = _record_failure(
            previous,
            utc_now(),
            source_revision,
            str(exc).split(":", 1)[0] or type(exc).__name__,
            str(exc),
        )
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
