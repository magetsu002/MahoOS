#!/usr/bin/env python3
"""One-time production certification campaign for normal-impact Maho Update."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import shutil
from typing import Any, Mapping, Sequence

from maho_update_discovery import IsolatedPacmanDiscovery, discover_coherent_subset_updates
from maho_update_native import NativeBtrfsOps
from maho_update_normal import NormalPreparationEvidence, execute_normal_certification, prepare_normal_transaction
from maho_update_normal_authority import (
    certification_confirmation,
    issue_normal_execution_authority,
    publish_normal_execution_authority,
)
from maho_update_normal_host import NormalProductionOps
from maho_update_staging import IsolatedPacmanStaging, stage_transaction
from maho_update_state import UpdateState, publish_transaction, read_transaction, transaction_path

STATE_ROOT = Path("/var/lib/maho/update")
SAFE_STORAGE_RESERVE_BYTES = 2 * 1024 * 1024 * 1024
CACHE_ROOT = Path("/var/cache/maho/update-normal-certification")
RUN_ROOT = Path("/run/maho-update-normal")
def _require_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("normal update certification requires root")


def _campaign_root() -> Path:
    root = Path(os.environ.get("MAHO_UPDATE_CAMPAIGN_ROOT", ""))
    if not root.is_absolute() or not root.is_dir():
        raise RuntimeError("root-owned update campaign payload is unavailable")
    if root.parent != Path("/usr/lib/maho/update-campaign"):
        raise RuntimeError("normal certification refuses non-platform campaign payload")
    return root


def _source_revision(root: Path) -> str:
    value = (root / "SOURCE_REVISION").read_text(encoding="utf-8").strip()
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value) or root.name != value:
        raise RuntimeError("installed campaign source revision is invalid")
    return value


def _canonical_config(root: Path) -> Path:
    source = root / "config/platform/maho-pacman.conf"
    live = Path("/etc/maho/pacman.conf")
    if source.is_symlink() or live.is_symlink() or not source.is_file() or not live.is_file():
        raise RuntimeError("canonical Maho Pacman authority is unavailable")
    if source.read_bytes() != live.read_bytes():
        raise RuntimeError("live Maho Pacman authority differs from root-owned campaign source")
    return live


def _required_repositories(root: Path) -> tuple[str, ...]:
    data = json.loads((root / "config/platform.json").read_text(encoding="utf-8"))
    value = data.get("update", {}).get("required_repositories")
    if not isinstance(value, list) or not value or any(not isinstance(x, str) or not x for x in value):
        raise RuntimeError("required repository authority is invalid")
    return tuple(value)


def _power() -> tuple[bool, bool, dict[str, Any]]:
    supplies = Path("/sys/class/power_supply")
    mains, batteries = [], []
    if not supplies.is_dir():
        return False, False, {"reason": "power_supply_sysfs_missing"}
    for item in sorted(supplies.iterdir()):
        try:
            kind = (item / "type").read_text().strip()
        except OSError:
            continue
        if kind == "Mains":
            try: online = (item / "online").read_text().strip() == "1"
            except OSError: online = False
            mains.append({"name": item.name, "online": online})
        elif kind == "Battery":
            try: capacity = int((item / "capacity").read_text().strip())
            except (OSError, ValueError): capacity = -1
            batteries.append({"name": item.name, "capacity": capacity})
    known = bool(mains or batteries)
    ok = any(x["online"] for x in mains) or (bool(batteries) and all(x["capacity"] >= 50 for x in batteries))
    return known, ok, {"mains": mains, "batteries": batteries}


def _private_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path); os.chmod(path, 0o600)
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass


def _require_positive(value: Mapping[str, Any], stage: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("ok") is not True:
        detail = json.dumps(dict(value), sort_keys=True, separators=(",", ":")) if isinstance(value, Mapping) else repr(value)
        if len(detail) > 4000:
            detail = detail[:4000] + "..."
        raise RuntimeError(f"normal certification {stage} failed: {detail}")
    return dict(value)


def _require_certification_slot(root: Path = STATE_ROOT) -> None:
    pointer = root / 'current'
    if not pointer.exists() and not pointer.is_symlink():
        return
    if pointer.is_symlink() or not pointer.is_file():
        raise RuntimeError('normal certification pointer invalid')
    transaction_id = pointer.read_text().strip()
    if re.fullmatch(r'upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}', transaction_id) is None:
        raise RuntimeError('normal certification transaction id invalid')
    current = read_transaction(transaction_path(root, transaction_id))
    if current['state'] not in ('HEALTHY', 'RECOVERED'):
        raise RuntimeError('normal_certification_would_replace_unresolved_update_transaction')


def certify_normal_update(
    target_packages: Sequence[str], confirmation: str, *, preflight_only: bool = False,
) -> dict[str, Any]:
    _require_root()
    root = _campaign_root()
    revision = _source_revision(root)
    if confirmation != certification_confirmation(revision):
        raise ValueError("exact normal certification confirmation token is required")
    targets = tuple(sorted(set(str(x) for x in target_packages)))
    if not targets:
        raise ValueError("normal certification requires an explicit package target")
    config = _canonical_config(root)
    repos = _required_repositories(root)
    power_known, power_ok, power = _power()
    if not power_known or not power_ok:
        raise RuntimeError("normal certification power policy is not satisfied")
    if Path("/var/lib/pacman/db.lck").exists():
        raise RuntimeError("live Pacman lock exists")
    _require_certification_slot()

    CACHE_ROOT.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chmod(CACHE_ROOT, 0o755)
    work = CACHE_ROOT / f"run-{os.getpid()}-{secrets.token_hex(6)}"
    work.mkdir(mode=0o755, parents=True, exist_ok=False)
    os.chmod(work, 0o755)
    txid = None
    btrfs = None
    candidate = None
    ops = None
    try:
        discovery = IsolatedPacmanDiscovery(work / "discovery", config_path=config, required_repositories=repos)
        result = discover_coherent_subset_updates(
            discovery, target_packages=targets, source_revision=revision,
        )
        transaction = result.transaction
        txid = transaction["transaction_id"]
        publish_transaction(STATE_ROOT, transaction)
        cache = work / "staging"
        staging = IsolatedPacmanStaging(Path(result.isolated_db), cache, config_path=config)
        free = shutil.disk_usage("/").free
        staged = stage_transaction(transaction, staging, available_bytes=free)
        if staged.transaction["state"] != UpdateState.STAGED.value or staged.manifest is None:
            raise RuntimeError("normal certification exact package staging failed")
        effects = staged.manifest.get("effects", {})
        if effects.get("classification") != "normal":
            raise RuntimeError("certification target became boot-critical after exact artifact inspection")
        if effects.get("effects") != ["ordinary-files"] or effects.get("activation_requirements") != []:
            raise RuntimeError("first normal certification is limited to ordinary-files with no activation requirement")
        publish_transaction(STATE_ROOT, staged.transaction)

        btrfs = NativeBtrfsOps(txid, run_root=RUN_ROOT)
        btrfs.root_identity()
        required = sum(
            int(x.get("download_size", 0)) + int(x.get("installed_size", 0))
            for x in staged.transaction["package_generation"]["packages"]
        ) + 512 * 1024 * 1024
        prep = prepare_normal_transaction(
            staged.transaction, staged.manifest, cache,
            NormalPreparationEvidence(
                True, True, required, free, power_known, power_ok, False, True, True,
                "production", SAFE_STORAGE_RESERVE_BYTES, True,
            ),
        )
        if prep.transaction["state"] != UpdateState.PREPARED.value:
            raise RuntimeError("normal certification preparation did not reach PREPARED")
        publish_transaction(STATE_ROOT, prep.transaction)

        candidate = btrfs.create_candidate()
        ops = NormalProductionOps(
            transaction=prep.transaction, cache_root=cache, btrfs=btrfs, candidate=candidate,
        )
        if preflight_only:
            install = _require_positive(ops.install_candidate(prep.plan), "candidate installation")
            admission = _require_positive(ops.guardian_admit(prep.plan), "Guardian Admission")
            activation_preflight = _require_positive(
                ops.preflight_activation(prep.plan), "live activation preflight"
            )
            if ops.live_mutation_started:
                raise RuntimeError("normal preflight unexpectedly started live mutation")
            cleanup = ops.cleanup_success()
            if cleanup.get("ok") is not True:
                raise RuntimeError("normal preflight could not retire candidate/base snapshots")
            candidate = None
            receipt = {
                "schema_version": 1,
                "kind": "maho-normal-update-certification-preflight",
                "source_revision": revision,
                "transaction_id": txid,
                "package_generation_id": prep.transaction["package_generation"]["id"],
                "targets": list(targets),
                "power": power,
                "effects": effects,
                "candidate_install": install,
                "guardian": ops.admission.as_dict() if ops.admission is not None else None,
                "activation_preflight": activation_preflight,
                "candidate_cleanup": cleanup,
                "live_mutation_started": False,
                "result": "READY_FOR_LIVE",
            }
            receipt_path = STATE_ROOT / "normal-certification" / f"{txid}-preflight.json"
            _private_json(receipt_path, receipt)
            return {
                "phase": "preflight-ready",
                "transaction_id": txid,
                "targets": list(targets),
                "receipt_path": str(receipt_path),
                "live_mutation_started": False,
                "candidate_cleanup": cleanup,
                "activation_preflight": activation_preflight,
                "reboot_performed": False,
            }
        execution = execute_normal_certification(
            prep.transaction, prep.plan, ops, confirmation=confirmation,
        )
        publish_transaction(STATE_ROOT, execution.transaction)
        if execution.transaction["state"] != UpdateState.HEALTHY.value:
            raise RuntimeError("normal certification execution did not reach HEALTHY")
        if ops.admission is None or ops.last_verification is None or not ops.last_verification.get("ok"):
            raise RuntimeError("normal certification lacks Guardian or verification evidence")

        pkgmap = {x["name"]: x for x in prep.transaction["package_generation"]["packages"]}
        package_evidence = [
            {
                "name": p["name"],
                "installed_version": pkgmap[p["name"]]["installed_version"],
                "candidate_version": pkgmap[p["name"]]["candidate_version"],
                "sha256": p["sha256"],
            }
            for p in staged.manifest["payloads"]
        ]
        authority = issue_normal_execution_authority(
            source_revision=revision,
            transaction_id=txid,
            package_generation_id=prep.transaction["package_generation"]["id"],
            graph_id=str(ops.admission.inspection.graph.graph_id),
            packages=package_evidence,
            effects=prep.plan.effects,
            activation_requirements=prep.plan.activation_requirements,
            verification=ops.last_verification,
            candidate_root_identity=ops.admission.inspection.candidate_root_identity,
            base_root_identity=ops.admission.inspection.base_root_identity,
        )
        cleanup = ops.cleanup_success()
        if cleanup.get("ok") is not True:
            raise RuntimeError("certified update could not retire candidate/base snapshots")
        authority_path = publish_normal_execution_authority(authority)
        receipt = {
            "schema_version": 1, "kind": "maho-normal-update-certification",
            "source_revision": revision, "transaction_id": txid,
            "package_generation_id": prep.transaction["package_generation"]["id"],
            "targets": list(targets), "power": power, "effects": effects,
            "guardian": ops.admission.as_dict(), "verification": ops.last_verification,
            "authority_id": authority["authority_id"], "authority_path": str(authority_path),
            "candidate_cleanup": cleanup, "result": "HEALTHY",
        }
        receipt_path = STATE_ROOT / "normal-certification" / f"{txid}.json"
        _private_json(receipt_path, receipt)
        return {
            "phase": "certified", "transaction_id": txid, "targets": list(targets),
            "authority_id": authority["authority_id"], "authority_path": str(authority_path),
            "receipt_path": str(receipt_path), "effects": list(prep.plan.effects),
            "activation_requirements": list(prep.plan.activation_requirements),
            "reboot_performed": False,
        }
    except Exception as exc:
        cleanup = None
        if btrfs is not None and candidate is not None and (ops is None or not ops.live_mutation_started):
            try: cleanup = btrfs.cleanup_candidate(str(candidate["uuid"]))
            except Exception as err: cleanup = {"ok": False, "error": str(err)}
        failure = {
            "schema_version": 1, "kind": "maho-normal-update-certification-failure",
            "source_revision": revision, "transaction_id": txid, "targets": list(targets),
            "detail": str(exc), "error_type": type(exc).__name__,
            "live_mutation_started": bool(ops and ops.live_mutation_started),
            "candidate_cleanup": cleanup,
        }
        name = txid or f"pre-{os.getpid()}-{secrets.token_hex(4)}"
        receipt_path = STATE_ROOT / "normal-certification" / f"{name}-failed.json"
        _private_json(receipt_path, failure)
        raise RuntimeError(f"{exc}; failure_receipt={receipt_path}") from exc
    finally:
        if btrfs is not None:
            try: btrfs.close()
            except Exception: pass
        shutil.rmtree(work, ignore_errors=True)
