#!/usr/bin/env python3
"""Root-owned native certification controller for one bounded MahoOS L3 restore."""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import pwd
import re
import secrets
from typing import Any, Mapping

from maho_recovery_discovery import SystemProbe, discover_recovery_generations
from maho_system_restore import plan_system_restore, plan_system_restore_preparation
from maho_system_restore_evidence import collect_provider_evidence
from maho_system_restore_host import SystemPreparationOps
from maho_system_restore_journal import (
    journal_path,
    new_transaction_id,
    read_journal,
    transition_journal,
    write_journal,
)
from maho_system_restore_preparation import prepare_restore_transaction
from maho_system_restore_provider import run_pinned_provider
from maho_system_restore_runtime import SystemRestoreRuntimeOps
from maho_system_restore_transaction import execute_prepared_restore, verify_postboot_restore

_TXID = re.compile(r"l3-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")
_GID = re.compile(r"g3-[0-9a-f]{24}")
_SCHEMA = 1

def _root() -> Path:
    override = os.environ.get("MAHO_L3_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1]


def _machine_id() -> str:
    value = Path("/etc/machine-id").read_text(encoding="utf-8").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise RuntimeError("invalid machine id")
    return value


def _source_revision(root: Path) -> str:
    value = (root / "SOURCE_REVISION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RuntimeError("invalid installed L3 source revision")
    return value


def _policy(root: Path) -> Mapping[str, Any]:
    data = json.loads((root / "config/platform.json").read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise RuntimeError("platform policy is not an object")
    return data


def _report(policy: Mapping[str, Any]):
    return discover_recovery_generations(policy, SystemProbe())


def _generation(report: Any, generation_id: str):
    return next((g for g in report.generations if g.generation_id == generation_id), None)

def _home_for_sudo_user() -> Path:
    user = os.environ.get("SUDO_USER", "").strip()
    if not user or user == "root":
        raise RuntimeError("native L3 seed requires sudo from a non-root user")
    entry = pwd.getpwnam(user)
    home = Path(entry.pw_dir)
    if home.parent != Path("/home"):
        raise RuntimeError("native L3 campaign requires a /home user")
    return home


def marker_paths(transaction_id: str, home: Path) -> tuple[Path, Path]:
    if not _TXID.fullmatch(transaction_id):
        raise ValueError("invalid L3 transaction id")
    if home.parent != Path("/home"):
        raise ValueError("invalid campaign home path")
    root_marker = Path("/var/lib/maho/l3-campaign") / f"{transaction_id}.root-marker"
    home_marker = home / ".maho-l3-campaign" / f"{transaction_id}.home-marker"
    return root_marker, home_marker


def _seed_path(machine_id: str, transaction_id: str, boot_root: Path = Path("/boot")) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", machine_id):
        raise ValueError("invalid machine id")
    if not _TXID.fullmatch(transaction_id):
        raise ValueError("invalid L3 transaction id")
    return boot_root / machine_id / "maho/recovery/seeds" / f"{transaction_id}.json"


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in {errno.EINVAL, errno.EOPNOTSUPP}:
                raise
    finally:
        os.close(fd)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n").encode()
    temp = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(temp, flags, 0o600)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temp, path)
    _fsync_directory(path.parent)


def _write_marker(path: Path, text: str, *, uid: int, gid: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        data = text.encode("utf-8")
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        os.fchown(fd, uid, gid)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(path.parent)


def _prepare_marker_directories(home: Path, user: Any) -> tuple[Path, Path]:
    if home.is_symlink() or not home.is_dir():
        raise RuntimeError("campaign home is not a real directory")
    root_dir = Path("/var/lib/maho/l3-campaign")
    root_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    if root_dir.is_symlink() or not root_dir.is_dir():
        raise RuntimeError("root campaign marker directory is unsafe")
    os.chmod(root_dir, 0o700)

    home_dir = home / ".maho-l3-campaign"
    if home_dir.is_symlink():
        raise RuntimeError("home campaign marker directory cannot be a symlink")
    home_dir.mkdir(mode=0o700, exist_ok=True)
    if home_dir.is_symlink() or not home_dir.is_dir():
        raise RuntimeError("home campaign marker directory is unsafe")
    os.chown(home_dir, user.pw_uid, user.pw_gid)
    os.chmod(home_dir, 0o700)
    return root_dir, home_dir

def _validate_seed(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    if data.get("schema_version") != _SCHEMA:
        raise ValueError("unsupported L3 seed schema")
    txid = data.get("transaction_id")
    gid = data.get("generation_id")
    if not isinstance(txid, str) or not _TXID.fullmatch(txid):
        raise ValueError("invalid L3 seed transaction id")
    if not isinstance(gid, str) or not _GID.fullmatch(gid):
        raise ValueError("invalid L3 seed generation id")
    if not isinstance(data.get("snapshot_id"), int) or data["snapshot_id"] <= 0:
        raise ValueError("invalid L3 seed snapshot id")
    for key in ("snapshot_uuid", "source_revision", "root_marker", "home_marker", "home_user"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError(f"invalid L3 seed {key}")
    if not re.fullmatch(r"[0-9a-f]{40}", data["source_revision"]):
        raise ValueError("invalid L3 seed source revision")
    user = data["home_user"]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}", user):
        raise ValueError("invalid L3 seed home user")
    expected_root = f"/var/lib/maho/l3-campaign/{txid}.root-marker"
    expected_home = f"/home/{user}/.maho-l3-campaign/{txid}.home-marker"
    if data["root_marker"] != expected_root or data["home_marker"] != expected_home:
        raise ValueError("L3 seed marker paths are not transaction-bound")
    return data


def _read_seed(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("L3 seed is not an object")
    seed = _validate_seed(data)
    if path.stem != seed["transaction_id"] or path.suffix != ".json":
        raise ValueError("L3 seed path does not match transaction id")
    return seed


def _markers_complete(seed: Mapping[str, Any]) -> bool:
    return Path(str(seed["root_marker"])).is_file() and Path(str(seed["home_marker"])).is_file()


def _marker_blockers(seed: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if Path(str(seed["root_marker"])).exists():
        blockers.append("root_marker_survived_restore")
    if not Path(str(seed["home_marker"])).is_file():
        blockers.append("home_marker_missing_after_restore")
    return blockers


def _seed_blockers(report: Any) -> tuple[str, ...]:
    platform = report.current_platform
    blockers: list[str] = []
    if platform.get("recovery_overlay_active") is True:
        blockers.append("normal_root_required")
    if platform.get("root_fstype") != "btrfs":
        blockers.append("root_not_btrfs")
    if platform.get("root_fsroot") != "/@":
        blockers.append("live_root_not_at")
    if platform.get("home_scope") != "excluded":
        blockers.append("home_not_separate")
    return tuple(blockers)

def seed_campaign(
    *,
    root: Path,
    machine_id: str,
    home: Path,
    transaction_id: str | None = None,
    ops: SystemPreparationOps | None = None,
    boot_root: Path = Path("/boot"),
) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise PermissionError("L3 native seed requires root")
    txid = transaction_id or new_transaction_id()
    source_revision = _source_revision(root)
    policy = _policy(root)
    before = _report(policy)
    blockers = _seed_blockers(before)
    if blockers:
        raise RuntimeError("L3 seed blocked: " + ", ".join(blockers))
    host = ops or SystemPreparationOps(machine_id=machine_id, boot_root=boot_root)
    snapshot_id = host.create_known_good_target(txid)
    evidence = host.wait_for_backup(snapshot_id)
    if evidence.get("boot_state_coherent") is not True:
        raise RuntimeError("new L3 target did not become boot-coherent")
    after = _report(policy)
    generation = next((g for g in after.generations if g.snapshot.snapshot_id == snapshot_id), None)
    if generation is None or generation.generation_id is None:
        raise RuntimeError("new L3 target generation was not discovered")
    if not generation.eligible or not generation.known_good:
        raise RuntimeError("new L3 target generation is not known-good and eligible")
    snapshot_uuid = host.snapshot_uuid(snapshot_id)

    root_marker, home_marker = marker_paths(txid, home)
    user = pwd.getpwnam(home.name)
    root_dir, home_dir = _prepare_marker_directories(home, user)
    if root_marker.parent != root_dir or home_marker.parent != home_dir:
        raise RuntimeError("campaign marker directories are not exact")
    _write_marker(root_marker, f"root marker {txid}\n", uid=0, gid=0)
    _write_marker(home_marker, f"home marker {txid}\n", uid=user.pw_uid, gid=user.pw_gid)

    seed = _validate_seed({
        "schema_version": _SCHEMA,
        "transaction_id": txid,
        "source_revision": source_revision,
        "generation_id": generation.generation_id,
        "snapshot_id": snapshot_id,
        "snapshot_uuid": snapshot_uuid,
        "root_marker": str(root_marker),
        "home_marker": str(home_marker),
        "home_user": home.name,
    })
    path = _seed_path(machine_id, txid, boot_root)
    _write_json_atomic(path, seed)
    return {**seed, "seed_path": str(path)}


def prepare_campaign(
    *,
    root: Path,
    machine_id: str,
    transaction_id: str,
    generation_id: str,
    boot_root: Path = Path("/boot"),
    ops: SystemPreparationOps | None = None,
) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise PermissionError("L3 native preparation requires root")
    seed = _read_seed(_seed_path(machine_id, transaction_id, boot_root))
    source_revision = _source_revision(root)
    if seed["source_revision"] != source_revision:
        raise RuntimeError("L3 source revision drifted after seed")
    if seed["generation_id"] != generation_id:
        raise RuntimeError("requested generation differs from seeded target")
    if not _markers_complete(seed):
        raise RuntimeError("native campaign markers are incomplete")

    policy = _policy(root)
    report = _report(policy)
    provider = collect_provider_evidence(policy)
    plan = plan_system_restore_preparation(report, generation_id, policy, provider)
    host = ops or SystemPreparationOps(machine_id=machine_id, boot_root=boot_root)
    generation = _generation(report, generation_id)
    if generation is None or generation.snapshot.snapshot_id != seed["snapshot_id"]:
        raise RuntimeError("seeded target generation is no longer discoverable")
    target_uuid = host.snapshot_uuid(seed["snapshot_id"])
    if target_uuid != seed["snapshot_uuid"]:
        raise RuntimeError("seeded target snapshot UUID drifted")
    home = host.home_identity()
    result = prepare_restore_transaction(
        plan,
        source_revision=source_revision,
        target_snapshot_uuid=target_uuid,
        home_evidence=home,
        provider_evidence=provider,
        machine_id=machine_id,
        boot_root=boot_root,
        ops=host,
        transaction_id=transaction_id,
    )
    return {
        "transaction_id": result.transaction_id,
        "generation_id": generation_id,
        "journal_path": result.journal_path,
        "backup_snapshot_id": result.backup_snapshot_id,
        "backup_snapshot_uuid": result.backup_snapshot_uuid,
        "restore_authorized": False,
    }


def _journal_for(machine_id: str, transaction_id: str, boot_root: Path) -> Path:
    return journal_path(boot_root, machine_id, transaction_id)

def execute_campaign(
    *,
    root: Path,
    machine_id: str,
    transaction_id: str,
    generation_id: str,
    confirmation: str,
    boot_root: Path = Path("/boot"),
    ops: SystemPreparationOps | None = None,
) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise PermissionError("L3 native execution requires root")
    expected_confirmation = f"RESTORE:{generation_id}:{transaction_id}"
    if confirmation != expected_confirmation:
        raise RuntimeError("exact destructive confirmation token is required")
    seed = _read_seed(_seed_path(machine_id, transaction_id, boot_root))
    if seed["generation_id"] != generation_id:
        raise RuntimeError("requested generation differs from seeded target")
    source_revision = _source_revision(root)
    if seed["source_revision"] != source_revision:
        raise RuntimeError("L3 source revision drifted after seed")
    jpath = _journal_for(machine_id, transaction_id, boot_root)
    journal = read_journal(jpath)
    if journal["phase"] != "prepared":
        raise RuntimeError("L3 transaction is not in prepared phase")

    policy = _policy(root)
    report = _report(policy)
    provider = collect_provider_evidence(policy)
    plan = plan_system_restore(report, generation_id, policy, provider)
    host = ops or SystemPreparationOps(machine_id=machine_id, boot_root=boot_root)
    target_uuid = host.snapshot_uuid(int(seed["snapshot_id"]))
    backup = host.wait_for_backup(int(journal["backup"]["snapshot_id"]))
    home = host.home_identity()
    runtime = SystemRestoreRuntimeOps(
        journal,
        machine_id=machine_id,
        transaction_id=transaction_id,
        preparation_ops=host,
    )

    result = execute_prepared_restore(
        jpath,
        source_revision=source_revision,
        plan=plan,
        provider_evidence=provider,
        target_snapshot_uuid=target_uuid,
        backup_evidence=backup,
        home_evidence=home,
        provider_runner=run_pinned_provider,
        structural_collector=runtime.structural_evidence,
    )
    return {
        "transaction_id": transaction_id,
        "generation_id": generation_id,
        "phase": result.phase,
        "provider_exit_code": result.provider_exit_code,
        "mutation_started": result.mutation_started,
        "blockers": list(result.blockers),
        "reboot_performed": False,
    }


def _fail_marker_verification(path: Path, blockers: list[str]) -> dict[str, Any]:
    journal = read_journal(path)
    failed = transition_journal(
        journal,
        "verify-failed",
        details={"stage": "native-campaign-markers", "blockers": blockers},
    )
    write_journal(path, failed)
    return failed


def verify_campaign(
    *,
    root: Path,
    machine_id: str,
    transaction_id: str,
    boot_root: Path = Path("/boot"),
    ops: SystemPreparationOps | None = None,
) -> dict[str, Any]:
    if os.geteuid() != 0:
        raise PermissionError("L3 native verification requires root")
    seed = _read_seed(_seed_path(machine_id, transaction_id, boot_root))
    source_revision = _source_revision(root)
    if seed["source_revision"] != source_revision:
        raise RuntimeError("L3 source revision drifted after restore")
    jpath = _journal_for(machine_id, transaction_id, boot_root)
    journal = read_journal(jpath)
    if journal["phase"] != "restored-awaiting-reboot":
        raise RuntimeError("L3 transaction is not awaiting postboot verification")

    marker_blockers = _marker_blockers(seed)
    if marker_blockers:
        failed = _fail_marker_verification(jpath, marker_blockers)
        return {
            "transaction_id": transaction_id,
            "phase": failed["phase"],
            "blockers": marker_blockers,
            "root_marker_removed": False,
            "home_marker_preserved": False,
        }

    host = ops or SystemPreparationOps(machine_id=machine_id, boot_root=boot_root)
    runtime = SystemRestoreRuntimeOps(
        journal,
        machine_id=machine_id,
        transaction_id=transaction_id,
        preparation_ops=host,
    )
    evidence = runtime.postboot_evidence()
    result = verify_postboot_restore(jpath, evidence)
    return {
        "transaction_id": transaction_id,
        "generation_id": seed["generation_id"],
        "phase": result.phase,
        "blockers": list(result.blockers),
        "root_marker_removed": True,
        "home_marker_preserved": True,
    }


def status_campaign(*, machine_id: str, transaction_id: str, boot_root: Path = Path("/boot")) -> dict[str, Any]:
    seed_path = _seed_path(machine_id, transaction_id, boot_root)
    seed = _read_seed(seed_path)
    jpath = _journal_for(machine_id, transaction_id, boot_root)
    journal = read_journal(jpath) if jpath.is_file() else None
    return {
        "transaction_id": transaction_id,
        "generation_id": seed["generation_id"],
        "snapshot_id": seed["snapshot_id"],
        "journal_phase": journal["phase"] if journal else None,
        "root_marker_exists": Path(seed["root_marker"]).exists(),
        "home_marker_exists": Path(seed["home_marker"]).is_file(),
        "seed_path": str(seed_path),
        "journal_path": str(jpath),
    }

def _print(payload: Mapping[str, Any]) -> None:
    print(json.dumps(dict(payload), indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(prog="maho-l3-campaign")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="create known-good target, then root/home test markers")

    prepare = sub.add_parser("prepare", help="create emergency backup and prepared journal")
    prepare.add_argument("transaction_id")
    prepare.add_argument("generation_id")

    execute = sub.add_parser("execute", help="perform one exact restore attempt from recovery boot")
    execute.add_argument("transaction_id")
    execute.add_argument("generation_id")
    execute.add_argument("--confirm", required=True)

    verify = sub.add_parser("verify", help="finalize after normal-root reboot")
    verify.add_argument("transaction_id")

    status = sub.add_parser("status", help="show durable native-campaign state")
    status.add_argument("transaction_id")
    args = parser.parse_args()

    root = _root()
    machine_id = _machine_id()
    if args.command == "seed":
        payload = seed_campaign(root=root, machine_id=machine_id, home=_home_for_sudo_user())
    elif args.command == "prepare":
        payload = prepare_campaign(
            root=root, machine_id=machine_id,
            transaction_id=args.transaction_id, generation_id=args.generation_id,
        )
    elif args.command == "execute":
        payload = execute_campaign(
            root=root, machine_id=machine_id,
            transaction_id=args.transaction_id, generation_id=args.generation_id,
            confirmation=args.confirm,
        )
    elif args.command == "verify":
        payload = verify_campaign(root=root, machine_id=machine_id, transaction_id=args.transaction_id)
    else:
        payload = status_campaign(machine_id=machine_id, transaction_id=args.transaction_id)
    _print(payload)


if __name__ == "__main__":
    main()
