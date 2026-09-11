#!/usr/bin/env python3
"""Durable cross-reboot journal for bounded MahoOS L3 restore."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any, Mapping

SCHEMA_VERSION = 1
_MACHINE_ID = re.compile(r"[0-9a-f]{32}")
_TRANSACTION_ID = re.compile(r"l3-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")
_PHASES = {
    "prepared",
    "restore-started",
    "provider-returned",
    "restored-awaiting-reboot",
    "structural-verified",
    "provider-failed",
    "verify-failed",
}
_TRANSITIONS = {
    "prepared": {"restore-started"},
    "restore-started": {"provider-returned", "provider-failed"},
    "provider-returned": {"restored-awaiting-reboot", "verify-failed"},
    "restored-awaiting-reboot": {"structural-verified", "verify-failed"},
}


def new_transaction_id(*, now: datetime | None = None, entropy: str | None = None) -> str:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    suffix = entropy or secrets.token_hex(4)
    if not re.fullmatch(r"[0-9a-f]{8}", suffix):
        raise ValueError("transaction entropy must be exactly eight lowercase hex characters")
    return f"l3-{current.strftime('%Y%m%dT%H%M%SZ')}-{suffix}"


def journal_path(boot_root: str | os.PathLike[str], machine_id: str, transaction_id: str) -> Path:
    machine_id = machine_id.strip().lower()
    if not _MACHINE_ID.fullmatch(machine_id):
        raise ValueError("invalid machine id")
    if not _TRANSACTION_ID.fullmatch(transaction_id):
        raise ValueError("invalid L3 transaction id")
    return Path(boot_root) / machine_id / "maho" / "recovery" / "transactions" / f"{transaction_id}.json"


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"journal {name} must be an object")
    return value


def validate_journal(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported L3 journal schema")
    transaction_id = data.get("transaction_id")
    if not isinstance(transaction_id, str) or not _TRANSACTION_ID.fullmatch(transaction_id):
        raise ValueError("invalid journal transaction id")
    phase = data.get("phase")
    if phase not in _PHASES:
        raise ValueError("invalid journal phase")
    if not isinstance(data.get("created_at"), str) or not data["created_at"]:
        raise ValueError("journal creation time is required")
    if not isinstance(data.get("source_revision"), str) or not re.fullmatch(r"[0-9a-f]{40}", data["source_revision"]):
        raise ValueError("journal source revision must be a full git SHA")

    target = _mapping(data.get("target"), "target")
    backup = _mapping(data.get("backup"), "backup")
    home = _mapping(data.get("home"), "home")
    provider = _mapping(data.get("provider"), "provider")
    if not isinstance(target.get("generation_id"), str) or not target["generation_id"].startswith("g3-"):
        raise ValueError("journal target generation is invalid")
    if not isinstance(target.get("snapshot_id"), int) or target["snapshot_id"] <= 0:
        raise ValueError("journal target snapshot id is invalid")
    if not isinstance(backup.get("snapshot_id"), int) or backup["snapshot_id"] <= 0:
        raise ValueError("journal backup snapshot id is invalid")
    if target["snapshot_id"] == backup["snapshot_id"]:
        raise ValueError("target and backup snapshots must differ")
    for section, key in ((target, "snapshot_uuid"), (backup, "snapshot_uuid"), (home, "subvolume_uuid")):
        if not isinstance(section.get(key), str) or not section[key]:
            raise ValueError(f"journal {key} is required")
    for key in ("root_filesystem_uuid", "expected_kernel_sha256", "expected_initramfs_sha256"):
        if not isinstance(target.get(key), str) or not target[key]:
            raise ValueError(f"journal target {key} is required")
    if provider.get("command") != "/usr/bin/limine-snapper-restore":
        raise ValueError("journal provider command is not the certified V1 provider")
    if provider.get("package") != "limine-snapper-sync" or provider.get("version") != "1.31.0-1":
        raise ValueError("journal provider package is not the certified V1 provider")
    if not isinstance(data.get("updated_at"), str) or not data["updated_at"]:
        raise ValueError("journal update time is required")
    _validate_history(data)
    return data


def _utc_stamp(now: datetime | None = None) -> str:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return current.isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_history(data: Mapping[str, Any]) -> None:
    history = data.get("history")
    if not isinstance(history, list) or not history:
        raise ValueError("journal history is required")
    previous: str | None = None
    for index, event in enumerate(history):
        event = _mapping(event, f"history[{index}]")
        phase = event.get("phase")
        if phase not in _PHASES:
            raise ValueError("journal history contains invalid phase")
        if not isinstance(event.get("at"), str) or not event["at"]:
            raise ValueError("journal history timestamp is required")
        if previous is None:
            if phase != "prepared":
                raise ValueError("journal history must begin prepared")
        elif phase not in _TRANSITIONS.get(previous, set()):
            raise ValueError(f"illegal L3 journal transition: {previous} -> {phase}")
        previous = phase
    if previous != data.get("phase"):
        raise ValueError("journal phase does not match history tail")


def create_journal(
    *,
    transaction_id: str,
    source_revision: str,
    target: Mapping[str, Any],
    backup: Mapping[str, Any],
    home: Mapping[str, Any],
    provider: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    stamp = _utc_stamp(now)
    return validate_journal({
        "schema_version": SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "phase": "prepared",
        "created_at": stamp,
        "updated_at": stamp,
        "source_revision": source_revision,
        "target": dict(target),
        "backup": dict(backup),
        "home": dict(home),
        "provider": dict(provider),
        "history": [{"phase": "prepared", "at": stamp}],
    })


def transition_journal(
    payload: Mapping[str, Any],
    next_phase: str,
    *,
    details: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = validate_journal(payload)
    phase = current["phase"]
    if next_phase not in _TRANSITIONS.get(phase, set()):
        raise ValueError(f"illegal L3 journal transition: {phase} -> {next_phase}")
    stamp = _utc_stamp(now)
    updated = dict(current)
    history = [dict(item) for item in current["history"]]
    event: dict[str, Any] = {"phase": next_phase, "at": stamp}
    if details is not None:
        event["details"] = dict(details)
    history.append(event)
    updated["phase"] = next_phase
    updated["updated_at"] = stamp
    updated["history"] = history
    return validate_journal(updated)


def write_journal(path: str | os.PathLike[str], payload: Mapping[str, Any]) -> None:
    destination = Path(path)
    data = validate_journal(payload)
    if destination.stem != data["transaction_id"] or destination.suffix != ".json":
        raise ValueError("journal path does not match transaction id")
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temp = destination.parent / f".{destination.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(temp, flags, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        os.replace(temp, destination)
        _fsync_directory(destination.parent)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in {22, 95}:
                raise
    finally:
        os.close(fd)


def read_journal(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read L3 journal: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("L3 journal root must be an object")
    data = validate_journal(raw)
    if source.stem != data["transaction_id"] or source.suffix != ".json":
        raise ValueError("journal path does not match transaction id")
    return data
