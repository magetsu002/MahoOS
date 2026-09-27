#!/usr/bin/env python3
"""Installation receipt and fail-closed first-boot certification contracts."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping

from maho_installer_payload import validate_payload_manifest
from maho_installer_plan import validate_plan_integrity


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} is missing")
    return value


def build_install_receipt(
    plan: Mapping[str, Any], payload: Mapping[str, Any], phase_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    plan_value = validate_plan_integrity(plan)
    payload_value = validate_payload_manifest(payload)
    required = {
        "IDENTITIES_CREATED", "USERS_CREATED", "RUNTIME_INSTALLED", "KERNELS_INSTALLED",
        "INITRAMFS_BUILT", "BOOT_GENERATION_PUBLISHED", "RECOVERY_INSTALLED",
        "SERVICES_INSTALLED", "SYSTEM_GENERATION_PUBLISHED",
    }
    if not isinstance(phase_evidence, Mapping) or not required.issubset(phase_evidence):
        raise ValueError("installer phase evidence is incomplete")
    identities = phase_evidence["IDENTITIES_CREATED"]
    user = phase_evidence["USERS_CREATED"]
    runtime = phase_evidence["RUNTIME_INSTALLED"]
    kernels = phase_evidence["KERNELS_INSTALLED"]
    initramfs = phase_evidence["INITRAMFS_BUILT"]
    boot = phase_evidence["BOOT_GENERATION_PUBLISHED"]
    recovery = phase_evidence["RECOVERY_INSTALLED"]
    services = phase_evidence["SERVICES_INSTALLED"]
    generations = phase_evidence["SYSTEM_GENERATION_PUBLISHED"]
    for name, value in (
        ("identities", identities), ("user", user), ("runtime", runtime),
        ("kernels", kernels), ("initramfs", initramfs), ("boot", boot),
        ("recovery", recovery), ("services", services), ("generations", generations),
    ):
        if not isinstance(value, Mapping):
            raise ValueError(f"{name} phase evidence is invalid")
    material = {
        "schema_version": 1,
        "kind": "maho-installation-receipt",
        "state": "PENDING_FIRST_BOOT",
        "install_attempt_id": plan_value["install_attempt_id"],
        "installation_uuid": plan_value["installation_identity"]["installation_uuid"],
        "plan_id": plan_value["plan_id"],
        "source_revision": plan_value["source_revision"],
        "payload_sha256": payload_value["payload_sha256"],
        "package_version": payload_value["package_version"],
        "storage": {
            "target_identity_sha256": plan_value["target"]["identity_sha256"],
            "gpt_disk_guid": plan_value["installation_identity"]["gpt_disk_guid"],
            "esp_partition_uuid": plan_value["installation_identity"]["esp_partition_uuid"],
            "luks_partition_uuid": plan_value["installation_identity"]["luks_partition_uuid"],
            "luks_uuid": plan_value["installation_identity"]["luks_uuid"],
            "btrfs_uuid": plan_value["installation_identity"]["btrfs_uuid"],
            "root_fsroot": "/@",
            "home_fsroot": "/@home",
            "root_subvolume_uuid": _require_text(identities.get("root_subvolume_uuid"), "root subvolume UUID"),
            "home_subvolume_uuid": _require_text(identities.get("home_subvolume_uuid"), "home subvolume UUID"),
            "mapper_name": plan_value["encryption_contract"]["mapper_name"],
        },
        "machine_id": _require_text(identities.get("machine_id"), "machine identity"),
        "user": dict(user),
        "runtime": dict(runtime),
        "package_generation_id": payload_value["package_generation_id"],
        "kernel_generation_id": _require_text(generations.get("kernel_generation_id"), "KernelGeneration"),
        "system_generation_id": _require_text(generations.get("system_generation_id"), "SystemGeneration"),
        "boot_generation_id": _require_text(boot.get("boot_generation_id"), "BootGeneration"),
        "recovery_identity": _require_text(recovery.get("recovery_identity"), "recovery identity"),
        "kernel": dict(kernels),
        "initramfs": dict(initramfs),
        "boot": dict(boot),
        "recovery": dict(recovery),
        "services": dict(services),
    }
    receipt_id = "install-receipt-" + hashlib.sha256(_canonical(material)).hexdigest()
    return validate_install_receipt(material | {"receipt_id": receipt_id})


def validate_install_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version", "kind", "state", "install_attempt_id", "installation_uuid",
        "plan_id", "source_revision", "payload_sha256", "package_version", "storage",
        "machine_id", "user", "runtime", "package_generation_id", "kernel_generation_id",
        "system_generation_id", "boot_generation_id", "recovery_identity", "kernel",
        "initramfs", "boot", "recovery", "services", "receipt_id",
    }
    if not isinstance(receipt, Mapping) or set(receipt) != fields:
        raise ValueError("installation receipt fields are invalid")
    if receipt.get("schema_version") != 1 or receipt.get("kind") != "maho-installation-receipt":
        raise ValueError("installation receipt schema is unsupported")
    if receipt.get("state") != "PENDING_FIRST_BOOT":
        raise ValueError("installation receipt is not pending first boot")
    for name in ("payload_sha256",):
        if _SHA256.fullmatch(str(receipt.get(name, ""))) is None:
            raise ValueError(f"installation receipt {name} is invalid")
    for name, prefix in (
        ("plan_id", "install-plan-"), ("package_generation_id", "pkg-"),
        ("kernel_generation_id", "kgen-"), ("system_generation_id", "gen-"),
        ("boot_generation_id", "bootgen-"), ("receipt_id", "install-receipt-"),
    ):
        value = str(receipt.get(name, ""))
        if not value.startswith(prefix) or _SHA256.fullmatch(value.removeprefix(prefix)) is None:
            raise ValueError(f"installation receipt {name} is invalid")
    material = dict(receipt)
    claimed = material.pop("receipt_id")
    expected = "install-receipt-" + hashlib.sha256(_canonical(material)).hexdigest()
    if claimed != expected:
        raise ValueError("installation receipt identity does not match its contents")
    forbidden = {"password", "passphrase", "secret", "private_key", "recovery_key"}
    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            if any(str(key).lower() in forbidden for key in value):
                raise ValueError("installation receipt contains a plaintext-secret field")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(receipt)
    return dict(receipt)


def certify_first_boot(
    receipt: Mapping[str, Any], observation: Mapping[str, Any], *, verified_at: str | None = None,
) -> dict[str, Any]:
    expected = validate_install_receipt(receipt)
    if not isinstance(observation, Mapping):
        raise ValueError("first-boot observation is invalid")
    blockers: list[str] = []
    storage = observation.get("storage")
    if not isinstance(storage, Mapping):
        blockers.append("storage_observation_missing")
    else:
        for key in (
            "btrfs_uuid", "root_fsroot", "root_subvolume_uuid",
            "home_subvolume_uuid", "luks_uuid", "mapper_name",
        ):
            if storage.get(key) != expected["storage"].get(key):
                blockers.append(f"storage_{key}_mismatch")
        if storage.get("installation_uuid") != expected["installation_uuid"]:
            blockers.append("installation_uuid_mismatch")
    if observation.get("machine_id") != expected["machine_id"]:
        blockers.append("machine_id_mismatch")
    generations = observation.get("generations")
    if not isinstance(generations, Mapping):
        blockers.append("generation_observation_missing")
    else:
        for key in ("system_generation_id", "package_generation_id", "kernel_generation_id", "boot_generation_id"):
            if generations.get(key) != expected[key]:
                blockers.append(f"{key}_mismatch")
    runtime = observation.get("runtime")
    if not isinstance(runtime, Mapping):
        blockers.append("runtime_observation_missing")
    else:
        for key in ("source_revision", "content_sha256", "deployment_class", "trust_eligible"):
            if runtime.get(key) != expected["runtime"].get(key):
                blockers.append(f"runtime_{key}_mismatch")
        if runtime.get("verified") is not True:
            blockers.append("runtime_not_verified")
    boot = observation.get("boot")
    if not isinstance(boot, Mapping):
        blockers.append("boot_observation_missing")
    else:
        if boot.get("running_kernel") != expected["kernel"].get("primary_release"):
            blockers.append("running_kernel_mismatch")
        if boot.get("boot_sha256") != expected["boot"].get("boot_sha256"):
            blockers.append("boot_artifact_mismatch")
        if boot.get("fallback_artifacts_present") is not True:
            blockers.append("fallback_artifacts_missing")
    guardian = observation.get("guardian")
    if not isinstance(guardian, Mapping) or guardian.get("service_active") is not True:
        blockers.append("guardian_not_active")
    elif guardian.get("required_evidence_fresh") is not True:
        blockers.append("guardian_required_evidence_stale_or_missing")
    recovery = observation.get("recovery")
    if not isinstance(recovery, Mapping) or recovery.get("recovery_identity") != expected["recovery_identity"]:
        blockers.append("recovery_identity_mismatch")
    elif recovery.get("artifacts_present") is not True:
        blockers.append("recovery_artifacts_missing")
    user = observation.get("user")
    if not isinstance(user, Mapping):
        blockers.append("user_observation_missing")
    else:
        for key in ("name", "uid", "wheel", "root_locked", "home_fsroot"):
            if user.get(key) != expected["user"].get(key):
                blockers.append(f"user_{key}_mismatch")
    services = observation.get("services")
    if not isinstance(services, Mapping):
        blockers.append("service_observation_missing")
    else:
        for key in (
            "networkmanager_enabled", "networkmanager_active", "sddm_enabled",
            "session_installed", "coordinator_installed", "coordinator_timer_enabled",
            "firewall_enabled", "guardian_user_service_enabled",
        ):
            if services.get(key) is not True:
                blockers.append(f"service_{key}_missing")
        if services.get("production_prevention_enabled") is not False:
            blockers.append("production_prevention_must_remain_inactive")
    firewall = observation.get("firewall")
    if not isinstance(firewall, Mapping) or firewall.get("receipt_valid") is not True or firewall.get("table_present") is not True:
        blockers.append("firewall_not_verified")
    elif firewall.get("provider_global_authority") is not False:
        blockers.append("firewall_authority_scope_invalid")
    failed_units = observation.get("failed_units")
    if not isinstance(failed_units, list) or failed_units:
        blockers.append("systemd_failed_units_present")
    boot_id = observation.get("boot_id")
    if not isinstance(boot_id, str) or not boot_id:
        blockers.append("boot_id_missing")
    if blockers:
        return {
            "schema_version": 1,
            "kind": "maho-installation-first-boot-result",
            "state": "ATTENTION_REQUIRED",
            "installation_receipt_id": expected["receipt_id"],
            "blockers": sorted(set(blockers)),
            "healthy_receipt": None,
        }
    material = {
        "schema_version": 1,
        "kind": "maho-installation-health-receipt",
        "state": "INSTALLATION_HEALTHY",
        "verified_at": verified_at or _utc_now(),
        "boot_id": boot_id,
        "installation_receipt_id": expected["receipt_id"],
        "install_attempt_id": expected["install_attempt_id"],
        "installation_uuid": expected["installation_uuid"],
        "system_generation_id": expected["system_generation_id"],
        "package_generation_id": expected["package_generation_id"],
        "kernel_generation_id": expected["kernel_generation_id"],
        "boot_generation_id": expected["boot_generation_id"],
        "runtime_content_sha256": expected["runtime"]["content_sha256"],
        "guardian_trust_state": guardian.get("trust_state", "UNKNOWN"),
    }
    health_id = "install-health-" + hashlib.sha256(_canonical(material)).hexdigest()
    return {
        "schema_version": 1,
        "kind": "maho-installation-first-boot-result",
        "state": "INSTALLATION_HEALTHY",
        "installation_receipt_id": expected["receipt_id"],
        "blockers": [],
        "healthy_receipt": material | {"health_receipt_id": health_id},
    }
