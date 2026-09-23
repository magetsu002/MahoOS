#!/usr/bin/env python3
"""Read-only blank-disk planning authority for the MahoOS installer.

This module deliberately has no mutation operations.  It binds one exact disk
observation to a deterministic install plan and explicit destructive
confirmation token so later installer stages cannot silently retarget a disk.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

_SHA40 = re.compile(r"[0-9a-f]{40}")
_DEVICE = re.compile(r"/dev/[A-Za-z0-9._/+:-]+")
INSTALLER_STAGES = (
    "partition-table",
    "filesystems",
    "base-system",
    "repositories",
    "primary-fallback-kernels",
    "limine",
    "guardian-recovery",
    "generation-authorities",
    "maho-runtime",
    "system-services",
    "user-sddm",
    "first-boot-guardian-verification",
)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} is invalid")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if parsed < 0:
        raise ValueError(f"{field} is invalid")
    return parsed


def _boolean(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"0", "1", "true", "false", "yes", "no"}:
        return value.strip().lower() in {"1", "true", "yes"}
    raise ValueError(f"{field} is invalid")


def _mountpoints(raw: Mapping[str, Any]) -> tuple[str, ...]:
    found: set[str] = set()
    values = raw.get("mountpoints")
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value.strip():
                found.add(value.strip())
    elif isinstance(values, str) and values.strip():
        found.add(values.strip())
    children = raw.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, Mapping):
                found.update(_mountpoints(child))
    return tuple(sorted(found))


def normalize_disk(raw: Mapping[str, Any]) -> dict[str, Any]:
    path = _text(raw.get("path"))
    if _DEVICE.fullmatch(path) is None:
        raise ValueError("disk path is invalid")
    size = _integer(raw.get("size"), "disk size")
    if size <= 0:
        raise ValueError("disk size is invalid")
    logical = _integer(raw.get("log-sec", raw.get("logical_sector_size", 0)), "logical sector size")
    physical = _integer(raw.get("phy-sec", raw.get("physical_sector_size", 0)), "physical sector size")
    if logical <= 0 or physical <= 0:
        raise ValueError("sector size is invalid")
    major_minor = _text(raw.get("maj:min", raw.get("major_minor")))
    if not major_minor or ":" not in major_minor:
        raise ValueError("major:minor identity is invalid")
    return {
        "path": path,
        "type": _text(raw.get("type")),
        "size_bytes": size,
        "read_only": _boolean(raw.get("ro", raw.get("read_only", False)), "read-only flag"),
        "removable": _boolean(raw.get("rm", raw.get("removable", False)), "removable flag"),
        "model": _text(raw.get("model")),
        "serial": _text(raw.get("serial")),
        "wwn": _text(raw.get("wwn")),
        "transport": _text(raw.get("tran", raw.get("transport"))),
        "logical_sector_size": logical,
        "physical_sector_size": physical,
        "major_minor": major_minor,
        "mountpoints": _mountpoints(raw),
    }


def _identity_material(disk: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": disk["path"],
        "size_bytes": disk["size_bytes"],
        "model": disk["model"],
        "serial": disk["serial"],
        "wwn": disk["wwn"],
        "transport": disk["transport"],
        "logical_sector_size": disk["logical_sector_size"],
        "physical_sector_size": disk["physical_sector_size"],
        "major_minor": disk["major_minor"],
    }


def disk_identity_sha256(disk: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(_identity_material(disk))).hexdigest()


def runtime_source_revision(root: Path) -> str:
    path = root / "share/maho/runtime-source-revision"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("installer source revision is unavailable") from exc
    if _SHA40.fullmatch(value) is None:
        raise ValueError("installer source revision is invalid")
    return value


def destructive_confirmation(plan_id: str) -> str:
    match = re.fullmatch(r"install-plan-([0-9a-f]{64})", plan_id)
    if match is None:
        raise ValueError("install plan identity is invalid")
    return f"ERASE-MAHO:{match.group(1)}"


def build_install_plan(raw_disk: Mapping[str, Any], *, source_revision: str) -> dict[str, Any]:
    if _SHA40.fullmatch(source_revision) is None:
        raise ValueError("installer source revision is invalid")
    disk = normalize_disk(raw_disk)
    blockers: list[str] = []
    if disk["type"] != "disk":
        blockers.append("target_not_whole_disk")
    if disk["read_only"]:
        blockers.append("target_read_only")
    if disk["mountpoints"]:
        blockers.append("target_or_child_mounted")
    if not disk["serial"] and not disk["wwn"]:
        blockers.append("target_identity_not_stable")

    identity = disk_identity_sha256(disk)
    ready = not blockers
    layout = {
        "partition_table": "gpt",
        "esp": {
            "filesystem": "vfat",
            "mountpoint": "/boot",
            "size_policy": "resolved-at-execution-before-mutation",
        },
        "root": {
            "filesystem": "btrfs",
            "mountpoint": "/",
            "size_policy": "remaining-space",
            "subvolumes": ["@", "@home", "@snapshots", "@var_log"],
        },
    }
    material = {
        "schema_version": 1,
        "kind": "maho-installer-plan",
        "source_revision": source_revision,
        "target": dict(disk) | {"identity_sha256": identity},
        "layout_contract": layout,
        "stages": list(INSTALLER_STAGES),
        "blockers": blockers,
    }
    plan_id = "install-plan-" + hashlib.sha256(_canonical(material)).hexdigest()
    return material | {
        "plan_id": plan_id,
        "ready_for_destructive_confirmation": ready,
        "destructive_confirmation": destructive_confirmation(plan_id) if ready else None,
        "execution_authority": "none",
        "mutation_performed": False,
    }


def validate_destructive_confirmation(
    plan: Mapping[str, Any], current_disk: Mapping[str, Any], *,
    source_revision: str, confirmation: str,
) -> dict[str, Any]:
    rebuilt = build_install_plan(current_disk, source_revision=source_revision)
    expected_plan = _text(plan.get("plan_id"))
    if not expected_plan or rebuilt["plan_id"] != expected_plan:
        raise ValueError("install plan identity drifted")
    expected_confirmation = rebuilt.get("destructive_confirmation")
    if expected_confirmation is None or confirmation != expected_confirmation:
        raise ValueError("destructive confirmation does not match the exact install plan")
    if not rebuilt["ready_for_destructive_confirmation"]:
        raise ValueError("install plan is blocked")
    return {
        "schema_version": 1,
        "plan_id": rebuilt["plan_id"],
        "target_identity_sha256": rebuilt["target"]["identity_sha256"],
        "source_revision": source_revision,
        "confirmation_valid": True,
        "execution_authority": "none",
        "mutation_performed": False,
    }


def disk_from_lsblk_payload(payload: Mapping[str, Any], *, expected_path: str) -> Mapping[str, Any]:
    devices = payload.get("blockdevices")
    if not isinstance(devices, list) or len(devices) != 1 or not isinstance(devices[0], Mapping):
        raise ValueError("lsblk did not return exactly one target device")
    device = devices[0]
    if _text(device.get("path")) != expected_path:
        raise ValueError("lsblk target identity drifted")
    return device


def probe_disk(device: str, *, run=subprocess.run) -> Mapping[str, Any]:
    if _DEVICE.fullmatch(device) is None:
        raise ValueError("disk path is invalid")
    command: Sequence[str] = (
        "lsblk", "-b", "-J",
        "-o", "PATH,TYPE,SIZE,RO,RM,MODEL,SERIAL,WWN,TRAN,LOG-SEC,PHY-SEC,MAJ:MIN,MOUNTPOINTS",
        device,
    )
    result = run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"lsblk failed for exact target: {result.stderr.strip() or result.returncode}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("lsblk returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("lsblk returned invalid payload")
    return disk_from_lsblk_payload(payload, expected_path=device)
