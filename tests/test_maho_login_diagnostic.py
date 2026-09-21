#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_login_diagnostic import collect_login_diagnostic  # noqa: E402
from maho_runtime_release import _payload_hash  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        dev = root / "dev"; (dev / "tty2").parent.mkdir(parents=True); (dev / "tty2").touch()
        sysroot = root / "sys"; (sysroot / "module/nvidia_drm").mkdir(parents=True)
        session = root / "hyprland.desktop"; command = root / "start-hyprland"; command.write_text("#!/bin/sh\n"); command.chmod(0o755)
        session.write_text(f"[Desktop Entry]\nExec={command}\n")
        runtime_root = root / "runtime"; releases = runtime_root / "releases"; releases.mkdir(parents=True)
        stage = releases / "stage"; (stage / "share/maho").mkdir(parents=True)
        revision = "a" * 40; (stage / "share/maho/runtime-source-revision").write_text(revision + "\n")
        digest = _payload_hash(stage); release = releases / digest; stage.rename(release)
        (release / "manifest.json").write_text(json.dumps({"version": 3, "content_sha256": digest, "source_revision": revision}) + "\n")
        for path in sorted(release.rglob("*"), key=lambda item: len(item.parts), reverse=True): path.chmod(0o555 if path.is_dir() else 0o444)
        release.chmod(0o555); (runtime_root / "current").symlink_to(release)

        late_gpu = False
        def runner(argv, **kwargs):
            nonlocal late_gpu
            args = list(argv)
            if args[:2] == ["systemctl", "show"]:
                prop = next(x.split("=", 1)[1] for x in args if x.startswith("--property="))
                value = {"ActiveState": "active", "NRestarts": "0", "ExecMainStartTimestampMonotonic": "8000000"}[prop]
                return subprocess.CompletedProcess(args, 0, value + "\n", "")
            if args[0] == "loginctl": return subprocess.CompletedProcess(args, 0, "seat0\n", "")
            if args[0] == "journalctl" and "-u" in args:
                log = f'[    8.100] host sddm[1]: Using VT 2\n[    8.900] host sddm[1]: Reading from "{session}"\n[    9.000] host sddm[1]: Greeter session started successfully\n'
                return subprocess.CompletedProcess(args, 0, log, "")
            if args[0] == "journalctl":
                when = "8.500" if late_gpu else "7.500"
                return subprocess.CompletedProcess(args, 0, f"[    {when}] host kernel: [drm] Initialized nvidia-drm 0.0.0\n", "")
            return subprocess.CompletedProcess(args, 1, "", "unexpected")

        good = collect_login_diagnostic(runner=runner, dev_root=dev, sys_root=sysroot, runtime_root=runtime_root)
        check("login contract requires greeter evidence beyond active service", good["state"] == "PASS" and good["checks"]["greeter_instantiated"])
        check("login contract records non-automated physical visibility honestly", good["visible_confirmation"] == "not-automated")
        late_gpu = True
        raced = collect_login_diagnostic(runner=runner, dev_root=dev, sys_root=sysroot, runtime_root=runtime_root)
        check("late NVIDIA DRM readiness fails the login ordering contract", raced["state"] == "FAIL" and "gpu_ready_before_display_manager" in raced["failed_checks"])
    print("ALL MAHO LOGIN DIAGNOSTIC TESTS PASS")


if __name__ == "__main__":
    main()
