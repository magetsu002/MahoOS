#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_update_preparation import PreparationEvidence, prepare_transaction  # noqa: E402
from maho_update_state import UpdateState, create_transaction, transition_transaction  # noqa: E402

NOW = datetime(2026, 9, 12, 4, 0, tzinfo=timezone.utc)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def rejected(name: str, function) -> None:
    try:
        function()
    except ValueError:
        check(name, True)
        return
    check(name, False)


def staged(cache: Path) -> tuple[dict, dict]:
    package = cache / "maho-os-2-any.pkg.tar.zst"
    package.write_bytes(b"payload")
    transaction = create_transaction(
        transaction_id="upd-20260912T040000Z-abcdef123456", source_revision="d" * 40,
        packages=[{"name": "maho-os", "installed_version": "1", "candidate_version": "2", "repository": "maho", "download_size": 7, "installed_size": 7, "roles": ["maho-runtime"]}],
        activation_requirements=["maho-runtime-release"], recovery_generation_id=None, now=NOW,
    )
    transaction = transition_transaction(transaction, UpdateState.STAGED, now=NOW)
    manifest = {
        "schema_version": 1,
        "transaction_id": transaction["transaction_id"],
        "package_generation_id": transaction["package_generation"]["id"],
        "payloads": [{
            "name": "maho-os", "version": "2", "path": str(package),
            "sha256": hashlib.sha256(b"payload").hexdigest(), "size": 7,
            "signature_status": "verified-by-pacman",
        }],
        "verification": "pacman-signature-policy-and-sha256",
    }
    return transaction, manifest


def evidence(**changes) -> PreparationEvidence:
    values = {
        "discovery_generation_current": True,
        "coherent_full_upgrade": True,
        "required_disk_bytes": 100,
        "available_disk_bytes": 1000,
        "power_status_known": True,
        "power_policy_satisfied": True,
        "concurrent_package_or_build_operation": False,
        "maho_runtime_relationship_known": True,
        "primary_kernel_relationship_known": True,
        "fallback_kernel_relationship_known": True,
        "headers_relationship_known": True,
        "nvidia_dkms_relationship_known": True,
        "boot_initramfs_relationship_known": True,
        "recovery_protection_available": True,
        "recovery_generation_id": "g3-1234567890abcdef12345678",
        "native_l3_certified": False,
        "execution_environment": "production",
    }
    values.update(changes)
    return PreparationEvidence(**values)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-update-preparation-") as temporary:
        cache = Path(temporary)
        transaction, manifest = staged(cache)
        production = prepare_transaction(transaction, manifest, cache, evidence(), now=NOW)
        check("M4A production preparation fails closed on deferred M3B", production.transaction["state"] == "BLOCKED" and "native_l3_certification_required" in production.plan.blockers)
        check("production plan records PREPARED before the native gate", [item["state"] for item in production.transaction["history"]][-2:] == ["PREPARED", "BLOCKED"])
        check("blocked production plan still binds exact generation and activation", production.plan.package_generation_id == transaction["package_generation"]["id"] and production.plan.activation_requirements == ("maho-runtime-release",))

        fixture = prepare_transaction(transaction, manifest, cache, evidence(execution_environment="fixture"), now=NOW)
        check("isolated fixture plan can prove PREPARED architecture", fixture.transaction["state"] == "PREPARED" and fixture.plan.complete)
        check("preparation binds the exact recovery generation", fixture.transaction["recovery"]["generation_id"] == "g3-1234567890abcdef12345678")
        check("fixture authority never forges native L3 certification", fixture.transaction["recovery"]["native_l3_certified"] is False)

        for label, changes, blocker in (
            ("stale transaction", {"discovery_generation_current": False}, "stale_update_transaction"),
            ("partial upgrade", {"coherent_full_upgrade": False}, "partial_upgrade_or_incoherent_package_set"),
            ("low disk", {"available_disk_bytes": 1}, "insufficient_install_space"),
            ("unknown power", {"power_status_known": False}, "power_status_unknown"),
            ("low battery", {"power_policy_satisfied": False}, "power_policy_unsatisfied"),
            ("concurrent package transaction", {"concurrent_package_or_build_operation": True}, "concurrent_package_or_build_operation"),
            ("Maho runtime unknown", {"maho_runtime_relationship_known": False}, "maho_runtime_relationship_unknown"),
            ("Primary kernel unknown", {"primary_kernel_relationship_known": False}, "primary_kernel_relationship_unknown"),
            ("Fallback kernel unknown", {"fallback_kernel_relationship_known": False}, "fallback_kernel_relationship_unknown"),
            ("headers unknown", {"headers_relationship_known": False}, "headers_relationship_unknown"),
            ("NVIDIA DKMS unknown", {"nvidia_dkms_relationship_known": False}, "nvidia_dkms_relationship_unknown"),
            ("boot implications unknown", {"boot_initramfs_relationship_known": False}, "boot_initramfs_relationship_unknown"),
            ("recovery unavailable", {"recovery_protection_available": False}, "recovery_protection_unavailable"),
            ("recovery unbound", {"recovery_generation_id": None}, "recovery_generation_unbound"),
        ):
            result = prepare_transaction(transaction, manifest, cache, evidence(execution_environment="fixture", **changes), now=NOW)
            check(f"{label} blocks before installation", result.transaction["state"] == "BLOCKED" and blocker in result.plan.blockers)

        forged = evidence(execution_environment="fixture", native_l3_certified=True)
        rejected("planner rejects forged native certification", lambda: prepare_transaction(transaction, manifest, cache, forged, now=NOW))
        malformed = dict(manifest)
        malformed["package_generation_id"] = "pkg-" + "0" * 64
        rejected("planner rejects stale staging generation", lambda: prepare_transaction(transaction, malformed, cache, evidence(execution_environment="fixture"), now=NOW))

    print("ALL MAHO UPDATE PREPARATION CONTRACTS PASS")


if __name__ == "__main__":
    main()
