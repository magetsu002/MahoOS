#!/usr/bin/env python3
"""Representative, non-disruptive MahoOS low-memory certification harness."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import sys
import time
from typing import Any

GIB = 1024 ** 3
MIB = 1024 ** 2
PROFILES = {
    "4g": {"memory_max": 4 * GIB, "memory_high": int(4 * GIB * 0.85), "pressure_target": 0.90, "idle_target_mib": 900},
    "8g": {"memory_max": 8 * GIB, "memory_high": int(8 * GIB * 0.85), "pressure_target": 0.90, "idle_target_mib": 1126},
}
CORE = ("hyprland", "shell", "dock", "notify", "guardian", "adaptive", "observe", "security")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run(argv: list[str], *, env: dict[str, str] | None = None, timeout: float = 10, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=check)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def manager_environment(runtime: Path) -> tuple[dict[str, str], dict[str, str]]:
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = str(runtime)
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    result = run(["systemctl", "--user", "show-environment"], env=env, timeout=8)
    if result.returncode != 0:
        raise RuntimeError(f"cannot query user manager: {result.stderr.strip()}")
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return env, values


def cgroup_path() -> Path:
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0":
            return Path("/sys/fs/cgroup") / fields[2].lstrip("/")
    raise RuntimeError("unified cgroup v2 path unavailable")


def read_int(path: Path) -> int | None:
    try:
        value = path.read_text().strip()
        return None if value == "max" else int(value)
    except (OSError, ValueError):
        return None


def read_kv(path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        for line in path.read_text().splitlines():
            fields = line.split()
            if len(fields) == 2:
                try:
                    out[fields[0]] = int(fields[1])
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def read_pressure(path: Path) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    try:
        for line in path.read_text().splitlines():
            fields = line.split()
            row: dict[str, float | int] = {}
            for item in fields[1:]:
                key, value = item.split("=", 1)
                row[key] = int(value) if key == "total" else float(value)
            out[fields[0]] = row
    except (OSError, ValueError):
        pass
    return out


def proc_metrics(pid: int) -> dict[str, Any] | None:
    root = Path("/proc") / str(pid)
    try:
        cmdline = root.joinpath("cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
        stat = root.joinpath("stat").read_text().split()
    except OSError:
        return None
    row: dict[str, Any] = {"pid": pid, "cmdline": cmdline[:1000]}
    try:
        for line in root.joinpath("smaps_rollup").read_text().splitlines():
            if line.startswith(("Pss:", "SwapPss:", "Rss:")):
                key = line.split(":", 1)[0].lower() + "_kib"
                row[key] = int(line.split()[1])
    except OSError:
        pass
    try:
        row["fds"] = len(list(root.joinpath("fd").iterdir()))
    except OSError:
        pass
    try:
        for line in root.joinpath("status").read_text().splitlines():
            if line.startswith("Threads:"):
                row["threads"] = int(line.split()[1])
                break
    except OSError:
        pass
    try:
        ticks = int(stat[13]) + int(stat[14])
        row["cpu_seconds"] = round(ticks / os.sysconf(os.sysconf_names["SC_CLK_TCK"]), 3)
        row["start_ticks"] = int(stat[21])
    except (ValueError, IndexError):
        pass
    row["label"] = label_process(cmdline)
    return row


def label_process(cmd: str) -> str:
    checks = (
        ("shell", ("quickshell", "maho-shell/shell.qml")),
        ("dock", ("quickshell", "maho-shell/dock-shell.qml")),
        ("notify", ("quickshell", "maho-notify/shell.qml")),
        ("guardian", ("guardian_watch_main.py",)),
        ("adaptive", ("maho_adaptive_shadow.py", "watch")),
        ("observe", ("maho-observe", "watch")),
        ("security", ("maho-security-monitor", "watch")),
        ("clipboard", ("maho-clipboard-history", "serve")),
        ("hyprland", ("Hyprland", "hyprland.conf")),
        ("portal-hyprland", ("xdg-desktop-portal-hyprland",)),
        ("portal-gtk", ("xdg-desktop-portal-gtk",)),
        ("portal", ("xdg-desktop-portal",)),
        ("browser", ("brave",)),
        ("dev-indexer", ("maho-dev-indexer",)),
        ("pressure", ("maho-pressure-worker",)),
        ("app-probe", ("maho-memory-probe",)),
        ("dbus", ("dbus-daemon",)),
    )
    for label, needles in checks:
        if all(needle in cmd for needle in needles):
            return label
    return "other"


def snapshot(cg: Path, name: str, started: float) -> dict[str, Any]:
    pids: list[int] = []
    try:
        pids = [int(x) for x in cg.joinpath("cgroup.procs").read_text().split()]
    except OSError:
        pass
    processes = [row for pid in pids if (row := proc_metrics(pid)) is not None]
    total_pss = sum(int(row.get("pss_kib", 0)) for row in processes)
    total_swap_pss = sum(int(row.get("swappss_kib", 0)) for row in processes)
    zram = ""
    try:
        zram = Path("/sys/block/zram0/mm_stat").read_text().strip()
    except OSError:
        pass
    return {
        "name": name,
        "captured_at": utc_now(),
        "elapsed_s": round(time.time() - started, 3),
        "memory_current": read_int(cg / "memory.current"),
        "memory_swap_current": read_int(cg / "memory.swap.current"),
        "memory_peak": read_int(cg / "memory.peak"),
        "memory_events": read_kv(cg / "memory.events"),
        "memory_stat": read_kv(cg / "memory.stat"),
        "memory_pressure": read_pressure(cg / "memory.pressure"),
        "total_pss_kib": total_pss,
        "total_swappss_kib": total_swap_pss,
        "processes": sorted(processes, key=lambda row: (row.get("label", ""), row["pid"])),
        "zram0_mm_stat": zram,
    }


def start_logged(name: str, argv: list[str], env: dict[str, str], logs: Path, *, stdin=None) -> subprocess.Popen[str]:
    handle = logs.joinpath(f"{name}.log").open("a")
    proc = subprocess.Popen(argv, env=env, stdin=stdin or subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    proc._maho_log_handle = handle  # type: ignore[attr-defined]
    return proc


def stop_proc(proc: subprocess.Popen[str] | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def copy_tree_if_present(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, dirs_exist_ok=True)


def prepare_home(root: Path, real_home: Path, base: Path) -> dict[str, str]:
    home = base / "h"
    runtime = base / "r"
    state = home / ".local/state"
    cache = home / ".cache"
    config = home / ".config"
    data = home / ".local/share"
    for path in (home, runtime, state, cache, config, data, home / ".local/bin", base / "logs"):
        path.mkdir(parents=True, exist_ok=True)
    runtime.chmod(0o700)
    real_runtime = real_home / ".local/share/maho/runtime"
    if real_runtime.is_dir():
        data.joinpath("maho").mkdir(parents=True, exist_ok=True)
        data.joinpath("maho/runtime").symlink_to(real_runtime, target_is_directory=True)

    theme = real_home / ".cache/maho/theme/active.json"
    if theme.is_file():
        target = cache / "maho/theme/active.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(theme, target)
    copy_tree_if_present(real_home / ".local/state/maho/notify", state / "maho/notify")
    copy_tree_if_present(real_home / ".local/state/maho/security", state / "maho/security")
    for shell_id in ("maho-shell", "maho-dock", "maho-notify"):
        copy_tree_if_present(real_home / f".local/state/quickshell/by-shell/{shell_id}", state / f"quickshell/by-shell/{shell_id}")

    local_bin = home / ".local/bin"
    for candidate in root.joinpath("bin").iterdir():
        if not candidate.is_file():
            continue
        target = local_bin / candidate.name
        if os.access(candidate, os.X_OK):
            target.symlink_to(candidate)
            continue
        first = candidate.read_text(errors="ignore").splitlines()[:1]
        interpreter = "python3" if first and "python" in first[0] else "bash"
        target.write_text(f"#!/usr/bin/env bash\nexec {interpreter} {str(candidate)!r} \"$@\"\n")
        target.chmod(0o755)
    link_stub = local_bin / "maho-link"
    if link_stub.exists() or link_stub.is_symlink():
        link_stub.unlink()
    link_stub.write_text("#!/usr/bin/env bash\nprintf '%s\\n' '{\"status\":\"disabled\",\"reason\":\"memory-certification-isolation\"}'\n")
    link_stub.chmod(0o755)

    shim_dir = base / "shim"
    shim_dir.mkdir(exist_ok=True)
    systemd_shim = shim_dir / "systemd-run"
    systemd_shim.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%q ' \"$@\" >>\"${MAHO_CERT_APP_LOG}\"; printf '\\\\n' >>\"${MAHO_CERT_APP_LOG}\"\n"
        "while [ \"$#\" -gt 0 ] && [ \"$1\" != -- ]; do shift; done\n[ \"$#\" -gt 0 ] && shift\n[ \"$#\" -gt 0 ] || exit 2\nnohup \"$@\" >>\"${MAHO_CERT_APP_OUTPUT}\" 2>&1 </dev/null &\n"
    )
    systemd_shim.chmod(0o755)

    app_dir = data / "applications"
    app_dir.mkdir(parents=True, exist_ok=True)
    app_dir.joinpath("io.maho.MemoryProbe.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Maho Memory Probe\nExec=kitty --class maho-memory-probe sh -lc \"sleep 300\"\nTerminal=false\nCategories=Utility;\n"
    )

    env = os.environ.copy()
    env.update({
        "HOME": str(home),
        "XDG_RUNTIME_DIR": str(runtime),
        "XDG_STATE_HOME": str(state),
        "XDG_CACHE_HOME": str(cache),
        "XDG_CONFIG_HOME": str(config),
        "XDG_DATA_HOME": str(data),
        "MAHO_ROOT": str(root),
        "XDG_CURRENT_DESKTOP": "Hyprland",
        "XDG_SESSION_DESKTOP": "Hyprland",
        "XDG_SESSION_TYPE": "wayland",
        "QT_QPA_PLATFORM": "wayland",
        "GDK_BACKEND": "wayland",
        "PATH": f"{shim_dir}:{local_bin}:{os.environ.get('PATH','/usr/bin')}",
        "MAHO_CERT_APP_LOG": str(base / "app-helper.argv"),
        "MAHO_CERT_APP_OUTPUT": str(base / "logs/app-helper.log"),
    })
    return env


def wait_for(predicate, timeout: float, interval: float = 0.1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def hypr_json(env: dict[str, str], what: str) -> Any:
    result = run(["hyprctl", "-j", what], env=env, timeout=4)
    if result.returncode != 0:
        return {"error": result.stderr.strip() or result.stdout.strip(), "returncode": result.returncode}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"raw": result.stdout}


def guardian_status(root: Path, env: dict[str, str]) -> Any:
    result = run([str(root / "bin/maho-guard"), "world-status", "--json"], env=env, timeout=10)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def adaptive_status(root: Path, env: dict[str, str]) -> Any:
    result = run([str(root / "bin/maho-adaptive"), "status", "--json"], env=env, timeout=10)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def core_alive(procs: dict[str, subprocess.Popen[str]]) -> dict[str, bool]:
    return {name: procs.get(name) is not None and procs[name].poll() is None for name in CORE}


def responsiveness(env: dict[str, str]) -> dict[str, Any]:
    times: list[float] = []
    failures: list[str] = []
    for _ in range(5):
        start = time.monotonic()
        result = run(["hyprctl", "-j", "monitors"], env=env, timeout=2)
        times.append((time.monotonic() - start) * 1000)
        if result.returncode != 0:
            failures.append(result.stderr.strip())
    return {"samples_ms": [round(v, 2) for v in times], "max_ms": round(max(times), 2), "failures": failures}


def pressure_worker_code() -> str:
    return r'''import json,pathlib,signal,sys,time
budget=int(sys.argv[1]); out=pathlib.Path(sys.argv[2]); chunks=[]; allocated=0; step=32*1024*1024
def write(status): out.write_text(json.dumps({'status':status,'allocated_bytes':allocated,'budget_bytes':budget}))
def stop(*_): write('released'); raise SystemExit(0)
signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
while allocated < budget:
    size=min(step,budget-allocated); block=bytearray(size)
    for i in range(0,len(block),4096): block[i]=1
    chunks.append(block); allocated += size; write('allocating'); time.sleep(.12)
write('held')
while True: time.sleep(1)
'''


def dev_indexer_code() -> str:
    return r'''import pathlib,sys,time
root=pathlib.Path(sys.argv[1]); blobs=[]
for p in root.rglob('*'):
    if p.is_file() and p.stat().st_size < 2_000_000:
        try: blobs.append(p.read_bytes())
        except OSError: pass
pad=bytearray(256*1024*1024)
for i in range(0,len(pad),4096): pad[i]=1
print('maho-dev-indexer ready',len(blobs),sum(map(len,blobs)),flush=True)
time.sleep(300)
'''


def guardian_brief(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"state": "invalid"}
    reliability = payload.get("reliability") if isinstance(payload.get("reliability"), dict) else {}
    world = payload.get("world_state") if isinstance(payload.get("world_state"), dict) else {}
    guardian = world.get("guardian") if isinstance(world.get("guardian"), dict) else {}
    severity = guardian.get("severity") if isinstance(guardian.get("severity"), dict) else {}
    trust = guardian.get("trust") if isinstance(guardian.get("trust"), dict) else {}
    self_health = guardian.get("self_health") if isinstance(guardian.get("self_health"), dict) else {}
    return {"reliability_state": reliability.get("state"), "reliability_counts": reliability.get("counts", {}), "severity_level": severity.get("level"), "trust": trust.get("state"), "self_health": self_health.get("state"), "errors": payload.get("errors", [])}


def adaptive_brief(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"state": "invalid"}
    actions = payload.get("actions") if isinstance(payload.get("actions"), dict) else {}
    situation = payload.get("situation") if isinstance(payload.get("situation"), dict) else {}
    guardian = situation.get("guardian") if isinstance(situation.get("guardian"), dict) else {}
    return {"mode": actions.get("mode"), "mutation_executed": actions.get("mutation_executed"), "blocked": payload.get("blocked"), "guardian": guardian, "active_posture": payload.get("active_posture", {})}


def inner(args: argparse.Namespace) -> int:
    profile = PROFILES[args.profile]
    root = Path(args.root).resolve()
    real_home = Path(args.real_home).resolve()
    base = Path(args.base)
    evidence = Path(args.evidence)
    logs = evidence / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    started = time.time()
    cg = cgroup_path()
    procs: dict[str, subprocess.Popen[str]] = {}
    workloads: list[subprocess.Popen[str]] = []
    summary: dict[str, Any] = {
        "version": 1, "profile": args.profile, "started_at": utc_now(), "root": str(root), "cgroup": str(cg),
        "memory_max": profile["memory_max"], "memory_high": profile["memory_high"],
        "exclusions": {
            "bluetooth_auto_connect": "simulated disabled to prevent host Bluetooth mutation",
            "adaptive_actuators": "shadow evaluator only; certified physical actuator path was already verified separately",
            "animated_wallpaper": "excluded because certification forbids intentional media playback; physical mpvpaper is measured separately",
            "application_systemd_ownership": "launch semantics use a cgroup-preserving systemd-run shim so the probe cannot escape the constrained environment",
        },
    }
    env = prepare_home(root, real_home, base)
    runtime = Path(env["XDG_RUNTIME_DIR"])
    host_runtime = Path(args.host_runtime)
    parent_socket = host_runtime / args.host_wayland
    runtime.joinpath("p").symlink_to(parent_socket)
    pipewire = host_runtime / "pipewire-0"
    if pipewire.exists():
        runtime.joinpath("pipewire-0").symlink_to(pipewire)
        summary["exclusions"]["pipewire"] = "host PipeWire socket linked for state observation only; no playback generated"
    hypr_conf = base / "hyprland.conf"
    hypr_conf.write_text(
        "monitor = ,1280x720@60,auto,1\n"
        "misc { disable_hyprland_logo = true; disable_splash_rendering = true }\n"
        "debug { disable_logs = false }\n"
        "xwayland { enabled = false }\n"
    )
    hypr_env = env.copy(); hypr_env["WAYLAND_DISPLAY"] = "p"; hypr_env.pop("HYPRLAND_INSTANCE_SIGNATURE", None); hypr_env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    try:
        procs["hyprland"] = start_logged("hyprland", ["Hyprland", "--config", str(hypr_conf)], hypr_env, logs)
        def ipc_ready() -> bool:
            roots = list(runtime.joinpath("hypr").glob("*/.socket.sock"))
            return bool(roots and roots[0].is_socket())
        if not wait_for(ipc_ready, 15):
            raise RuntimeError("nested Hyprland IPC did not become ready")
        socket_path = next(runtime.joinpath("hypr").glob("*/.socket.sock"))
        signature = socket_path.parent.name
        if not wait_for(lambda: bool(list(runtime.glob("wayland-*"))), 10):
            raise RuntimeError("nested Wayland socket did not appear")
        nested_display = sorted(p.name for p in runtime.glob("wayland-*") if p.is_socket())[0]
        env["HYPRLAND_INSTANCE_SIGNATURE"] = signature
        env["WAYLAND_DISPLAY"] = nested_display

        dbus_socket = runtime / "bus"
        procs["dbus"] = start_logged("dbus", ["dbus-daemon", "--session", "--nofork", f"--address=unix:path={dbus_socket}"], env, logs)
        if not wait_for(dbus_socket.exists, 5):
            raise RuntimeError("isolated session D-Bus did not start")
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_socket}"
        env["MAHO_CERT_DBUS_ADDRESS"] = env["DBUS_SESSION_BUS_ADDRESS"]

        portal_bins = {
            "portal-hyprland": "/usr/lib/xdg-desktop-portal-hyprland",
            "portal-gtk": "/usr/lib/xdg-desktop-portal-gtk",
            "portal": "/usr/lib/xdg-desktop-portal",
        }
        for name, binary in portal_bins.items():
            if Path(binary).is_file():
                procs[name] = start_logged(name, [binary], env, logs)
        time.sleep(1)

        procs["shell"] = start_logged("shell", ["quickshell", "-p", str(root / "config/quickshell/maho-shell/shell.qml")], env, logs)
        procs["dock"] = start_logged("dock", ["quickshell", "-p", str(root / "config/quickshell/maho-shell/dock-shell.qml")], env, logs)
        procs["notify"] = start_logged("notify", ["quickshell", "--no-duplicate", "-p", str(root / "config/quickshell/maho-notify/shell.qml")], env, logs)
        if shutil.which("wl-paste", path=env["PATH"]) and shutil.which("cliphist", path=env["PATH"]):
            procs["clipboard"] = start_logged("clipboard", [str(root / "bin/maho-clipboard-history"), "serve"], env, logs)

        procs["observe"] = start_logged("observe", ["bash", str(root / "bin/maho-observe"), "watch"], env, logs)
        procs["security"] = start_logged("security", [str(root / "bin/maho-security-monitor"), "watch"], env, logs)
        guardian_env = env.copy(); guardian_env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={host_runtime}/bus"; guardian_env["XDG_RUNTIME_DIR"] = str(host_runtime)
        procs["guardian"] = start_logged("guardian", [str(root / "bin/maho-guardian-watch"), "watch"], guardian_env, logs)
        procs["adaptive"] = start_logged("adaptive", [str(root / "bin/maho-adaptive"), "watch", "--interval", "2"], env, logs)

        if not wait_for(lambda: all(core_alive(procs).values()), 3):
            raise RuntimeError(f"core process startup failure: {core_alive(procs)}")
        time.sleep(8)
        alive_initial = core_alive(procs)
        layers = hypr_json(env, "layers")
        summary["startup_seconds"] = round(time.time() - started, 3)
        summary["core_alive_initial"] = alive_initial
        summary["layers"] = layers
        guardian_initial = guardian_status(root, guardian_env); atomic_json(evidence / "guardian-initial.json", guardian_initial)
        adaptive_initial = adaptive_status(root, env); atomic_json(evidence / "adaptive-initial.json", adaptive_initial)
        summary["guardian_initial"] = guardian_brief(guardian_initial)
        summary["adaptive_initial"] = adaptive_brief(adaptive_initial)
        idle = snapshot(cg, "idle", started); atomic_json(evidence / "idle.json", idle)

        helper_doctor = run([sys.executable, str(root / "lib/maho_app_model.py"), "doctor"], env=env, timeout=20)
        helper_launch = run([sys.executable, str(root / "lib/maho_app_model.py"), "launch-new", "io.maho.MemoryProbe.desktop"], env=env, timeout=20)
        summary["app_helper"] = {
            "doctor_rc": helper_doctor.returncode, "doctor": helper_doctor.stdout.strip(),
            "launch_rc": helper_launch.returncode, "launch_stderr": helper_launch.stderr.strip(),
            "shim_argv": (base / "app-helper.argv").read_text().strip() if (base / "app-helper.argv").exists() else "",
        }
        time.sleep(3)
        clients_after_helper = hypr_json(env, "clients")
        summary["app_helper"]["client_present"] = isinstance(clients_after_helper, list) and any("maho-memory-probe" in str(row).lower() for row in clients_after_helper)

        if args.profile == "8g":
            browser_env = env.copy(); browser_env["MAHO_MEMORY_CERTIFY"] = "1"
            brave = shutil.which("brave", path=env["PATH"])
            if brave:
                workloads.append(start_logged("browser", [brave, f"--user-data-dir={base / 'brave'}", "--no-first-run", "--no-default-browser-check", "--disable-sync", "--disable-background-networking", "--disable-component-update", "--ozone-platform=wayland", "about:blank"], browser_env, logs))
            workloads.append(start_logged("dev-indexer", [sys.executable, "-c", dev_indexer_code(), str(root), "maho-dev-indexer"], env, logs))
            time.sleep(8)
        loaded = snapshot(cg, "loaded", started); atomic_json(evidence / "loaded.json", loaded)

        pressure_file = base / "pressure.json"
        baseline_total = int(loaded.get("memory_current") or 0) + int(loaded.get("memory_swap_current") or 0)
        target_total = int(profile["memory_max"] * profile["pressure_target"])
        pressure_budget = max(0, target_total - baseline_total)
        summary["pressure_budget_mib"] = round(pressure_budget / MIB, 2)
        pre_events = dict(loaded.get("memory_events", {}))
        pre_psi_total = int(((loaded.get("memory_pressure") or {}).get("some") or {}).get("total", 0))
        pressure = start_logged("pressure", [sys.executable, "-c", pressure_worker_code(), str(pressure_budget), str(pressure_file), "maho-pressure-worker"], env, logs)
        workloads.append(pressure)
        onset_captured = False
        peak_reached = False
        deadline = time.time() + 90
        while time.time() < deadline:
            if pressure.poll() is not None:
                break
            current = read_int(cg / "memory.current") or 0
            events = read_kv(cg / "memory.events")
            psi_total = int((read_pressure(cg / "memory.pressure").get("some") or {}).get("total", 0))
            pressure_observed = current >= int(profile["memory_high"]) or int(events.get("high", 0)) > int(pre_events.get("high", 0)) or psi_total > pre_psi_total
            if not onset_captured and pressure_observed:
                atomic_json(evidence / "pressure-onset.json", snapshot(cg, "pressure-onset", started)); onset_captured = True
            try:
                progress = json.loads(pressure_file.read_text())
            except (OSError, json.JSONDecodeError):
                progress = {}
            if progress.get("status") == "held":
                peak_reached = True
                break
            time.sleep(.25)
        if not onset_captured:
            atomic_json(evidence / "pressure-onset.json", snapshot(cg, "pressure-onset", started))
        time.sleep(8)
        peak = snapshot(cg, "peak", started); atomic_json(evidence / "peak.json", peak)
        summary["peak_responsiveness"] = responsiveness(env)
        summary["core_alive_peak"] = core_alive(procs)
        pressure_events = dict(peak.get("memory_events", {}))
        stop_proc(pressure)
        time.sleep(12)
        recovery = snapshot(cg, "recovery", started); atomic_json(evidence / "recovery.json", recovery)
        summary["core_alive_recovery"] = core_alive(procs)
        summary["recovery_responsiveness"] = responsiveness(env)
        guardian_recovery = guardian_status(root, guardian_env); atomic_json(evidence / "guardian-recovery.json", guardian_recovery)
        adaptive_recovery = adaptive_status(root, env); atomic_json(evidence / "adaptive-recovery.json", adaptive_recovery)
        summary["guardian_recovery"] = guardian_brief(guardian_recovery)
        summary["adaptive_recovery"] = adaptive_brief(adaptive_recovery)

        loaded_current = int(loaded.get("memory_current") or 0)
        recovery_current = int(recovery.get("memory_current") or 0)
        recovery_bound = max(int(loaded_current * 1.30), loaded_current + 192 * MIB)
        pass_conditions = {
            "core_started": all(alive_initial.values()),
            "core_survived_peak": all(summary["core_alive_peak"].values()),
            "core_survived_recovery": all(summary["core_alive_recovery"].values()),
            "app_helper": helper_doctor.returncode == 0 and helper_launch.returncode == 0 and bool(summary["app_helper"]["client_present"]),
            "pressure_target_reached": peak_reached,
            "no_cgroup_oom": int(pressure_events.get("oom", 0)) == 0 and int(pressure_events.get("oom_kill", 0)) == 0,
            "responsive_at_peak": not summary["peak_responsiveness"]["failures"] and summary["peak_responsiveness"]["max_ms"] < 1000,
            "memory_recovered": recovery_current <= recovery_bound,
        }
        summary["pass_conditions"] = pass_conditions
        summary["pass"] = all(pass_conditions.values())
        summary["idle_target_mib"] = profile["idle_target_mib"]
        summary["idle_pss_mib"] = round(int(idle.get("total_pss_kib", 0)) / 1024, 2)
        summary["loaded_memory_mib"] = round(int(loaded.get("memory_current") or 0) / MIB, 2)
        summary["peak_memory_mib"] = round(int(peak.get("memory_current") or 0) / MIB, 2)
        summary["recovery_memory_mib"] = round(recovery_current / MIB, 2)
        summary["ended_at"] = utc_now()
        summary["duration_s"] = round(time.time() - started, 3)
        oomd = run(["journalctl", "-b", "-u", "systemd-oomd", "--since", f"@{int(started)}", "--no-pager", "-o", "short-iso"], env=guardian_env, timeout=10)
        evidence.joinpath("oomd.log").write_text(oomd.stdout + oomd.stderr)
        atomic_json(evidence / "summary.json", summary)
        return 0 if summary["pass"] else 1
    except Exception as exc:
        summary["pass"] = False
        summary["error"] = f"{type(exc).__name__}: {exc}"
        summary["ended_at"] = utc_now()
        atomic_json(evidence / "summary.json", summary)
        return 1
    finally:
        for proc in reversed(workloads):
            stop_proc(proc)
        for proc in reversed(list(procs.values())):
            stop_proc(proc)
        for proc in list(procs.values()):
            handle = getattr(proc, "_maho_log_handle", None)
            if handle:
                try: handle.close()
                except OSError: pass


def outer(args: argparse.Namespace) -> int:
    profile = PROFILES[args.profile]
    root = Path(__file__).resolve().parent.parent
    real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    runtime = Path(f"/run/user/{os.getuid()}")
    user_env, manager = manager_environment(runtime)
    host_wayland = manager.get("WAYLAND_DISPLAY") or os.environ.get("WAYLAND_DISPLAY", "")
    if not host_wayland or not runtime.joinpath(host_wayland).exists():
        raise SystemExit("maho-memory-certify: live Wayland socket is unavailable")
    for command in ("Hyprland", "quickshell", "dbus-daemon", "systemd-run", "hyprctl"):
        if shutil.which(command) is None:
            raise SystemExit(f"maho-memory-certify: required command unavailable: {command}")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence = Path(args.evidence).expanduser() if args.evidence else real_home / f".local/state/maho/certification/daily-driver-low-memory/{stamp}-{args.profile}"
    evidence.mkdir(parents=True, exist_ok=False)
    base = Path(f"/tmp/mc{args.profile[0]}-{os.getpid()}")
    if base.exists(): shutil.rmtree(base)
    base.mkdir(mode=0o700)
    unit = f"maho-memcert-{args.profile}-{os.getpid()}.service"
    command = [
        "systemd-run", "--user", f"--unit={unit}", "--quiet",
        f"--property=MemoryMax={profile['memory_max']}", f"--property=MemoryHigh={profile['memory_high']}",
        "--property=MemoryAccounting=yes", "--property=CPUAccounting=yes", "--property=TasksMax=4096", "--property=OOMPolicy=continue",
        sys.executable, str(Path(__file__).resolve()), "_inner",
        "--profile", args.profile, "--root", str(root), "--real-home", str(real_home), "--base", str(base),
        "--evidence", str(evidence), "--host-runtime", str(runtime), "--host-wayland", host_wayland,
    ]
    started = time.time()
    launch = run(command, env=user_env, timeout=20)
    if launch.returncode != 0:
        raise SystemExit(f"maho-memory-certify: failed to start constrained service: {launch.stderr.strip()}")
    summary_path = evidence / "summary.json"
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        if summary_path.exists():
            break
        state = run(["systemctl", "--user", "show", unit, "--property=ActiveState", "--property=SubState", "--property=Result", "--value"], env=user_env, timeout=5)
        if state.returncode != 0:
            break
        if "inactive" in state.stdout or "failed" in state.stdout:
            time.sleep(.5)
            if summary_path.exists(): break
        time.sleep(1)
    if not summary_path.exists():
        run(["systemctl", "--user", "stop", unit], env=user_env, timeout=10)
        atomic_json(evidence / "summary.json", {"version": 1, "profile": args.profile, "pass": False, "error": "certification timed out or service exited before writing evidence", "duration_s": time.time()-started})
    journal = run(["journalctl", "--user", "-u", unit, "--since", f"@{int(started)}", "--no-pager", "-o", "short-iso"], env=user_env, timeout=15)
    evidence.joinpath("service.log").write_text(journal.stdout + journal.stderr)
    show = run(["systemctl", "--user", "show", unit], env=user_env, timeout=8)
    evidence.joinpath("service-properties.txt").write_text(show.stdout + show.stderr)
    run(["systemctl", "--user", "stop", unit], env=user_env, timeout=10)
    run(["systemctl", "--user", "reset-failed", unit], env=user_env, timeout=10)
    summary = json.loads(summary_path.read_text())
    summary["evidence_dir"] = str(evidence)
    atomic_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    try: shutil.rmtree(base)
    except OSError: pass
    return 0 if summary.get("pass") is True else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maho-memory-certify", description="Run a real nested Maho desktop under a bounded cgroup without limiting the physical desktop")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("profile", choices=tuple(PROFILES))
    run_parser.add_argument("--evidence")
    run_parser.add_argument("--timeout", type=int, default=420)
    inner_parser = sub.add_parser("_inner", help=argparse.SUPPRESS)
    inner_parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    inner_parser.add_argument("--root", required=True)
    inner_parser.add_argument("--real-home", required=True)
    inner_parser.add_argument("--base", required=True)
    inner_parser.add_argument("--evidence", required=True)
    inner_parser.add_argument("--host-runtime", required=True)
    inner_parser.add_argument("--host-wayland", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return inner(args) if args.command == "_inner" else outer(args)


if __name__ == "__main__":
    raise SystemExit(main())
