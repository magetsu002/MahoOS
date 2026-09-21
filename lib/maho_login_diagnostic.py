#!/usr/bin/env python3
"""Read-only graphical-login contract from current-boot evidence."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from typing import Any, Callable, Sequence

from maho_runtime_release import verify_release

Runner = Callable[..., subprocess.CompletedProcess[str]]
_MONO = re.compile(r"^\[\s*([0-9]+(?:\.[0-9]+)?)\]")


def _run(runner: Runner, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return runner(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _show(runner: Runner, unit: str, prop: str) -> str | None:
    result = _run(runner, ("systemctl", "show", unit, f"--property={prop}", "--value"))
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _first_time(text: str, needle: str) -> float | None:
    for line in text.splitlines():
        if needle not in line:
            continue
        match = _MONO.match(line)
        if match:
            return float(match.group(1))
    return None


def _session_command(path: Path) -> tuple[str | None, bool]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None, False
    raw = next((line.split("=", 1)[1].strip() for line in lines if line.startswith("Exec=")), "")
    if not raw:
        return None, False
    try:
        command = shlex.split(raw)[0]
    except (ValueError, IndexError):
        return raw, False
    available = Path(command).is_file() if command.startswith("/") else shutil.which(command) is not None
    return command, available


def collect_login_diagnostic(
    *, runner: Runner = subprocess.run, dev_root: Path = Path("/dev"),
    sys_root: Path = Path("/sys"), runtime_root: Path | None = None,
) -> dict[str, Any]:
    home = Path(os.environ.get("HOME", ""))
    runtime_root = runtime_root or Path(
        os.environ.get("MAHO_RUNTIME_ROOT")
        or Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")) / "maho/runtime"
    )
    current = runtime_root / "current"
    runtime = verify_release(current, runtime_root / "releases")

    graphical = _show(runner, "graphical.target", "ActiveState")
    dm_active = _show(runner, "display-manager.service", "ActiveState")
    restarts_raw = _show(runner, "display-manager.service", "NRestarts")
    dm_start_raw = _show(runner, "display-manager.service", "ExecMainStartTimestampMonotonic")
    try:
        restarts = int(restarts_raw or "")
    except ValueError:
        restarts = None
    try:
        dm_start = int(dm_start_raw or "") / 1_000_000
    except ValueError:
        dm_start = None

    sddm_result = _run(runner, ("journalctl", "-b", "-u", "sddm.service", "-o", "short-monotonic", "--no-pager"))
    sddm_log = sddm_result.stdout if sddm_result.returncode == 0 else ""
    greeter_time = _first_time(sddm_log, "Greeter session started successfully")
    vt_match = re.search(r"Using VT\s+([0-9]+)", sddm_log)
    vt = int(vt_match.group(1)) if vt_match else None
    tty_exists = bool(vt and (dev_root / f"tty{vt}").exists())

    seat_result = _run(runner, ("loginctl", "seat-status", "seat0"))
    seat_ok = seat_result.returncode == 0 and "seat0" in seat_result.stdout

    session_match = re.search(r'Reading from "([^"]+\.desktop)"', sddm_log)
    session_path = Path(session_match.group(1)) if session_match else Path("/usr/share/wayland-sessions/hyprland.desktop")
    session_command, session_valid = _session_command(session_path)

    kernel_result = _run(runner, ("journalctl", "-b", "-k", "-o", "short-monotonic", "--no-pager"))
    kernel_log = kernel_result.stdout if kernel_result.returncode == 0 else ""
    nvidia_ready = _first_time(kernel_log, "Initialized nvidia-drm")
    nvidia_present = (sys_root / "module/nvidia_drm").exists()
    gpu_order_ok = (not nvidia_present) or (
        nvidia_ready is not None and dm_start is not None and nvidia_ready <= dm_start
    )

    checks = {
        "graphical_target": graphical == "active",
        "display_manager": dm_active == "active",
        "greeter_instantiated": greeter_time is not None,
        "seat0": seat_ok,
        "expected_vt": tty_exists,
        "restart_loop_absent": restarts is not None and restarts <= 1,
        "runtime_current": runtime.verified,
        "session_path": session_valid,
        "gpu_ready_before_display_manager": gpu_order_ok,
    }
    unknown = any(value is None for value in (graphical, dm_active, restarts, dm_start)) or sddm_result.returncode != 0
    state = "PASS" if all(checks.values()) else "UNKNOWN" if unknown else "FAIL"
    failed = sorted(name for name, ok in checks.items() if not ok)
    return {
        "schema_version": 1,
        "kind": "maho-login-diagnostic",
        "state": state,
        "checks": checks,
        "failed_checks": failed,
        "graphical_target_state": graphical,
        "display_manager_state": dm_active,
        "display_manager_restarts": restarts,
        "display_manager_start_monotonic": dm_start,
        "greeter_start_monotonic": greeter_time,
        "seat": "seat0" if seat_ok else None,
        "vt": vt,
        "session_path": str(session_path),
        "session_command": session_command,
        "runtime_source_revision": runtime.source_revision,
        "runtime_reasons": list(runtime.reasons),
        "nvidia_drm_ready_monotonic": nvidia_ready,
        "visible_confirmation": "not-automated",
    }


if __name__ == "__main__":
    import json
    value = collect_login_diagnostic()
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    raise SystemExit(0 if value["state"] == "PASS" else 1)
