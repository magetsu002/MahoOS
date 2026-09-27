#!/usr/bin/env python3
"""Deterministic, non-mutating storage planning for the MahoOS installer."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
import uuid

GIB = 1024 ** 3
MIB = 1024 ** 2
MINIMUM_DISK_BYTES = 128 * GIB
ESP_SIZE_BYTES = 4 * GIB
MINIMUM_RESERVE_BYTES = 20 * GIB
RESERVE_PERCENT_NUMERATOR = 15
RESERVE_PERCENT_DENOMINATOR = 100
LUKS2_OVERHEAD_BUDGET_BYTES = 32 * MIB
FILESYSTEM_METADATA_BUDGET_BYTES = 2 * GIB
GPT_ENTRY_COUNT = 128
GPT_ENTRY_SIZE_BYTES = 128
ALIGNMENT_BYTES = MIB
SUBVOLUMES = ("@", "@home", "@snapshots", "@var_log")

_SHA40 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DEVICE = re.compile(r"/dev/[A-Za-z0-9._/+:-]+")
_INSTALL_NAMESPACE = uuid.UUID("b74dfe24-06f3-5ce0-a93f-71e842d62687")


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
        found.update(value.strip() for value in values if isinstance(value, str) and value.strip())
    elif isinstance(values, str) and values.strip():
        found.add(values.strip())
    children = raw.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, Mapping):
                found.update(_mountpoints(child))
    return tuple(sorted(found))


def _has_children(raw: Mapping[str, Any]) -> bool:
    children = raw.get("children")
    return isinstance(children, list) and bool(children)


def normalize_disk(raw: Mapping[str, Any]) -> dict[str, Any]:
    path = _text(raw.get("path"))
    if _DEVICE.fullmatch(path) is None:
        raise ValueError("disk path is invalid")
    size = _integer(raw.get("size", raw.get("size_bytes")), "disk size")
    if size <= 0:
        raise ValueError("disk size is invalid")
    logical = _integer(raw.get("log-sec", raw.get("logical_sector_size", 0)), "logical sector size")
    physical = _integer(raw.get("phy-sec", raw.get("physical_sector_size", 0)), "physical sector size")
    if logical <= 0 or physical <= 0 or physical % logical or size % logical:
        raise ValueError("sector geometry is invalid")
    major_minor = _text(raw.get("maj:min", raw.get("major_minor")))
    if re.fullmatch(r"[0-9]+:[0-9]+", major_minor) is None:
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
        "backing_file": _text(raw.get("back-file", raw.get("backing_file"))),
        "logical_sector_size": logical,
        "physical_sector_size": physical,
        "major_minor": major_minor,
        "mountpoints": _mountpoints(raw),
        "partition_table_type": _text(raw.get("pttype", raw.get("partition_table_type"))),
        "filesystem_type": _text(raw.get("fstype", raw.get("filesystem_type"))),
        "has_children": _has_children(raw) if "children" in raw else bool(raw.get("has_children", False)),
    }


def _identity_material(disk: Mapping[str, Any]) -> dict[str, Any]:
    return {key: disk[key] for key in (
        "path", "size_bytes", "model", "serial", "wwn", "transport", "backing_file",
        "logical_sector_size", "physical_sector_size", "major_minor",
    )}


def disk_identity_sha256(disk: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(_identity_material(disk))).hexdigest()


def same_disk_identity(expected: Mapping[str, Any], observed: Mapping[str, Any]) -> bool:
    return _identity_material(expected) == _identity_material(normalize_disk(observed))


def runtime_source_revision(root: Path) -> str:
    path = root / "share/maho/runtime-source-revision"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        release_path = root / "share/maho/release.json"
        try:
            release = json.loads(release_path.read_text(encoding="utf-8"))
            value = _text(release.get("source_revision")) if isinstance(release, Mapping) else ""
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("installer source revision is unavailable") from exc
    if _SHA40.fullmatch(value) is None:
        raise ValueError("installer source revision is invalid")
    return value


def partition_path(device: str, number: int) -> str:
    if number not in {1, 2} or _DEVICE.fullmatch(device) is None:
        raise ValueError("partition identity is invalid")
    separator = "p" if device[-1].isdigit() else ""
    return f"{device}{separator}{number}"


def _align_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def _uuid(seed: str, label: str) -> str:
    return str(uuid.uuid5(_INSTALL_NAMESPACE, f"{seed}:{label}"))


def _geometry(disk: Mapping[str, Any]) -> dict[str, Any]:
    logical = disk["logical_sector_size"]
    total = disk["size_bytes"] // logical
    table_sectors = math.ceil(GPT_ENTRY_COUNT * GPT_ENTRY_SIZE_BYTES / logical)
    first_usable = 2 + table_sectors
    last_usable = total - table_sectors - 2
    alignment_sectors = math.lcm(ALIGNMENT_BYTES, disk["physical_sector_size"]) // logical
    esp_sectors = ESP_SIZE_BYTES // logical
    esp_first = _align_up(first_usable, alignment_sectors)
    esp_last = esp_first + esp_sectors - 1
    luks_first = esp_last + 1
    if luks_first > last_usable:
        raise ValueError("disk is too small for the storage geometry")
    return {
        "logical_sector_size_bytes": logical,
        "physical_sector_size_bytes": disk["physical_sector_size"],
        "total_sectors": total,
        "alignment_sectors": alignment_sectors,
        "gpt": {
            "entry_count": GPT_ENTRY_COUNT,
            "entry_size_bytes": GPT_ENTRY_SIZE_BYTES,
            "partition_array_sectors": table_sectors,
            "primary_header_lba": 1,
            "primary_entries_first_lba": 2,
            "backup_entries_first_lba": total - table_sectors - 1,
            "backup_header_lba": total - 1,
            "first_usable_lba": first_usable,
            "last_usable_lba": last_usable,
        },
        "esp_first_lba": esp_first,
        "esp_last_lba": esp_last,
        "esp_sector_count": esp_sectors,
        "luks_first_lba": luks_first,
        "luks_last_lba": last_usable,
        "luks_sector_count": last_usable - luks_first + 1,
    }


def _plan_material(plan: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "schema_version", "kind", "source_revision", "target", "geometry", "layout_contract",
        "installation_identity", "encryption_contract", "space_policy", "execution_scope", "blockers",
    )
    return {key: plan[key] for key in keys}


def destructive_confirmation(plan_sha256: str) -> str:
    if _SHA256.fullmatch(plan_sha256) is None:
        raise ValueError("install plan digest is invalid")
    return f"ERASE-MAHO:{plan_sha256}"


def build_install_plan(raw_disk: Mapping[str, Any], *, source_revision: str) -> dict[str, Any]:
    if _SHA40.fullmatch(source_revision) is None:
        raise ValueError("installer source revision is invalid")
    disk = normalize_disk(raw_disk)
    geometry = _geometry(disk)
    blockers: list[str] = []
    if disk["type"] != "disk":
        blockers.append("target_not_whole_disk")
    if disk["read_only"]:
        blockers.append("target_read_only")
    if disk["removable"]:
        blockers.append("target_removable")
    if disk["mountpoints"]:
        blockers.append("target_or_child_mounted")
    if not disk["serial"] and not disk["wwn"] and not disk["backing_file"]:
        blockers.append("target_identity_not_stable")
    if disk["partition_table_type"] or disk["filesystem_type"] or disk["has_children"]:
        blockers.append("target_not_blank")
    if disk["size_bytes"] < MINIMUM_DISK_BYTES:
        blockers.append("target_below_128_gib_minimum")
    if disk["logical_sector_size"] not in {512, 4096}:
        blockers.append("target_sector_size_unsupported")

    identity = disk_identity_sha256(disk)
    target = dict(disk) | {"identity_sha256": identity}
    seed_material = {
        "source_revision": source_revision,
        "target_identity_sha256": identity,
        "geometry": geometry,
        "contract": "maho-v1-storage",
    }
    seed = hashlib.sha256(_canonical(seed_material)).hexdigest()
    installation_id = _uuid(seed, "installation")
    identifiers = {
        "installation_uuid": installation_id,
        "gpt_disk_guid": _uuid(seed, "gpt-disk"),
        "esp_partition_uuid": _uuid(seed, "esp-partition"),
        "luks_partition_uuid": _uuid(seed, "luks-partition"),
        "luks_uuid": _uuid(seed, "luks2"),
        "btrfs_uuid": _uuid(seed, "btrfs"),
        "fat_volume_id": hashlib.sha256(f"{seed}:fat".encode()).hexdigest()[:8].upper(),
    }
    usable_filesystem = max(
        0,
        geometry["luks_sector_count"] * disk["logical_sector_size"] - LUKS2_OVERHEAD_BUDGET_BYTES,
    )
    reserve_required = max(
        MINIMUM_RESERVE_BYTES,
        math.ceil(usable_filesystem * RESERVE_PERCENT_NUMERATOR / RESERVE_PERCENT_DENOMINATOR),
    )
    maximum_staging = max(0, usable_filesystem - reserve_required - FILESYSTEM_METADATA_BUDGET_BYTES)
    space_policy = {
        "minimum_disk_bytes": MINIMUM_DISK_BYTES,
        "usable_filesystem_floor_bytes": usable_filesystem,
        "luks2_overhead_budget_bytes": LUKS2_OVERHEAD_BUDGET_BYTES,
        "filesystem_metadata_budget_bytes": FILESYSTEM_METADATA_BUDGET_BYTES,
        "reserve_formula": "max(20 GiB, 15% of usable filesystem space)",
        "reserve_required_bytes": reserve_required,
        "worst_case_staging_limit_bytes": maximum_staging,
        "reserve_after_worst_case_staging_bytes": usable_filesystem - FILESYSTEM_METADATA_BUDGET_BYTES - maximum_staging,
        "reserve_valid": usable_filesystem - FILESYSTEM_METADATA_BUDGET_BYTES - maximum_staging >= reserve_required,
    }
    layout = {
        "firmware": "uefi",
        "partition_table": "gpt",
        "swap": "zram-only",
        "hibernation": False,
        "partitions": [
            {
                "number": 1,
                "path": partition_path(disk["path"], 1),
                "name": "Maho ESP",
                "type_guid": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",
                "partition_uuid": identifiers["esp_partition_uuid"],
                "first_lba": geometry["esp_first_lba"],
                "last_lba": geometry["esp_last_lba"],
                "sector_count": geometry["esp_sector_count"],
                "size_bytes": ESP_SIZE_BYTES,
                "filesystem": "fat32",
                "filesystem_label": "MAHO_ESP",
                "mountpoint": "/boot",
            },
            {
                "number": 2,
                "path": partition_path(disk["path"], 2),
                "name": "Maho Crypt",
                "type_guid": "ca7d7ccb-63ed-4c53-861c-1742536059cc",
                "partition_uuid": identifiers["luks_partition_uuid"],
                "first_lba": geometry["luks_first_lba"],
                "last_lba": geometry["luks_last_lba"],
                "sector_count": geometry["luks_sector_count"],
                "size_bytes": geometry["luks_sector_count"] * disk["logical_sector_size"],
                "container": "luks2",
                "filesystem_inside": "btrfs",
            },
        ],
        "btrfs": {
            "label": "MAHO_ROOT",
            "uuid": identifiers["btrfs_uuid"],
            "subvolumes": list(SUBVOLUMES),
            "mounts": {
                "@": "/",
                "@home": "/home",
                "@snapshots": "/.snapshots",
                "@var_log": "/var/log",
            },
        },
    }
    material = {
        "schema_version": 2,
        "kind": "maho-installer-storage-plan",
        "source_revision": source_revision,
        "target": target,
        "geometry": geometry,
        "layout_contract": layout,
        "installation_identity": identifiers,
        "encryption_contract": {
            "format": "luks2",
            "cipher": "aes-xts-plain64",
            "key_size_bits": 512,
            "pbkdf": "argon2id",
            "sector_size_bytes": disk["logical_sector_size"],
            "mapper_name": f"maho-{installation_id[:8]}",
            "key_delivery": "root-readable-file-mode-0600",
        },
        "space_policy": space_policy,
        "execution_scope": "disposable-test-media-only",
        "blockers": blockers,
    }
    plan_sha256 = hashlib.sha256(_canonical(material)).hexdigest()
    ready = not blockers and space_policy["reserve_valid"]
    return material | {
        "plan_sha256": plan_sha256,
        "plan_id": f"install-plan-{plan_sha256}",
        "ready_for_destructive_confirmation": ready,
        "destructive_confirmation": destructive_confirmation(plan_sha256) if ready else None,
        "execution_authority": "root-or-policykit-required",
        "mutation_performed": False,
    }


def validate_plan_integrity(plan: Mapping[str, Any]) -> dict[str, Any]:
    try:
        digest = hashlib.sha256(_canonical(_plan_material(plan))).hexdigest()
    except (KeyError, TypeError) as exc:
        raise ValueError("install plan is incomplete") from exc
    if plan.get("schema_version") != 2 or plan.get("kind") != "maho-installer-storage-plan":
        raise ValueError("install plan schema is unsupported")
    if plan.get("plan_sha256") != digest or plan.get("plan_id") != f"install-plan-{digest}":
        raise ValueError("install plan digest does not match its contents")
    ready = not plan.get("blockers") and plan.get("space_policy", {}).get("reserve_valid") is True
    expected_confirmation = destructive_confirmation(digest) if ready else None
    if plan.get("ready_for_destructive_confirmation") is not ready:
        raise ValueError("install plan readiness is inconsistent")
    if plan.get("destructive_confirmation") != expected_confirmation:
        raise ValueError("install plan confirmation is inconsistent")
    return dict(plan)


def validate_destructive_confirmation(
    plan: Mapping[str, Any], current_disk: Mapping[str, Any], *,
    source_revision: str, confirmation: str,
) -> dict[str, Any]:
    validated = validate_plan_integrity(plan)
    rebuilt = build_install_plan(current_disk, source_revision=source_revision)
    if rebuilt["plan_id"] != validated["plan_id"]:
        raise ValueError("install plan identity drifted")
    if confirmation != rebuilt["destructive_confirmation"]:
        raise ValueError("destructive confirmation does not match the exact install plan")
    if not rebuilt["ready_for_destructive_confirmation"]:
        raise ValueError("install plan is blocked")
    return {
        "schema_version": 1,
        "plan_id": rebuilt["plan_id"],
        "target_identity_sha256": rebuilt["target"]["identity_sha256"],
        "source_revision": source_revision,
        "confirmation_valid": True,
        "execution_authority": "root-or-policykit-required",
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
        "-o", "PATH,TYPE,SIZE,RO,RM,MODEL,SERIAL,WWN,TRAN,LOG-SEC,PHY-SEC,MAJ:MIN,MOUNTPOINTS,PTTYPE,FSTYPE",
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
    observed = dict(disk_from_lsblk_payload(payload, expected_path=device))
    if device.startswith("/dev/loop"):
        backing_path = Path("/sys/class/block") / Path(device).name / "loop/backing_file"
        try:
            observed["back-file"] = backing_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError("loop target backing identity is unavailable") from exc
    return observed
