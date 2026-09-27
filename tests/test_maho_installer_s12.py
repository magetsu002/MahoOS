#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_installer_assembly import AssemblyInterruption, assemble_installed_system
from maho_installer_execute import ASSEMBLY_PHASES, PHASES, STORAGE_PHASES
from maho_installer_payload import (
    REQUIRED_PACKAGES,
    _canonical,
    _validate_dependency_closure,
    validate_payload_manifest,
)
from maho_installer_plan import MINIMUM_DISK_BYTES, build_install_plan
from maho_installer_receipt import (
    _canonical as receipt_canonical,
    build_install_receipt,
    certify_first_boot,
    validate_install_receipt,
)
from maho_installer_system import SystemAssemblyOps

REV = "a" * 40
ATTEMPT = "11111111-1111-4111-8111-111111111111"
HEX = "b" * 64


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def rejected(name: str, fn) -> None:
    try:
        fn()
    except (ValueError, RuntimeError):
        print("PASS", name)
        return
    raise AssertionError(name)


def disk() -> dict:
    return {
        "path": "/dev/vdz",
        "type": "disk",
        "size": MINIMUM_DISK_BYTES,
        "ro": 0,
        "rm": 0,
        "model": "QEMU HARDDISK",
        "serial": "MAHO-DISPOSABLE-S12",
        "wwn": "",
        "tran": "virtio",
        "back-file": "",
        "log-sec": 512,
        "phy-sec": 4096,
        "maj:min": "252:99",
        "mountpoints": [None],
        "pttype": None,
        "fstype": None,
    }


def plan() -> dict:
    return build_install_plan(disk(), source_revision=REV, install_attempt_id=ATTEMPT)


def payload() -> dict:
    names = sorted(REQUIRED_PACKAGES | {"intel-ucode"})
    packages = []
    for index, name in enumerate(names):
        packages.append({
            "name": name,
            "version": "1-1",
            "architecture": "x86_64",
            "filename": f"{name}-1-1-x86_64.pkg.tar.zst",
            "sha256": f"{index + 1:064x}",
            "repository": "maho-exact-build" if name == "maho-os" else "signed-pacman-repository",
            "signature": {
                "status": "exact-local-build" if name == "maho-os" else "verified",
                "evidence_sha256": f"{index + 101:064x}",
            },
            "depends": [],
            "provides": [],
        })
    material = {
        "schema_version": 1,
        "kind": "maho-installer-payload",
        "source_revision": REV,
        "package_version": "1-1",
        "runtime_archive_sha256": "f" * 64,
        "repositories": [{
            "name": "core",
            "database_file": "core.db",
            "database_sha256": "1" * 64,
            "signature_file": "core.db.sig",
            "signature_sha256": "2" * 64,
            "verification_evidence_sha256": "3" * 64,
        }],
        "packages": packages,
    }
    digest = hashlib.sha256(_canonical(material)).hexdigest()
    return validate_payload_manifest(material | {
        "payload_sha256": digest,
        "package_generation_id": f"pkg-{digest}",
    })


def mounted_journal(value: dict) -> dict:
    return {
        "schema_version": 2,
        "kind": "maho-installer-storage-journal",
        "install_attempt_id": value["install_attempt_id"],
        "plan_id": value["plan_id"],
        "plan_sha256": value["plan_sha256"],
        "target_identity_sha256": value["target"]["identity_sha256"],
        "installation_uuid": value["installation_identity"]["installation_uuid"],
        "phase": "MOUNTED",
        "history": [{"phase": phase, "recorded_at": "2026-09-27T00:00:00Z"} for phase in STORAGE_PHASES],
    }


class FakeAssemblyOps:
    def __init__(self, *, mount_ok: bool = True) -> None:
        self.mount_ok = mount_ok
        self.applied: set[str] = set()
        self.calls: list[str] = []
        self.mount_checks = 0

    def verify_target_mount(self, plan, mount_root):
        self.mount_checks += 1
        return {"verified": self.mount_ok}

    def phase_complete(self, phase, plan, payload, journal, mount_root):
        return phase in self.applied or phase in (journal.get("phase_evidence") or {})

    def phase_started(self, phase, plan, payload, journal, mount_root):
        return False

    def apply_phase(self, phase, plan, payload, journal, mount_root):
        self.calls.append(phase)
        self.applied.add(phase)
        return {"phase": phase, "automatic_reboot": False}


def invoke_assembly(tmp: Path, p: dict, pl: dict, ops: FakeAssemblyOps, *, fail_after=None):
    journal = tmp / "journal.json"
    if not journal.exists():
        journal.write_text(json.dumps(mounted_journal(p)), encoding="utf-8")
    return assemble_installed_system(
        p, pl, journal_path=journal, mount_root=tmp / "target",
        ops=ops, fail_after=fail_after, require_root=False,
    )


def receipt_evidence(p: dict, pl: dict) -> dict:
    return {
        "IDENTITIES_CREATED": {
            "machine_id": "1" * 32,
            "root_subvolume_uuid": "11111111-2222-3333-4444-555555555555",
            "home_subvolume_uuid": "66666666-7777-8888-9999-aaaaaaaaaaaa",
        },
        "USERS_CREATED": {
            "name": "magetsu", "uid": 1000, "wheel": True,
            "root_locked": True, "home_fsroot": "/@home",
        },
        "RUNTIME_INSTALLED": {
            "source_revision": REV, "content_sha256": "4" * 64,
            "deployment_class": "production", "trust_eligible": True, "verified": True,
        },
        "KERNELS_INSTALLED": {
            "primary_package": "linux-cachyos", "primary_release": "6.18.1-cachyos",
            "fallback_package": "linux-cachyos-lts", "fallback_release": "6.12.50-lts",
            "primary_headers": True, "fallback_headers": True, "microcode_package": "intel-ucode",
        },
        "INITRAMFS_BUILT": {
            "primary_sha256": "5" * 64, "fallback_sha256": "6" * 64,
            "luks_uuid": p["installation_identity"]["luks_uuid"],
            "root_uuid": p["installation_identity"]["btrfs_uuid"],
        },
        "BOOT_GENERATION_PUBLISHED": {
            "boot_generation_id": "bootgen-" + "7" * 64,
            "normal_loader": "/EFI/MahoOS/Normal/limine.efi",
            "fallback_entry": "MahoOS Fallback",
            "recovery_loader": "/EFI/MahoOS/Recovery/limine.efi",
            "signer_fingerprint": "AA",
            "boot_sha256": {"/boot/EFI/BOOT/BOOTX64.EFI": "8" * 64},
        },
        "RECOVERY_INSTALLED": {
            "recovery_identity": "recovery-1",
            "filesystem_uuid": p["installation_identity"]["btrfs_uuid"],
            "snapshot_id": 1, "snapshot_path": "/@snapshots/1/snapshot", "read_only": True,
            "fallback_kernel_sha256": "9" * 64, "fallback_initramfs_sha256": "a" * 64,
        },
        "SERVICES_INSTALLED": {
            "networkmanager_enabled": True, "sddm_enabled": True, "session_installed": True,
            "coordinator_installed": True, "coordinator_timer_enabled": True,
            "guardian_user_service_enabled": True, "production_prevention_enabled": False,
        },
        "SYSTEM_GENERATION_PUBLISHED": {
            "system_generation_id": "gen-" + "b" * 64,
            "kernel_generation_id": "kgen-" + "c" * 64,
            "package_generation_id": pl["package_generation_id"],
            "transaction_id": "tx", "provenance_id": "prov", "preboot_trust_state": "UNKNOWN",
        },
    }


def healthy_observation(receipt: dict) -> dict:
    return {
        "storage": {
            "btrfs_uuid": receipt["storage"]["btrfs_uuid"],
            "root_fsroot": "/@",
            "root_subvolume_uuid": receipt["storage"]["root_subvolume_uuid"],
            "home_subvolume_uuid": receipt["storage"]["home_subvolume_uuid"],
            "luks_uuid": receipt["storage"]["luks_uuid"],
            "mapper_name": receipt["storage"]["mapper_name"],
            "installation_uuid": receipt["installation_uuid"],
        },
        "machine_id": receipt["machine_id"],
        "generations": {
            "system_generation_id": receipt["system_generation_id"],
            "package_generation_id": receipt["package_generation_id"],
            "kernel_generation_id": receipt["kernel_generation_id"],
            "boot_generation_id": receipt["boot_generation_id"],
        },
        "runtime": dict(receipt["runtime"]),
        "boot": {
            "running_kernel": receipt["kernel"]["primary_release"],
            "boot_sha256": dict(receipt["boot"]["boot_sha256"]),
            "fallback_artifacts_present": True,
        },
        "guardian": {
            "service_active": True, "required_evidence_fresh": True,
            "provider_health": {}, "trust_state": "UNKNOWN",
        },
        "recovery": {
            "recovery_identity": receipt["recovery_identity"], "artifacts_present": True,
        },
        "user": dict(receipt["user"]),
        "services": {
            "networkmanager_enabled": True, "networkmanager_active": True,
            "sddm_enabled": True, "session_installed": True,
            "coordinator_installed": True, "coordinator_timer_enabled": True,
            "firewall_enabled": True, "guardian_user_service_enabled": True,
            "production_prevention_enabled": False,
        },
        "firewall": {
            "receipt_valid": True, "table_present": True, "provider_global_authority": False,
        },
        "failed_units": [],
        "boot_id": "22222222-3333-4444-8555-666666666666",
    }


def private_file(root: Path, name: str, value: bytes) -> Path:
    path = root / name
    path.write_bytes(value)
    path.chmod(0o600)
    return path


class IdentityOps(SystemAssemblyOps):
    def _run(self, command, *, input_bytes=None, check=True):
        if command[0] == "systemd-machine-id-setup":
            root_arg = next(item for item in command if item.startswith("--root="))
            target = Path(root_arg.split("=", 1)[1]) / "etc/machine-id"
            target.write_text("d" * 32 + "\n", encoding="utf-8")
            stdout = b""
        elif command[:3] == ("btrfs", "subvolume", "show"):
            uuid = b"11111111-2222-3333-4444-555555555555" if str(command[3]).endswith("target") else b"66666666-7777-8888-9999-aaaaaaaaaaaa"
            stdout = b"UUID: " + uuid + b"\n"
        else:
            stdout = b""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")


class InitramfsOps(SystemAssemblyOps):
    def __init__(self, *args, broken=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.broken = broken

    def _chroot(self, root, command, *, input_bytes=None, check=True):
        if command[1] == "-c":
            stdout = b"HOOKS=(base systemd microcode block sd-encrypt filesystems fsck)\n"
        else:
            rows = [
                "usr/bin/btrfs", "usr/lib/systemd/systemd",
                "usr/lib/systemd/systemd-cryptsetup",
                "usr/lib/systemd/system-generators/systemd-cryptsetup-generator",
                "etc/crypttab", "usr/lib/modules/x/kernel/dm-crypt.ko.zst",
            ]
            if self.broken:
                rows.remove("usr/lib/systemd/systemd-cryptsetup")
            stdout = ("\n".join(rows) + "\n").encode()
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")


def make_ops(cls, tmp: Path, **kwargs):
    password = private_file(tmp, "password", b"correct horse battery staple\n")
    storage = private_file(tmp, "storage", b"storage-key\n")
    return cls(
        payload_dir=tmp, user_name="magetsu", host_name="maho-test",
        password_file=password, storage_key_file=storage,
        recovery_key_output=tmp / "recovery-key", **kwargs,
    )


def main() -> None:
    p = plan()
    pl = payload()

    check("exact payload identity validates", validate_payload_manifest(pl)["package_generation_id"] == pl["package_generation_id"])
    changed = copy.deepcopy(pl)
    changed["packages"][0]["version"] = "2-1"
    rejected("payload content tampering breaks exact identity", lambda: validate_payload_manifest(changed))
    _validate_dependency_closure([
        {"name": "provider", "provides": ["virtual=1"], "depends": []},
        {"name": "consumer", "provides": [], "depends": ["virtual>=1"]},
    ])
    print("PASS dependency closure accepts exact provided capability")
    rejected("missing payload dependency is rejected", lambda: _validate_dependency_closure([
        {"name": "consumer", "provides": [], "depends": ["missing>=1"]},
    ]))

    with tempfile.TemporaryDirectory(prefix="maho-s12-assembly-") as raw:
        tmp = Path(raw)
        ops = FakeAssemblyOps()
        result = invoke_assembly(tmp, p, pl, ops)
        check("assembly records every durable S1.2 phase", result["phase"] == "UNMOUNTED" and [x["phase"] for x in result["history"]] == list(PHASES[:PHASES.index("UNMOUNTED") + 1]))
        check("assembly never introduces an automatic reboot", all((result.get("phase_evidence") or {}).get(phase, {}).get("automatic_reboot") is not True for phase in ASSEMBLY_PHASES))
        check("target mount identity is verified before assembly mutation", ops.mount_checks == 1)

    interruption_phases = [
        "BASE_INSTALLED", "IDENTITIES_CREATED", "RUNTIME_INSTALLED", "KERNELS_INSTALLED",
        "INITRAMFS_BUILT", "BOOT_GENERATION_PUBLISHED", "RECOVERY_INSTALLED",
        "SYSTEM_GENERATION_PUBLISHED", "INSTALL_RECEIPT_WRITTEN",
    ]
    for phase in interruption_phases:
        with tempfile.TemporaryDirectory(prefix="maho-s12-interrupt-") as raw:
            tmp = Path(raw)
            try:
                invoke_assembly(tmp, p, pl, FakeAssemblyOps(), fail_after=phase)
            except AssemblyInterruption:
                pass
            else:
                raise AssertionError(f"interruption after {phase} was not surfaced")
            resumed = invoke_assembly(tmp, p, pl, FakeAssemblyOps())
            check(f"durable interruption after {phase} resumes idempotently", resumed["phase"] == "UNMOUNTED")

    with tempfile.TemporaryDirectory(prefix="maho-s12-partial-") as raw:
        tmp = Path(raw)
        try:
            invoke_assembly(tmp, p, pl, FakeAssemblyOps(), fail_after="PAYLOAD_VERIFIED")
        except AssemblyInterruption:
            pass
        journal_path = tmp / "journal.json"
        value = json.loads(journal_path.read_text())
        value["in_progress_phase"] = "BASE_INSTALLED"
        journal_path.write_text(json.dumps(value), encoding="utf-8")
        rejected("uncertain in-phase mutation stops for explicit inspection", lambda: invoke_assembly(tmp, p, pl, FakeAssemblyOps()))

    with tempfile.TemporaryDirectory(prefix="maho-s12-mount-") as raw:
        rejected("wrong mounted target identity blocks before mutation", lambda: invoke_assembly(Path(raw), p, pl, FakeAssemblyOps(mount_ok=False)))

    evidence = receipt_evidence(p, pl)
    receipt = build_install_receipt(p, pl, evidence)
    observation = healthy_observation(receipt)
    healthy = certify_first_boot(receipt, observation, verified_at="2026-09-27T00:00:00Z")
    check("successful independent first-boot evidence certifies INSTALLATION_HEALTHY", healthy["state"] == "INSTALLATION_HEALTHY")
    check("installation health does not manufacture Guardian trust", healthy["healthy_receipt"]["guardian_trust_state"] == "UNKNOWN")

    cases = [
        ("wrong root rejected", lambda o: o["storage"].__setitem__("root_fsroot", "/@wrong"), "storage_root_fsroot_mismatch"),
        ("wrong installation UUID rejected", lambda o: o["storage"].__setitem__("installation_uuid", "wrong"), "installation_uuid_mismatch"),
        ("wrong generation rejected", lambda o: o["generations"].__setitem__("system_generation_id", "gen-" + "0" * 64), "system_generation_id_mismatch"),
        ("wrong runtime rejected", lambda o: o["runtime"].__setitem__("content_sha256", "0" * 64), "runtime_content_sha256_mismatch"),
        ("stale Guardian evidence rejects health", lambda o: o["guardian"].__setitem__("required_evidence_fresh", False), "guardian_required_evidence_stale_or_missing"),
        ("missing recovery artifact rejects health", lambda o: o["recovery"].__setitem__("artifacts_present", False), "recovery_artifacts_missing"),
        ("incorrect user rejects health", lambda o: o["user"].__setitem__("uid", 1001), "user_uid_mismatch"),
        ("incorrect home subvolume rejects health", lambda o: o["storage"].__setitem__("home_subvolume_uuid", "wrong"), "storage_home_subvolume_uuid_mismatch"),
        ("wrong machine identity rejects health", lambda o: o.__setitem__("machine_id", "0" * 32), "machine_id_mismatch"),
    ]
    for label, mutate, blocker in cases:
        candidate = copy.deepcopy(observation)
        mutate(candidate)
        result = certify_first_boot(receipt, candidate)
        check(label, result["state"] == "ATTENTION_REQUIRED" and blocker in result["blockers"])

    secret_receipt = copy.deepcopy(receipt)
    secret_receipt["user"]["password"] = "never-store-me"
    material = dict(secret_receipt)
    material.pop("receipt_id")
    secret_receipt["receipt_id"] = "install-receipt-" + hashlib.sha256(receipt_canonical(material)).hexdigest()
    rejected("plaintext secret fields are forbidden from install receipts", lambda: validate_install_receipt(secret_receipt))

    with tempfile.TemporaryDirectory(prefix="maho-s12-system-") as raw:
        tmp = Path(raw)
        root = tmp / "target"
        root.mkdir()
        ops = make_ops(IdentityOps, tmp)
        identity = ops._phase_identities_created(p, pl, {}, root)
        fstab = (root / "etc/fstab").read_text()
        crypttab = (root / "etc/crypttab.initramfs").read_text()
        check("fstab binds exact Btrfs and ESP identities", p["installation_identity"]["btrfs_uuid"] in fstab and f"PARTUUID={p['installation_identity']['esp_partition_uuid']}" in fstab and all(f"subvol={name}" in fstab for name in ("@", "@home", "@snapshots", "@var_log")))
        check("crypttab binds exact LUKS identity", p["installation_identity"]["luks_uuid"] in crypttab and p["encryption_contract"]["mapper_name"] in crypttab)
        check("machine and installation identities remain separate", identity["machine_id"] != p["installation_identity"]["installation_uuid"])
        mode = stat.S_IMODE((tmp / "recovery-key").stat().st_mode)
        check("recovery key export is private and explicit", identity["password_slot_added"] is True and identity["recovery_key_exported"] is True and mode == 0o600)
        check("identity evidence contains no plaintext password", "correct horse battery staple" not in json.dumps(identity))

        normal = ops._cmdline(p)
        recovery = ops._cmdline(p, recovery=True)
        check("normal boot is writable and recovery boot is read-only", " rw " in f" {normal} " and " ro " in f" {recovery} " and " rw " not in f" {recovery} ")

        init_ok = make_ops(InitramfsOps, tmp)
        verified = init_ok._verify_initramfs(root, "/boot/initramfs-test.img")
        check("initramfs verification requires encryption and Btrfs closure", verified["dm_crypt_present"] is True and "sd-encrypt" in verified["hooks"])
        init_bad = make_ops(InitramfsOps, tmp, broken=True)
        rejected("incomplete initramfs content fails closed", lambda: init_bad._verify_initramfs(root, "/boot/initramfs-test.img"))

        release = root / "home/magetsu/.local/share/maho/runtime/releases/abc"
        release.mkdir(parents=True)
        current = release.parents[1] / "current"
        current.symlink_to("/home/magetsu/.local/share/maho/runtime/releases/abc")
        check("target absolute runtime symlink resolves inside installed root", ops._target_symlink_release(root, current) == release.resolve())

    firstboot_unit = (ROOT / "config/systemd/system/maho-installer-firstboot.service").read_text()
    unit_part, service_part = firstboot_unit.split("[Service]", 1)
    check("first-boot StartLimit directives are valid Unit directives", "StartLimitIntervalSec=" in unit_part and "StartLimitBurst=" in unit_part and "StartLimitIntervalSec=" not in service_part)
    check("first-boot service stops retrying after durable health", "ConditionPathExists=!/var/lib/maho/installer/installation-healthy.json" in unit_part)

    system_source = (ROOT / "lib/maho_installer_system.py").read_text()
    cli_source = (ROOT / "bin/maho-installer").read_text()
    check("installer has no hidden reboot command", '("reboot"' not in system_source and '("systemctl", "reboot"' not in system_source and '"reboot"' not in cli_source)
    check("boot signing private key cleanup is fail-safe", "finally:" in system_source and "run_key.unlink(missing_ok=True)" in system_source)
    check("user-manager wants links are target-relative", 'link.symlink_to(Path("..") / unit)' in system_source)

    pkgbuild = (ROOT / "packaging/arch/PKGBUILD.in").read_text()
    check("S2.1 coordinator package/systemd wiring is preserved", "maho-update-coordinator.service" in pkgbuild and "maho-update-coordinator.timer" in pkgbuild and "timers.target.wants/maho-update-coordinator.timer" in pkgbuild)
    check("S1.2 firstboot and firewall services are package-owned", "maho-installer-firstboot.service" in pkgbuild and "maho-firewall.service" in pkgbuild)

    print("ALL MAHO INSTALLER S1.2 CONTRACTS PASS")


if __name__ == "__main__":
    main()
