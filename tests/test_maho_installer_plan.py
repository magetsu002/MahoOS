#!/usr/bin/env python3
from __future__ import annotations

import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_installer_plan import (  # noqa: E402
    INSTALLER_STAGES,
    build_install_plan,
    disk_from_lsblk_payload,
    probe_disk,
    runtime_source_revision,
    validate_destructive_confirmation,
)

REV = "a" * 40


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def disk() -> dict:
    return {
        "path": "/dev/nvme9n1",
        "type": "disk",
        "size": 2_000_398_934_016,
        "ro": 0,
        "rm": 0,
        "model": "Maho Fixture NVMe",
        "serial": "MAHO-INSTALLER-0001",
        "wwn": "eui.0011223344556677",
        "tran": "nvme",
        "log-sec": 512,
        "phy-sec": 4096,
        "maj:min": "259:99",
        "mountpoints": [None],
        "children": [
            {
                "path": "/dev/nvme9n1p1",
                "type": "part",
                "mountpoints": [None],
            }
        ],
    }


def rejected(label: str, function) -> None:
    try:
        function()
    except (ValueError, RuntimeError):
        print("PASS", label)
        return
    raise AssertionError(label)


def main() -> None:
    first = build_install_plan(disk(), source_revision=REV)
    second = build_install_plan(copy.deepcopy(disk()), source_revision=REV)
    check("exact disk plan is deterministic", first == second)
    check("clean whole disk reaches destructive-confirmation gate", first["ready_for_destructive_confirmation"] is True and not first["blockers"])
    check("plan never grants mutation authority", first["execution_authority"] == "none" and first["mutation_performed"] is False)
    check("confirmation is bound to the full plan identity", first["destructive_confirmation"] == "ERASE-MAHO:" + first["plan_id"].removeprefix("install-plan-"))
    check("installer assembles the existing recovery stack", tuple(first["stages"]) == INSTALLER_STAGES and "guardian-recovery" in first["stages"] and "generation-authorities" in first["stages"])
    check("storage contract preserves Maho Btrfs generation shape", first["layout_contract"]["root"]["subvolumes"] == ["@", "@home", "@snapshots", "@var_log"])

    changed = disk()
    changed["serial"] = "MAHO-INSTALLER-0002"
    changed_plan = build_install_plan(changed, source_revision=REV)
    check("disk identity drift invalidates the old confirmation", changed_plan["destructive_confirmation"] != first["destructive_confirmation"])

    gate = validate_destructive_confirmation(
        first, disk(), source_revision=REV, confirmation=first["destructive_confirmation"],
    )
    check(
        "exact confirmation validates without granting execution authority",
        gate["confirmation_valid"] is True
        and gate["target_identity_sha256"] == first["target"]["identity_sha256"]
        and gate["execution_authority"] == "none"
        and gate["mutation_performed"] is False,
    )
    rejected(
        "confirmation cannot be replayed onto another disk identity",
        lambda: validate_destructive_confirmation(
            first, changed, source_revision=REV, confirmation=first["destructive_confirmation"],
        ),
    )
    rejected(
        "confirmation cannot be replayed across source revisions",
        lambda: validate_destructive_confirmation(
            first, disk(), source_revision="b" * 40, confirmation=first["destructive_confirmation"],
        ),
    )
    rejected(
        "wrong confirmation is rejected",
        lambda: validate_destructive_confirmation(
            first, disk(), source_revision=REV, confirmation="ERASE-MAHO:" + "0" * 64,
        ),
    )

    mounted = disk()
    mounted["children"][0]["mountpoints"] = ["/mnt/existing"]
    mounted_plan = build_install_plan(mounted, source_revision=REV)
    check("mounted target is blocked before confirmation", mounted_plan["blockers"] == ["target_or_child_mounted"] and mounted_plan["destructive_confirmation"] is None)

    partition = disk()
    partition["type"] = "part"
    check("partition target cannot masquerade as whole disk", "target_not_whole_disk" in build_install_plan(partition, source_revision=REV)["blockers"])

    readonly = disk()
    readonly["ro"] = 1
    check("read-only disk is blocked", "target_read_only" in build_install_plan(readonly, source_revision=REV)["blockers"])

    weak = disk()
    weak["serial"] = ""
    weak["wwn"] = ""
    check("unstable physical identity is blocked", "target_identity_not_stable" in build_install_plan(weak, source_revision=REV)["blockers"])

    rejected("invalid source revision is rejected", lambda: build_install_plan(disk(), source_revision="main"))

    source_root = ROOT / ".tmp-installer-source-fixture"
    try:
        (source_root / "share/maho").mkdir(parents=True, exist_ok=True)
        (source_root / "share/maho/runtime-source-revision").write_text(REV + "\n", encoding="utf-8")
        check("runtime source revision is read from immutable metadata", runtime_source_revision(source_root) == REV)
        (source_root / "share/maho/runtime-source-revision").write_text("main\n", encoding="utf-8")
        rejected("non-SHA runtime source metadata is rejected", lambda: runtime_source_revision(source_root))
    finally:
        import shutil
        shutil.rmtree(source_root, ignore_errors=True)
    rejected("invalid disk path is rejected", lambda: build_install_plan(disk() | {"path": "/"}, source_revision=REV))

    payload = {"blockdevices": [disk()]}
    parsed = disk_from_lsblk_payload(payload, expected_path="/dev/nvme9n1")
    check("lsblk parser binds one exact target path", parsed["serial"] == "MAHO-INSTALLER-0001")
    rejected("lsblk path drift is rejected", lambda: disk_from_lsblk_payload(payload, expected_path="/dev/nvme0n1"))

    class Result:
        returncode = 0
        stderr = ""
        stdout = __import__("json").dumps(payload)

    commands = []
    def fake_run(command, **kwargs):
        commands.append(tuple(command))
        return Result()

    observed = probe_disk("/dev/nvme9n1", run=fake_run)
    check("live probe uses read-only lsblk against exact device", observed["path"] == "/dev/nvme9n1" and commands and commands[0][-1] == "/dev/nvme9n1")
    check("live probe never invokes a mutating tool", commands[0][0] == "lsblk")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        packaged_root = tmp_path / "payload"
        (packaged_root / "bin").mkdir(parents=True)
        (packaged_root / "lib").mkdir(parents=True)
        (packaged_root / "lib/bytecode_probe.py").write_text("VALUE = 1\n", encoding="utf-8")
        (packaged_root / "bin/maho-installer").write_text(
            "import os, sys\n"
            "sys.path.insert(0, os.path.join(os.environ['MAHO_ROOT'], 'lib'))\n"
            "import bytecode_probe\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        env.pop("PYTHONPYCACHEPREFIX", None)
        env["HOME"] = str(tmp_path / "home")
        env["XDG_DATA_HOME"] = str(tmp_path / "data")
        env["MAHO_PACKAGED_ROOT"] = str(packaged_root)
        wrapper = ROOT / "packaging/arch/maho-installer-wrapper"

        subprocess.run(["bash", str(wrapper), "--help"], env=env, check=True)
        check(
            "packaged installer help keeps payload bytecode-free",
            not any(packaged_root.rglob("__pycache__")),
        )

        current = tmp_path / "data/maho/runtime/current"
        current.parent.mkdir(parents=True)
        current.symlink_to(packaged_root, target_is_directory=True)
        subprocess.run(["bash", str(wrapper), "--help"], env=env, check=True)
        check(
            "runtime installer help keeps immutable release bytecode-free",
            not any(packaged_root.rglob("__pycache__")),
        )

    print("ALL MAHO INSTALLER PLAN CONTRACTS PASS")


if __name__ == "__main__":
    main()
