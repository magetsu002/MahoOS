#!/usr/bin/env python3
"""Root-owned native M4B update/activation certification campaign."""
from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import subprocess
from typing import Any, Mapping

from guardian_admission import AdmissionOutcome
from guardian_native_admission import CandidateRoots
from maho_runtime_release import verify_release
from maho_system_restore_campaign import prepare_campaign as prepare_l3_campaign, seed_campaign
from maho_system_restore_host import SystemPreparationOps
from maho_system_restore_journal import read_journal as read_l3_journal
from maho_update_discovery import IsolatedPacmanDiscovery, discover_updates
from maho_update_admission import (
    admission_review_confirmation,
    evaluate_production_candidate,
    guardian_transaction_id,
    issue_activation_authority,
    verify_activation_authority,
)
from maho_update_native import (
    NativeBtrfsOps,
    NativeCandidateUpdateOps,
    PostBootActivationOps,
    activation_confirmation,
    update_confirmation,
)
from maho_update_preparation import PreparationEvidence, prepare_transaction
from maho_update_receipts import record_receipt
from maho_update_staging import IsolatedPacmanStaging, stage_transaction
from maho_update_state import (
    UpdateState,
    bind_native_authority,
    new_transaction_id,
    publish_transaction,
    read_transaction,
    transaction_path,
    transition_transaction,
    validate_transaction,
)
from maho_update_transaction import ExecutionPlan, build_execution_plan, execute_update, verify_activation
from maho_trust_identity import ArtifactID

_TXID = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
_SHA40 = re.compile(r"[0-9a-f]{40}")
_STATE_ROOT = Path("/var/lib/maho/update")


def _root() -> Path:
    override = os.environ.get("MAHO_UPDATE_CAMPAIGN_ROOT")
    return Path(override) if override else Path(__file__).resolve().parents[1]


def _source_revision(root: Path) -> str:
    try:
        value = (root / "SOURCE_REVISION").read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if _SHA40.fullmatch(value) is None:
        raise RuntimeError("installed M4B campaign source revision is invalid")
    return value


def _machine_id() -> str:
    value = Path("/etc/machine-id").read_text(encoding="utf-8").strip().lower()
    if re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise RuntimeError("machine identity is invalid")
    return value


def _platform(root: Path) -> dict[str, Any]:
    value = json.loads((root / "config/platform.json").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("platform policy is invalid")
    return value


def _require_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("M4B native certification requires root")


def _repo_contract(policy: Mapping[str, Any]) -> dict[str, Any]:
    update = policy.get("update")
    if not isinstance(update, Mapping):
        raise RuntimeError("package_repo_policy_missing")
    config_value = update.get("pacman_config")
    required = update.get("required_repositories")
    if not isinstance(config_value, str) or not config_value.startswith("/"):
        raise RuntimeError("package_repo_config_invalid")
    if not isinstance(required, list) or not required or any(not isinstance(item, str) or not item for item in required):
        raise RuntimeError("package_repo_policy_invalid")
    config = Path(config_value)
    try:
        stat = config.stat()
    except OSError as exc:
        raise RuntimeError("package_repo_config_unavailable") from exc
    if not config.is_file() or stat.st_uid != 0 or stat.st_gid != 0 or stat.st_mode & 0o022:
        raise RuntimeError("package_repo_config_untrusted")
    completed = subprocess.run(
        ("/usr/bin/pacman-conf", "--config", str(config), "--repo-list"),
        check=False, text=True, capture_output=True,
        env={"PATH": "/usr/bin", "LC_ALL": "C"},
    )
    observed = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or observed != required:
        raise RuntimeError(
            "package_repo_set_mismatch: expected " + ",".join(required) +
            " observed " + ",".join(observed)
        )
    return {
        "config_path": str(config),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "repositories": observed,
    }


def _blocker_code(exc: Exception) -> str:
    text = str(exc).strip()
    head = text.split(":", 1)[0]
    if re.fullmatch(r"[a-z0-9_]+", head):
        return head
    if isinstance(exc, LookupError):
        return "no_coherent_update_candidates"
    return "campaign_precondition_failed"


def _campaign_path(machine_id: str, transaction_id: str) -> Path:
    if _TXID.fullmatch(transaction_id) is None:
        raise ValueError("invalid update transaction identity")
    return Path("/boot") / machine_id / "maho/update/m4b" / f"{transaction_id}.json"


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    encoded = (json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o644)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_campaign(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid M4B campaign journal")
    txid = value.get("transaction_id")
    if not isinstance(txid, str) or _TXID.fullmatch(txid) is None or path.stem != txid:
        raise ValueError("M4B campaign journal identity mismatch")
    return value


def _transition_campaign(path: Path, journal: Mapping[str, Any], phase: str, **details: Any) -> dict[str, Any]:
    updated = dict(journal)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    updated["phase"] = phase
    updated["updated_at"] = stamp
    history = [dict(item) for item in journal.get("history", [])]
    history.append({"phase": phase, "at": stamp, "details": details})
    updated["history"] = history
    if details:
        updated.update(details)
    _write_json_atomic(path, updated)
    return updated


def _campaign_user() -> str:
    name = os.environ.get("MAHO_UPDATE_USER") or os.environ.get("SUDO_USER") or ""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}", name):
        raise RuntimeError("M4B campaign requires an exact non-root update user")
    record = pwd.getpwnam(name)
    if record.pw_uid == 0 or record.pw_dir != f"/home/{name}":
        raise RuntimeError("M4B campaign user home is not the expected /home identity")
    return name


def _runtime_identity(user: str) -> dict[str, Any]:
    base = Path("/home") / user / ".local/share/maho/runtime"
    verification = verify_release(base / "current", base / "releases")
    if not verification.verified or not verification.content_sha256 or not verification.source_revision:
        raise RuntimeError("current immutable Maho runtime is not verified")
    return verification.as_dict()


def _pacman_query(name: str) -> str:
    completed = subprocess.run(("pacman", "-Q", name), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"required installed package unavailable: {name}")
    observed, separator, version = completed.stdout.strip().partition(" ")
    if observed != name or not separator or not version:
        raise RuntimeError(f"cannot parse installed package identity: {name}")
    return version


def _target_versions(transaction: Mapping[str, Any]) -> dict[str, str]:
    current = validate_transaction(transaction)
    candidates = {item["name"]: item["candidate_version"] for item in current["package_generation"]["packages"]}
    required = ("linux-cachyos", "linux-cachyos-headers", "linux-cachyos-lts", "linux-cachyos-lts-headers")
    expected = dict(candidates)
    for name in required:
        expected.setdefault(name, _pacman_query(name))
    return expected


def _relationships(transaction: Mapping[str, Any], runtime: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    expected = _target_versions(transaction)
    packages = validate_transaction(transaction)["package_generation"]["packages"]
    nvidia = sorted(item["name"] for item in packages if set(item["roles"]) & {"nvidia", "dkms"})
    relationships = {
        "maho_runtime": {
            "package": "maho-runtime",
            "version": runtime["content_sha256"],
            "source_revision": runtime["source_revision"],
            "immutable_release_required": True,
        },
        "primary_kernel": {"package": "linux-cachyos", "version": expected["linux-cachyos"]},
        "primary_headers": {"package": "linux-cachyos-headers", "version": expected["linux-cachyos-headers"]},
        "fallback_kernel": {"package": "linux-cachyos-lts", "version": expected["linux-cachyos-lts"]},
        "fallback_headers": {"package": "linux-cachyos-lts-headers", "version": expected["linux-cachyos-lts-headers"]},
        "nvidia_dkms": {"status": "planned" if nvidia else "not-installed", "packages": nvidia},
        "boot_artifacts": [
            "/boot/intel-ucode.img",
            "/boot/vmlinuz-linux-cachyos", "/boot/initramfs-linux-cachyos.img",
            "/boot/vmlinuz-linux-cachyos-lts", "/boot/initramfs-linux-cachyos-lts.img",
        ],
    }
    return relationships, expected


def _generation_is_current(transaction: Mapping[str, Any]) -> bool:
    for item in validate_transaction(transaction)["package_generation"]["packages"]:
        result = subprocess.run(("pacman", "-Q", item["name"]), text=True, capture_output=True, check=False)
        if item["installed_version"] == "<not-installed>":
            if result.returncode == 0:
                return False
            continue
        if result.returncode != 0:
            return False
        _, _, observed = result.stdout.strip().partition(" ")
        if observed != item["installed_version"]:
            return False
    return True


def _power_evidence() -> tuple[bool, bool, int | None]:
    mains: list[bool] = []
    battery: int | None = None
    root = Path("/sys/class/power_supply")
    if not root.is_dir():
        return False, False, None
    for entry in root.iterdir():
        try:
            kind = (entry / "type").read_text().strip().lower()
        except OSError:
            continue
        if kind in {"mains", "usb", "usb_c"}:
            try:
                mains.append((entry / "online").read_text().strip() == "1")
            except OSError:
                pass
        elif kind == "battery":
            try:
                battery = int((entry / "capacity").read_text().strip())
            except (OSError, ValueError):
                pass
    known = bool(mains)
    satisfied = known and any(mains) and (battery is None or battery >= 25)
    return known, satisfied, battery


def _manifest_path(cache: Path, package_generation_id: str) -> Path:
    return cache / f"manifest-{package_generation_id}.json"


def _plan_from_dict(value: Mapping[str, Any]) -> ExecutionPlan:
    return ExecutionPlan(
        transaction_id=str(value["transaction_id"]),
        package_generation_id=str(value["package_generation_id"]),
        source_revision=str(value["source_revision"]),
        payload_paths=tuple(value["payload_paths"]),
        maho_runtime=dict(value["maho_runtime"]),
        primary_kernel=dict(value["primary_kernel"]),
        fallback_kernel=dict(value["fallback_kernel"]),
        primary_headers=dict(value["primary_headers"]),
        fallback_headers=dict(value["fallback_headers"]),
        nvidia_dkms=dict(value["nvidia_dkms"]),
        initramfs_presets=tuple(value["initramfs_presets"]),
        boot_artifacts=tuple(value["boot_artifacts"]),
        recovery_generation_id=str(value["recovery_generation_id"]),
        activation_requirements=tuple(value["activation_requirements"]),
        execution_environment=str(value["execution_environment"]),
    )


def prepare_native_campaign() -> dict[str, Any]:
    _require_root()
    root = _root()
    source_revision = _source_revision(root)
    machine_id = _machine_id()
    policy = _platform(root)
    if policy.get("boot", {}).get("kernel_update_snapshot_restore_certified") is not True:
        raise RuntimeError("M4B requires certified M3B native restore")
    repo = _repo_contract(policy)
    user = _campaign_user()
    home = Path("/home") / user
    runtime = _runtime_identity(user)
    host = SystemPreparationOps(machine_id=machine_id)
    home_identity = host.home_identity()
    NativeBtrfsOps("upd-20000101T000000Z-000000000000").root_identity()

    now = datetime.now(timezone.utc)
    entropy = secrets.token_hex(6)
    transaction_id = new_transaction_id(now=now, entropy=entropy)
    work = Path("/var/cache/maho/update-m4b") / transaction_id
    discovery_root = work / "discovery"
    cache = work / "staging"
    discovery = IsolatedPacmanDiscovery(
        discovery_root,
        config_path=repo["config_path"],
        required_repositories=repo["repositories"],
    )
    discovered = discover_updates(
        discovery,
        source_revision=source_revision,
        recovery_generation_id=None,
        now=now,
        entropy=entropy,
    )
    transaction = discovered.transaction
    repo = {**repo, "sync_db_sha256": discovery.sync_database_hashes()}
    if transaction["transaction_id"] != transaction_id:
        raise RuntimeError("update discovery transaction identity drifted")
    names = {item["name"] for item in transaction["package_generation"]["packages"]}
    if "linux-cachyos" not in names or "restart" not in transaction["activation"]["requirements"]:
        raise RuntimeError("M4B certification requires a real Primary kernel update generation")

    staging = IsolatedPacmanStaging(discovery.db, cache, config_path=repo["config_path"])
    staged = stage_transaction(transaction, staging, now=now)
    if staged.transaction["state"] != UpdateState.STAGED.value or staged.manifest is None:
        raise RuntimeError("package_staging_incomplete")
    transaction = staged.transaction
    relationships, expected_versions = _relationships(transaction, runtime)
    known_power, power_ok, battery = _power_evidence()
    required = sum(item["installed_size"] + item["download_size"] for item in transaction["package_generation"]["packages"])
    available = min(shutil.disk_usage("/").free, shutil.disk_usage(cache).free)
    generation_current = _generation_is_current(transaction)
    if not generation_current:
        raise RuntimeError("stale_update_transaction")
    if not known_power:
        raise RuntimeError("power_status_unknown")
    if not power_ok:
        raise RuntimeError("power_policy_unsatisfied")
    if Path("/var/lib/pacman/db.lck").exists():
        raise RuntimeError("concurrent_package_or_build_operation")
    if available < required:
        raise RuntimeError("insufficient_install_space")

    # Only after the full package graph and exact payload set are proven do we
    # create any M3B recovery state. This keeps failed solver/staging attempts
    # completely outside the snapshot authority boundary.
    l3_seed = seed_campaign(root=root, machine_id=machine_id, home=home)
    l3_prepared = prepare_l3_campaign(
        root=root,
        machine_id=machine_id,
        transaction_id=l3_seed["transaction_id"],
        generation_id=l3_seed["generation_id"],
    )
    transaction = bind_native_authority(
        transaction,
        recovery_generation_id=l3_seed["generation_id"],
        m3b_evidence={
            "platform_gate": True,
            "l3_transaction_id": l3_seed["transaction_id"],
            "target_snapshot_id": l3_seed["snapshot_id"],
            "target_snapshot_uuid": l3_seed["snapshot_uuid"],
            "emergency_backup_snapshot_id": l3_prepared["backup_snapshot_id"],
        },
        update_kind="m4b-campaign",
        update_evidence={
            "campaign_source_revision": source_revision,
            "native_proof_pending": True,
            "package_repo_config_sha256": repo["config_sha256"],
        },
    )
    evidence = PreparationEvidence(
        discovery_generation_current=generation_current,
        coherent_full_upgrade=True,
        required_disk_bytes=required,
        available_disk_bytes=available,
        power_status_known=known_power,
        power_policy_satisfied=power_ok,
        concurrent_package_or_build_operation=Path("/var/lib/pacman/db.lck").exists(),
        maho_runtime_relationship_known=True,
        primary_kernel_relationship_known=True,
        fallback_kernel_relationship_known=True,
        headers_relationship_known=True,
        nvidia_dkms_relationship_known=True,
        boot_initramfs_relationship_known=True,
        recovery_protection_available=True,
        recovery_generation_id=l3_seed["generation_id"],
        native_l3_certified=True,
        execution_environment="production",
    )
    prepared = prepare_transaction(transaction, staged.manifest, cache, evidence, now=now)
    if prepared.transaction["state"] != UpdateState.PREPARED.value or not prepared.plan.complete:
        raise RuntimeError("M4B production preparation did not reach PREPARED")
    transaction = prepared.transaction
    publish_transaction(_STATE_ROOT, transaction)
    manifest_path = _manifest_path(cache, transaction["package_generation"]["id"])
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    journal = {
        "schema_version": 1,
        "transaction_id": transaction_id,
        "source_revision": source_revision,
        "phase": "prepared",
        "created_at": stamp,
        "updated_at": stamp,
        "history": [{"phase": "prepared", "at": stamp, "details": {}}],
        "user": user,
        "home_identity": home_identity,
        "runtime_identity": runtime,
        "package_repo": repo,
        "work_root": str(work),
        "cache_root": str(cache),
        "manifest_path": str(manifest_path),
        "relationships": relationships,
        "expected_versions": expected_versions,
        "l3_seed": l3_seed,
        "l3_prepared": l3_prepared,
        "power": {"known": known_power, "satisfied": power_ok, "battery_percent": battery},
    }
    path = _campaign_path(machine_id, transaction_id)
    _write_json_atomic(path, journal)
    return {
        "transaction_id": transaction_id,
        "package_generation_id": transaction["package_generation"]["id"],
        "candidate_count": discovered.candidate_count,
        "recovery_generation_id": l3_seed["generation_id"],
        "recovery_snapshot_id": l3_seed["snapshot_id"],
        "emergency_backup_snapshot_id": l3_prepared["backup_snapshot_id"],
        "primary_kernel": {"from": next(item["installed_version"] for item in transaction["package_generation"]["packages"] if item["name"] == "linux-cachyos"), "to": expected_versions["linux-cachyos"]},
        "phase": "prepared",
        "confirmation": update_confirmation(transaction_id, transaction["package_generation"]["id"]),
        "journal_path": str(path),
    }


def execute_native_campaign(transaction_id: str, confirmation: str) -> dict[str, Any]:
    _require_root()
    root = _root()
    source_revision = _source_revision(root)
    machine_id = _machine_id()
    path = _campaign_path(machine_id, transaction_id)
    journal = _read_campaign(path)
    if journal.get("phase") != "prepared" or journal.get("source_revision") != source_revision:
        raise RuntimeError("M4B campaign is not exact prepared source")
    if _repo_contract(_platform(root)) != {k: journal["package_repo"][k] for k in ("config_path", "config_sha256", "repositories")}:
        raise RuntimeError("package_repo_contract_drifted")
    tx_path = transaction_path(_STATE_ROOT, transaction_id)
    transaction = read_transaction(tx_path)
    if transaction["state"] != UpdateState.PREPARED.value:
        raise RuntimeError("update transaction is not PREPARED")
    expected_confirmation = update_confirmation(transaction_id, transaction["package_generation"]["id"])
    if confirmation != expected_confirmation:
        raise RuntimeError("exact native update confirmation token is required")
    if not _generation_is_current(transaction):
        raise RuntimeError("live package generation drifted after preparation")
    host = SystemPreparationOps(machine_id=machine_id)
    if host.home_identity() != journal["home_identity"]:
        raise RuntimeError("/home identity drifted after preparation")
    if _runtime_identity(journal["user"]) != journal["runtime_identity"]:
        raise RuntimeError("Maho runtime identity drifted after preparation")
    l3_journal = read_l3_journal(Path(journal["l3_prepared"]["journal_path"]))
    if l3_journal["phase"] != "prepared":
        raise RuntimeError("M3B recovery transaction is no longer prepared")

    ready = transition_transaction(
        transaction,
        UpdateState.MAINTENANCE_READY,
        reason="explicit M4B certification campaign authority granted",
        evidence={"confirmation": "exact", "campaign_source_revision": source_revision},
    )
    publish_transaction(_STATE_ROOT, ready)
    btrfs = NativeBtrfsOps(transaction_id)
    candidate: dict[str, Any] | None = None
    success = False
    try:
        candidate = btrfs.create_candidate()
        manifest = json.loads(Path(journal["manifest_path"]).read_text(encoding="utf-8"))
        plan = build_execution_plan(
            ready,
            manifest,
            journal["cache_root"],
            journal["relationships"],
            execution_environment="production",
        )
        candidate_state_root = btrfs.offline_root / "var/lib/maho/update"
        ops = NativeCandidateUpdateOps(
            btrfs.offline_root,
            journal["cache_root"],
            transaction=ready,
            expected_versions=journal["expected_versions"],
            runtime_user=journal["user"],
            runtime_identity=journal["runtime_identity"],
            recovery_seed=journal["l3_seed"],
            recovery_journal_path=journal["l3_prepared"]["journal_path"],
            machine_id=machine_id,
            candidate_uuid=candidate["uuid"],
            btrfs_ops=btrfs,
        )
        # Persist every in-flight/recovery state on the still-running root.
        # The candidate receives authority only after the full offline install
        # reaches INSTALLED_PENDING_ACTIVATION.
        execution = execute_update(ready, plan, ops, journal_path=tx_path)
        if execution.transaction["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value:
            publish_transaction(_STATE_ROOT, execution.transaction)
            if candidate is not None and execution.transaction["state"] == UpdateState.FAILED_RECOVERABLE.value:
                btrfs.cleanup_candidate(candidate["uuid"])
            _transition_campaign(path, journal, "execution-failed", transaction_state=execution.transaction["state"])
            return {"transaction_id": transaction_id, "phase": execution.transaction["state"], "activation_ready": False}
        publish_transaction(candidate_state_root, execution.transaction)
        publish_transaction(_STATE_ROOT, execution.transaction)
        frozen = btrfs.freeze_candidate(candidate["uuid"])
        candidate = {**candidate, **frozen}
        admission_paths = btrfs.admission_roots(candidate["uuid"], candidate["admission_base_uuid"])
        roots = CandidateRoots.create(
            transaction_id=guardian_transaction_id(transaction_id),
            candidate_id=candidate["uuid"],
            base_root=admission_paths["base_root"],
            candidate_root=admission_paths["candidate_root"],
        )
        admission = evaluate_production_candidate(roots, execution.transaction, plan)
        admission_payload = admission.as_dict()
        if admission.decision.outcome is AdmissionOutcome.REJECT:
            cleanup = btrfs.cleanup_candidate(candidate["uuid"])
            _transition_campaign(
                path, journal, "admission-rejected", candidate=candidate, plan=plan.as_dict(),
                transaction_state=execution.transaction["state"], admission=admission_payload,
                candidate_cleanup=cleanup,
            )
            return {
                "transaction_id": transaction_id, "phase": "admission-rejected",
                "activation_ready": False, "admission": admission.decision.as_dict(),
            }
        if admission.decision.outcome is AdmissionOutcome.REVIEW:
            journal = _transition_campaign(
                path, journal, "admission-review", candidate=candidate, plan=plan.as_dict(),
                transaction_state=execution.transaction["state"], admission=admission_payload,
            )
            success = True
            return {
                "transaction_id": transaction_id, "phase": "admission-review",
                "candidate_uuid": candidate["uuid"], "activation_ready": False,
                "admission": admission.decision.as_dict(),
                "admission_confirmation": admission_review_confirmation(
                    transaction_id, admission.inspection.graph.graph_id,
                ),
            }
        activation_authority = issue_activation_authority(
            admission, update_transaction_id=transaction_id,
            transaction=execution.transaction, source_revision=source_revision,
        )
        journal = _transition_campaign(
            path,
            journal,
            "installed-pending-activation",
            candidate=candidate,
            plan=plan.as_dict(),
            transaction_state=execution.transaction["state"],
            admission=admission_payload,
            activation_authority=activation_authority.as_dict(),
        )
        success = True
        return {
            "transaction_id": transaction_id,
            "phase": "installed-pending-activation",
            "candidate_uuid": candidate["uuid"],
            "candidate_name": candidate["name"],
            "boot_sha256": frozen["boot_sha256"],
            "admission_authority_id": str(activation_authority.authority_id),
            "reboot_performed": False,
            "activation_confirmation": activation_confirmation(transaction_id, candidate["uuid"]),
        }
    except Exception as exc:
        if candidate is not None:
            try:
                cleanup = btrfs.cleanup_candidate(candidate["uuid"])
            except Exception as cleanup_error:
                cleanup = {"ok": False, "error": str(cleanup_error)}
            try:
                _transition_campaign(
                    path, journal, "execution-exception",
                    error=str(exc), candidate_cleanup=cleanup,
                )
            except Exception:
                pass
        raise
    finally:
        btrfs.close()



def approve_native_admission(transaction_id: str, confirmation: str) -> dict[str, Any]:
    _require_root()
    root = _root()
    source_revision = _source_revision(root)
    machine_id = _machine_id()
    path = _campaign_path(machine_id, transaction_id)
    journal = _read_campaign(path)
    if journal.get("phase") != "admission-review" or journal.get("source_revision") != source_revision:
        raise RuntimeError("M4B campaign is not awaiting exact Admission review")
    transaction = read_transaction(transaction_path(_STATE_ROOT, transaction_id))
    if transaction["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value:
        raise RuntimeError("update authority is not pending activation")
    candidate = journal.get("candidate")
    admission_payload = journal.get("admission")
    if not isinstance(candidate, Mapping) or not isinstance(admission_payload, Mapping):
        raise RuntimeError("Admission review evidence is incomplete")
    mutation_graph = admission_payload.get("mutation_graph")
    if not isinstance(mutation_graph, Mapping):
        raise RuntimeError("Admission mutation graph is missing")
    graph_id = ArtifactID(str(mutation_graph.get("graph_id", "")))
    if confirmation != admission_review_confirmation(transaction_id, graph_id):
        raise RuntimeError("exact Admission graph confirmation token is required")
    plan = _plan_from_dict(journal["plan"])
    btrfs = NativeBtrfsOps(transaction_id)
    try:
        admission_paths = btrfs.admission_roots(candidate["uuid"], candidate["admission_base_uuid"])
        roots = CandidateRoots.create(
            transaction_id=guardian_transaction_id(transaction_id),
            candidate_id=candidate["uuid"],
            base_root=admission_paths["base_root"],
            candidate_root=admission_paths["candidate_root"],
        )
        admission = evaluate_production_candidate(
            roots, transaction, plan, known_safe_graph_ids=(graph_id,),
        )
        if admission.decision.outcome is not AdmissionOutcome.ALLOW:
            raise RuntimeError("reviewed Admission graph no longer reaches ALLOW")
        authority = issue_activation_authority(
            admission, update_transaction_id=transaction_id,
            transaction=transaction, source_revision=source_revision,
        )
    finally:
        btrfs.close()
    _transition_campaign(
        path, journal, "installed-pending-activation",
        admission=admission.as_dict(), activation_authority=authority.as_dict(),
    )
    return {
        "transaction_id": transaction_id,
        "phase": "installed-pending-activation",
        "candidate_uuid": candidate["uuid"],
        "admission_authority_id": str(authority.authority_id),
        "activation_confirmation": activation_confirmation(transaction_id, candidate["uuid"]),
        "reboot_performed": False,
    }

def arm_native_activation(transaction_id: str, confirmation: str) -> dict[str, Any]:
    _require_root()
    root = _root()
    source_revision = _source_revision(root)
    machine_id = _machine_id()
    path = _campaign_path(machine_id, transaction_id)
    journal = _read_campaign(path)
    if journal.get("phase") != "installed-pending-activation" or journal.get("source_revision") != source_revision:
        raise RuntimeError("M4B campaign is not awaiting exact activation")
    transaction = read_transaction(transaction_path(_STATE_ROOT, transaction_id))
    if transaction["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value:
        raise RuntimeError("update authority is not pending activation")
    candidate = journal.get("candidate")
    if not isinstance(candidate, Mapping):
        raise RuntimeError("candidate activation evidence is missing")
    expected = activation_confirmation(transaction_id, str(candidate.get("uuid", "")))
    if confirmation != expected:
        raise RuntimeError("exact candidate activation confirmation token is required")
    if SystemPreparationOps(machine_id=machine_id).home_identity() != journal["home_identity"]:
        raise RuntimeError("/home identity drifted before activation")
    if _runtime_identity(journal["user"]) != journal["runtime_identity"]:
        raise RuntimeError("Maho runtime identity drifted before activation")
    if read_l3_journal(Path(journal["l3_prepared"]["journal_path"]))["phase"] != "prepared":
        raise RuntimeError("M3B recovery transaction is no longer prepared")
    activation_authority = journal.get("activation_authority")
    if not isinstance(activation_authority, Mapping):
        raise RuntimeError("Native Admission activation authority is missing")
    plan = _plan_from_dict(journal["plan"])
    btrfs = NativeBtrfsOps(transaction_id)
    try:
        admission_paths = btrfs.admission_roots(candidate["uuid"], candidate["admission_base_uuid"])
        roots = CandidateRoots.create(
            transaction_id=guardian_transaction_id(transaction_id),
            candidate_id=candidate["uuid"],
            base_root=admission_paths["base_root"],
            candidate_root=admission_paths["candidate_root"],
        )
        verified_authority = verify_activation_authority(
            activation_authority, roots=roots, update_transaction_id=transaction_id,
            transaction=transaction, plan=plan, source_revision=source_revision,
        )
        evidence = btrfs.arm_activation(
            machine_id=machine_id,
            expected_candidate_uuid=candidate["uuid"],
            expected_boot_hashes=candidate["boot_sha256"],
        )
    finally:
        btrfs.close()
    journal = _transition_campaign(
        path, journal, "activation-armed", activation=evidence,
        admission_authority_consumed=str(verified_authority.authority_id),
    )
    return {
        "transaction_id": transaction_id,
        "phase": "activation-armed",
        **evidence,
        "next_action": "explicit normal Primary reboot",
    }


def verify_native_activation(transaction_id: str) -> dict[str, Any]:
    _require_root()
    root = _root()
    source_revision = _source_revision(root)
    machine_id = _machine_id()
    path = _campaign_path(machine_id, transaction_id)
    journal = _read_campaign(path)
    if journal.get("phase") != "activation-armed" or journal.get("source_revision") != source_revision:
        raise RuntimeError("M4B campaign is not awaiting postboot verification")
    tx_path = transaction_path(_STATE_ROOT, transaction_id)
    transaction = read_transaction(tx_path)
    if transaction["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value:
        raise RuntimeError("activated candidate did not preserve pending transaction authority")
    plan = _plan_from_dict(journal["plan"])
    activation = journal["activation"]
    ops = PostBootActivationOps(
        transaction=transaction,
        expected_versions=journal["expected_versions"],
        runtime_user=journal["user"],
        home_identity=journal["home_identity"],
        runtime_identity=journal["runtime_identity"],
        candidate_uuid=activation["candidate_uuid"],
        previous_root_uuid=activation["previous_root_uuid"],
        previous_root_name=activation["previous_root_name"],
        boot_hashes=activation["boot_sha256"],
        recovery_seed=journal["l3_seed"],
        machine_id=machine_id,
    )
    result = verify_activation(transaction, plan, ops, journal_path=tx_path)
    admission_cleanup: dict[str, Any] | None = None
    if result.transaction["state"] == UpdateState.HEALTHY.value:
        candidate = journal.get("candidate")
        if not isinstance(candidate, Mapping) or not isinstance(candidate.get("admission_base_uuid"), str):
            raise RuntimeError("postboot Admission base identity is missing")
        btrfs = NativeBtrfsOps(transaction_id)
        try:
            admission_cleanup = btrfs.cleanup_admission_base(candidate["admission_base_uuid"])
        finally:
            btrfs.close()
        if admission_cleanup.get("ok") is not True:
            raise RuntimeError("verified update could not retire its Admission base")
    publish_transaction(_STATE_ROOT, result.transaction)
    receipt = record_receipt(_STATE_ROOT, result.transaction)
    final_phase = "verified" if result.transaction["state"] == UpdateState.HEALTHY.value else "attention-required"
    _transition_campaign(
        path, journal, final_phase, transaction_state=result.transaction["state"],
        receipt_path=str(receipt), admission_base_cleanup=admission_cleanup,
    )
    return {
        "transaction_id": transaction_id,
        "phase": final_phase,
        "transaction_state": result.transaction["state"],
        "blockers": result.transaction.get("blockers", []),
        "receipt_path": str(receipt),
        "admission_base_cleanup": admission_cleanup,
        "reboot_performed": False,
    }


def status_native_campaign(transaction_id: str) -> dict[str, Any]:
    machine_id = _machine_id()
    journal = _read_campaign(_campaign_path(machine_id, transaction_id))
    state = None
    try:
        state = read_transaction(transaction_path(_STATE_ROOT, transaction_id))["state"]
    except (OSError, ValueError):
        pass
    return {
        "transaction_id": transaction_id,
        "phase": journal["phase"],
        "transaction_state": state,
        "recovery_generation_id": journal["l3_seed"]["generation_id"],
        "candidate": journal.get("candidate"),
        "activation": journal.get("activation"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="maho-update-campaign")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    execute = sub.add_parser("execute")
    execute.add_argument("transaction_id")
    execute.add_argument("--confirm", required=True)
    approve = sub.add_parser("approve-admission")
    approve.add_argument("transaction_id")
    approve.add_argument("--confirm", required=True)
    activate = sub.add_parser("activate")
    activate.add_argument("transaction_id")
    activate.add_argument("--confirm", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("transaction_id")
    status = sub.add_parser("status")
    status.add_argument("transaction_id")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            payload = prepare_native_campaign()
        elif args.command == "execute":
            payload = execute_native_campaign(args.transaction_id, args.confirm)
        elif args.command == "approve-admission":
            payload = approve_native_admission(args.transaction_id, args.confirm)
        elif args.command == "activate":
            payload = arm_native_activation(args.transaction_id, args.confirm)
        elif args.command == "verify":
            payload = verify_native_activation(args.transaction_id)
        else:
            payload = status_native_campaign(args.transaction_id)
    except (RuntimeError, ValueError, LookupError, PermissionError) as exc:
        payload = {
            "phase": "blocked",
            "blockers": [_blocker_code(exc)],
            "detail": str(exc),
            "error_type": type(exc).__name__,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        raise SystemExit(3)
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
