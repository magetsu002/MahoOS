#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_update_state import UpdateState, create_transaction, transaction_path, transition_transaction  # noqa: E402
from maho_update_transaction import (  # noqa: E402
    ExecutionFailure,
    OfflineRootUpdateOps,
    build_execution_plan,
    execute_update,
    recover_interrupted_fixture,
    verify_fixture_activation,
)

NOW = datetime(2026, 9, 12, 6, 0, tzinfo=timezone.utc)


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


def ready(cache: Path) -> tuple[dict, dict]:
    payload = cache / "maho-os-2-any.pkg.tar.zst"
    payload.write_bytes(b"payload")
    transaction = create_transaction(
        transaction_id="upd-20260912T060000Z-123456abcdef", source_revision="f" * 40,
        packages=[{"name": "maho-os", "installed_version": "1", "candidate_version": "2", "repository": "maho", "download_size": 7, "installed_size": 7, "roles": ["maho-runtime"]}],
        activation_requirements=["maho-runtime-release", "restart"],
        recovery_generation_id="g3-1234567890abcdef12345678", now=NOW,
    )
    transaction = transition_transaction(transaction, UpdateState.STAGED, now=NOW)
    transaction = transition_transaction(transaction, UpdateState.PREPARED, now=NOW)
    transaction = transition_transaction(transaction, UpdateState.MAINTENANCE_READY, now=NOW)
    manifest = {
        "schema_version": 1, "transaction_id": transaction["transaction_id"],
        "package_generation_id": transaction["package_generation"]["id"],
        "payloads": [{"name": "maho-os", "version": "2", "path": str(payload), "sha256": hashlib.sha256(b"payload").hexdigest(), "size": 7, "signature_status": "verified-by-pacman"}],
        "verification": "pacman-signature-policy-and-sha256",
    }
    return transaction, manifest


def relationships(**changes) -> dict:
    values = {
        "maho_runtime": {"package": "maho-os", "version": "2", "immutable_release_required": True},
        "primary_kernel": {"package": "linux-cachyos", "version": "7.2"},
        "primary_headers": {"package": "linux-cachyos-headers", "version": "7.2"},
        "fallback_kernel": {"package": "linux-cachyos-lts", "version": "6.18"},
        "fallback_headers": {"package": "linux-cachyos-lts-headers", "version": "6.18"},
        "nvidia_dkms": {"status": "planned", "packages": ["nvidia-dkms"]},
        "boot_artifacts": [
            "/boot/vmlinuz-linux-cachyos", "/boot/initramfs-linux-cachyos.img",
            "/boot/vmlinuz-linux-cachyos-lts", "/boot/initramfs-linux-cachyos-lts.img",
        ],
    }
    values.update(changes)
    return values


class FakeOps:
    fixture_safe = True

    def __init__(self, fail: str | None = None, recover_ok: bool = True, failed_mutation: bool = False) -> None:
        self.fail = fail
        self.recover_ok = recover_ok
        self.failed_mutation = failed_mutation
        self.calls: list[str] = []

    def _call(self, name: str):
        self.calls.append(name)
        if self.fail == name:
            raise ExecutionFailure(name, f"fixture failure: {name}", mutation_started=self.failed_mutation)
        return {"ok": True, "stage": name}

    def prepare_recovery(self, plan): return self._call("recovery-preparation")
    def install_full_upgrade(self, plan): return self._call("full-package-upgrade")
    def verify_maho_runtime(self, plan): return self._call("maho-runtime")
    def verify_kernel_matrix(self, plan): return self._call("kernel-header-dkms")
    def build_initramfs(self, plan, preset): return self._call(f"initramfs:{preset}")
    def verify_boot_artifacts(self, plan): return self._call("boot-artifacts")
    def finalize_install(self, plan): return self._call("install-finalization")
    def verify_activation(self, plan): return self._call("activation-verification")
    def recover(self, plan, failed_stage):
        self.calls.append(f"recover:{failed_stage}")
        return {"ok": self.recover_ok, "recovery_generation": plan.recovery_generation_id}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-update-transaction-") as temporary:
        cache = Path(temporary)
        transaction, manifest = ready(cache)
        fixture_plan = build_execution_plan(transaction, manifest, cache, relationships(), execution_environment="fixture")
        check("plan coordinates immutable Maho runtime", fixture_plan.maho_runtime["immutable_release_required"] is True)
        check("plan coordinates Primary and Fallback initramfs", fixture_plan.initramfs_presets == ("linux-cachyos", "linux-cachyos-lts"))
        check("plan binds exact recovery generation", fixture_plan.recovery_generation_id == transaction["recovery"]["generation_id"])
        check("plan binds every staged payload", fixture_plan.payload_paths == (manifest["payloads"][0]["path"],))

        ops = FakeOps()
        journal = transaction_path(cache / "state", transaction["transaction_id"])
        installed = execute_update(transaction, fixture_plan, ops, journal_path=journal, now=NOW)
        check("fixture full transaction reaches installed pending activation", installed.transaction["state"] == "INSTALLED_PENDING_ACTIVATION")
        check("transaction runs recovery, package, runtime, kernel, both initramfs, boot, finalization", ops.calls == [
            "recovery-preparation", "full-package-upgrade", "maho-runtime", "kernel-header-dkms",
            "initramfs:linux-cachyos", "initramfs:linux-cachyos-lts", "boot-artifacts", "install-finalization",
        ])
        check("successful installation never reboots or mutates firmware", not installed.reboot_performed and not installed.firmware_mutated)
        healthy = verify_fixture_activation(installed.transaction, fixture_plan, ops, journal_path=journal, now=NOW)
        check("fixture post-activation proof reaches HEALTHY", healthy.transaction["state"] == "HEALTHY")

        production_plan = build_execution_plan(transaction, manifest, cache, relationships(), execution_environment="production")
        production_ops = FakeOps()
        blocked = execute_update(transaction, production_plan, production_ops, now=NOW)
        check("production mutation is gated until M3B and M4B", blocked.transaction["state"] == "BLOCKED" and "native_update_execution_uncertified" in blocked.transaction["blockers"])
        check("production gate blocks before any executor call", production_ops.calls == [] and not blocked.mutation_started)
        durable_gate = execute_update(transaction, production_plan, production_ops, native_l3_certified=True, native_update_execution_certified=True, now=NOW)
        check("M4A durable transaction still refuses forged caller gates", durable_gate.transaction["state"] == "BLOCKED" and "durable_native_authority_absent" in durable_gate.transaction["blockers"])

        offline_root = cache / "offline-root"
        (offline_root / "var/lib/pacman").mkdir(parents=True)
        offline = OfflineRootUpdateOps(offline_root, cache, runner=lambda command: (_ for _ in ()).throw(AssertionError("gate must prevent command execution")))
        concrete_blocked = execute_update(transaction, production_plan, offline, now=NOW)
        check("concrete offline executor remains behind production gate", concrete_blocked.transaction["state"] == "BLOCKED" and offline.commands == [])
        fixture_escape = execute_update(transaction, fixture_plan, offline, now=NOW)
        check("fixture label cannot unlock concrete system executor", fixture_escape.transaction["state"] == "BLOCKED" and fixture_escape.transaction["blockers"] == ["fixture_executor_not_isolated"] and offline.commands == [])
        rejected("concrete executor can never target live root", lambda: OfflineRootUpdateOps("/", cache))
        rejected("concrete executor rejects live Pacman cache", lambda: OfflineRootUpdateOps(offline_root, "/var/cache/pacman/pkg"))
        try:
            offline.run(("/usr/bin/pacman", "-Syu"), fixture_plan)
        except PermissionError:
            check("concrete executor refuses unallowlisted package mutation", True)

        rejected("kernel/header mismatch fails before mutation", lambda: build_execution_plan(transaction, manifest, cache, relationships(primary_headers={"package": "linux-cachyos-headers", "version": "wrong"}), execution_environment="fixture"))
        rejected("missing Fallback kernel fails before mutation", lambda: build_execution_plan(transaction, manifest, cache, relationships(fallback_kernel=None), execution_environment="fixture"))
        rejected("incomplete boot artifact matrix fails before mutation", lambda: build_execution_plan(transaction, manifest, cache, relationships(boot_artifacts=["/boot/vmlinuz-linux-cachyos"]), execution_environment="fixture"))

        before_mutation = execute_update(transaction, fixture_plan, FakeOps(fail="recovery-preparation"), now=NOW)
        check("pre-mutation recovery preparation failure is recoverable and bounded", before_mutation.transaction["state"] == "FAILED_RECOVERABLE" and not before_mutation.mutation_started)
        package_failure = execute_update(transaction, fixture_plan, FakeOps(fail="full-package-upgrade", failed_mutation=True), now=NOW)
        check("partial package mutation enters recovery", package_failure.transaction["state"] == "RECOVERED" and package_failure.recovery_attempted)
        for stage in ("maho-runtime", "kernel-header-dkms", "initramfs:linux-cachyos", "initramfs:linux-cachyos-lts", "boot-artifacts", "install-finalization"):
            failed_ops = FakeOps(fail=stage)
            result = execute_update(transaction, fixture_plan, failed_ops, now=NOW)
            check(f"{stage} failure invokes bounded recovery", result.transaction["state"] == "RECOVERED" and result.recovery_attempted and f"recover:{stage}" in failed_ops.calls)
        failed_recovery = execute_update(transaction, fixture_plan, FakeOps(fail="boot-artifacts", recover_ok=False), now=NOW)
        check("failed recovery becomes explicit attention handoff", failed_recovery.transaction["state"] == "ATTENTION_REQUIRED" and failed_recovery.transaction["blockers"] == ["update_recovery_failed"])

        interrupted = transition_transaction(transaction, UpdateState.INSTALLING, reason="fixture interrupted", now=NOW)
        reconciled = recover_interrupted_fixture(interrupted, fixture_plan, FakeOps(), now=NOW)
        check("interrupted durable transaction enters recovery", reconciled.transaction["state"] == "RECOVERED")

    print("ALL MAHO UPDATE TRANSACTION CONTRACTS PASS")


if __name__ == "__main__":
    main()
