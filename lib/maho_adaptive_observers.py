#!/usr/bin/env python3
"""Read-only session and workload observation for adaptive policy.

Collection is best-effort and capability-scoped. Classification deliberately
requires multiple independent signals; mere process existence never implies
important foreground work.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Iterable, Mapping

UNKNOWN = "unknown"
GAME_LAUNCHERS = {"steam", "steamwebhelper", "lutris", "heroic"}
GAME_HINTS = {"gamescope", "wine-preloader", "wine64-preloader", "pressure-vessel"}
GAME_PATH_HINTS = ("/steamapps/common/", "/games/", "/game/", "/wineprefixes/", "/heroic/", "/lutris/")
COMPILERS = {"gcc", "g++", "cc", "c++", "clang", "clang++", "rustc", "go"}
BUILD_TOOLS = {"make", "ninja", "cmake", "meson", "cargo", "npm", "pnpm", "yarn"}
RENDER_TOOLS = {"blender", "ffmpeg", "handbrakecli", "kdenlive_render"}
MEDIA_TOOLS = {"mpv", "vlc", "celluloid", "smplayer"}
MAX_GPU_FDS_PER_PROCESS = 256


@dataclass(frozen=True)
class ProcessEvidence:
    pid: int
    ppid: int
    command: str
    executable: str
    age_seconds: float
    cpu_seconds: float
    foreground: bool = False
    gpu: bool = False


@dataclass(frozen=True)
class SessionEvidence:
    locked: bool | str = UNKNOWN
    lock_dwell_seconds: float | str = UNKNOWN
    idle_seconds: float | str = UNKNOWN
    recent_input_seconds: float | str = UNKNOWN
    inhibitors: tuple[str, ...] = ()


@dataclass(frozen=True)
class WindowEvidence:
    fullscreen: bool | str = UNKNOWN
    active_pid: int | None = None
    title: str = ""
    window_class: str = ""


@dataclass(frozen=True)
class WorkloadClassification:
    fullscreen: bool | str
    probable_gaming: bool | str
    probable_compile: bool | str
    probable_rendering: bool | str
    probable_media: bool | str
    interactive: bool | str
    high_background_cpu: bool | str
    gpu_activity: bool | str
    confidence: float | str
    evidence: tuple[str, ...]
    respected_background_job: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _basename(value: str) -> str:
    return Path(value).name.lower()


def process_uses_gpu(process_root: Path) -> bool:
    """Observe a process's DRM handles without opening any device."""
    descriptors = process_root / "fd"
    try:
        entries = sorted(descriptors.iterdir(), key=lambda item: item.name)[:MAX_GPU_FDS_PER_PROCESS]
    except OSError:
        return False
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("/dev/dri/") and Path(target).name.startswith(("renderD", "card")):
            return True
    return False


def _tree_related(processes: Iterable[ProcessEvidence], roots: set[int]) -> set[int]:
    rows = list(processes)
    related = set(roots)
    changed = True
    while changed:
        changed = False
        for process in rows:
            if process.ppid in related and process.pid not in related:
                related.add(process.pid)
                changed = True
    return related


def classify_workload(
    processes: Iterable[ProcessEvidence],
    window: WindowEvidence,
    session: SessionEvidence,
    *,
    audio_active: bool | str = UNKNOWN,
) -> WorkloadClassification:
    rows = tuple(processes)
    by_pid = {row.pid: row for row in rows}
    active = by_pid.get(window.active_pid or -1)
    names = {_basename(row.executable or row.command) for row in rows}
    evidence: list[str] = []

    # Gaming: launcher existence is explicitly insufficient. Require a probable
    # game/runtime process PLUS foreground/fullscreen or GPU/user interaction.
    launcher_only = bool(names & GAME_LAUNCHERS)
    game_runtime = [
        row for row in rows
        if (
            _basename(row.executable or row.command) in GAME_HINTS
            or (row.gpu and any(token in row.executable.lower() for token in GAME_PATH_HINTS))
        )
        and _basename(row.executable or row.command) not in GAME_LAUNCHERS
        and row.age_seconds >= 10
    ]
    active_game = bool(active and active in game_runtime)
    fullscreen = window.fullscreen
    recent_input = isinstance(session.recent_input_seconds, (int, float)) and session.recent_input_seconds <= 15
    gaming_signals = sum((bool(game_runtime), fullscreen is True, active_game, recent_input, any(row.gpu for row in game_runtime)))
    probable_gaming: bool | str = gaming_signals >= 3 and (fullscreen is True or recent_input)
    if probable_gaming:
        evidence.append("gaming:multi-signal")
    elif launcher_only:
        evidence.append("gaming:launcher-only-insufficient")

    # Compile/build: a compiler process must be sustained and structurally
    # related to a build tool, or itself consume meaningful CPU over time.
    build_roots = {row.pid for row in rows if _basename(row.executable or row.command) in BUILD_TOOLS and row.age_seconds >= 8}
    build_tree = _tree_related(rows, build_roots)
    compilers = [row for row in rows if _basename(row.executable or row.command) in COMPILERS]
    meaningful_compilers = [
        row for row in compilers
        if row.age_seconds >= 8 and (row.pid in build_tree or row.cpu_seconds >= 2.0)
    ]
    probable_compile: bool | str = bool(meaningful_compilers and (build_roots or sum(r.cpu_seconds for r in meaningful_compilers) >= 4.0))
    if probable_compile:
        evidence.append("compile:sustained-process-tree")
    elif compilers:
        evidence.append("compile:process-exists-insufficient")

    renderers = [
        row for row in rows
        if _basename(row.executable or row.command) in RENDER_TOOLS
        and row.age_seconds >= 15
        and row.cpu_seconds >= 3
    ]
    probable_rendering: bool | str = bool(renderers)
    if probable_rendering:
        evidence.append("render:sustained-work")

    media_process = bool(names & MEDIA_TOOLS) or (
        active is not None and any(token in (window.window_class + " " + window.title).lower() for token in ("youtube", "video", "player"))
    )
    probable_media: bool | str = bool(media_process and (audio_active is True or fullscreen is True))
    if probable_media:
        evidence.append("media:playback-context")

    # Fullscreen media is not a game without the independent gaming signals.
    if probable_media and gaming_signals < 3:
        probable_gaming = False

    active_foreground = active is not None and (active.foreground or window.active_pid == active.pid)
    interactive: bool | str = bool(active_foreground and recent_input)
    if interactive:
        evidence.append("foreground:recent-input")

    background_cpu = sum(
        row.cpu_seconds / max(row.age_seconds, 1.0)
        for row in rows if not row.foreground and row.age_seconds >= 20
    )
    high_background_cpu: bool | str = background_cpu >= 0.75
    if high_background_cpu:
        evidence.append("background:sustained-cpu")

    gpu_activity = any(row.gpu for row in rows)
    if gpu_activity:
        evidence.append("gpu:process-evidence")

    respected = bool(probable_compile or probable_rendering)
    confidence_signals = 0
    if probable_gaming:
        confidence_signals = max(confidence_signals, gaming_signals)
    if probable_compile:
        confidence_signals = max(confidence_signals, 4)
    if probable_rendering:
        confidence_signals = max(confidence_signals, 4)
    if probable_media:
        confidence_signals = max(confidence_signals, 3)
    if interactive:
        confidence_signals = max(confidence_signals, 3)
    confidence: float | str = min(1.0, 0.2 + confidence_signals * 0.18) if confidence_signals else 0.35 if rows else UNKNOWN

    return WorkloadClassification(
        fullscreen,
        probable_gaming,
        probable_compile,
        probable_rendering,
        probable_media,
        interactive,
        high_background_cpu,
        gpu_activity,
        confidence,
        tuple(sorted(set(evidence))),
        respected,
    )


def _read(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace").strip()
    except (OSError, UnicodeError):
        return None


def collect_processes(proc_root: Path = Path("/proc")) -> tuple[ProcessEvidence, ...]:
    """Best-effort /proc snapshot; no signals are sent and no process is opened writable."""
    uptime_raw = _read(proc_root / "uptime") or ""
    try:
        uptime = float(uptime_raw.split()[0])
    except (ValueError, IndexError):
        uptime = 0.0
    try:
        ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
    except (ValueError, KeyError):
        ticks = 100
    rows: list[ProcessEvidence] = []
    for entry in proc_root.iterdir() if proc_root.is_dir() else ():
        if not entry.name.isdigit():
            continue
        stat = _read(entry / "stat")
        if not stat:
            continue
        # comm can contain spaces and parentheses, so parse from final ')'.
        close = stat.rfind(")")
        if close < 0:
            continue
        fields = stat[close + 2:].split()
        try:
            ppid = int(fields[1])
            utime = int(fields[11]); stime = int(fields[12]); start_ticks = int(fields[19])
        except (ValueError, IndexError):
            continue
        cmdline = _read(entry / "cmdline") or ""
        command = cmdline.replace("\x00", " ").strip()
        comm = (_read(entry / "comm") or "").strip()
        executable = ""
        try:
            executable = os.readlink(entry / "exe")
        except OSError:
            executable = comm
        age = max(0.0, uptime - start_ticks / ticks) if uptime else 0.0
        cpu = max(0.0, (utime + stime) / ticks)
        rows.append(ProcessEvidence(
            int(entry.name), ppid, command or comm, executable, age, cpu,
            gpu=process_uses_gpu(entry),
        ))
    return tuple(rows)


def _run_json(command: list[str], timeout: float = 1.5) -> Mapping[str, Any]:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return {}
        value = json.loads(result.stdout)
        return value if isinstance(value, Mapping) else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}


def collect_window() -> WindowEvidence:
    active = _run_json(["hyprctl", "activewindow", "-j"])
    if not active:
        return WindowEvidence()
    pid = active.get("pid") if isinstance(active.get("pid"), int) else None
    fullscreen_raw = active.get("fullscreen")
    fullscreen = bool(fullscreen_raw) if isinstance(fullscreen_raw, (bool, int)) else UNKNOWN
    return WindowEvidence(
        fullscreen=fullscreen,
        active_pid=pid,
        title=str(active.get("title") or ""),
        window_class=str(active.get("class") or ""),
    )


def _session_properties(command: list[str]) -> Mapping[str, str]:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=1.5)
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def _loginctl_properties() -> Mapping[str, str]:
    # User services have no session ID. Resolve logind's sessions for this UID
    # rather than inheriting a possibly stale shell/session environment.
    user = _session_properties(["loginctl", "show-user", str(os.getuid()), "-p", "Sessions"])
    sessions = user.get("Sessions", "").split()
    if not sessions or len(sessions) > 32 or any(not re.fullmatch(r"[a-zA-Z0-9_-]+", x) for x in sessions):
        return {}
    graphical = []
    for session in sessions:
        values = _session_properties([
            "loginctl", "show-session", session,
            "-p", "User", "-p", "Class", "-p", "Type", "-p", "Active", "-p", "Remote",
            "-p", "LockedHint", "-p", "IdleHint", "-p", "IdleSinceHintMonotonic",
        ])
        if values.get("User") != str(os.getuid()) or values.get("Class") not in {"user", "manager", "background"}:
            return {}
        if values.get("Class") == "user" and values.get("Type") in {"wayland", "x11"}:
            graphical.append(values)
    # Multiple desktops are ambiguous even if only one currently has the seat.
    if len(graphical) != 1 or graphical[0].get("Active") != "yes" or graphical[0].get("Remote") != "no":
        return {}
    return graphical[0]


def _session_inhibitors() -> tuple[str, ...]:
    value = _run_json([
        "busctl", "--system", "--json=short", "call", "org.freedesktop.login1",
        "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "ListInhibitors",
    ])
    data = value.get("data")
    if value.get("type") != "a(ssssuu)" or not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], list):
        return ("logind-inhibitors-unknown",)
    blockers = []
    for row in data[0]:
        if not isinstance(row, list) or len(row) != 6 or any(not isinstance(x, str) for x in row[:4]):
            return ("logind-inhibitors-unknown",)
        what, who, why, mode = row[:4]
        if "idle" in what.split(":") or (mode == "block" and "shutdown" in what.split(":")):
            blockers.append(f"{what}:{who}:{why}:{mode}")
    return tuple(blockers)


def _wayland_session_evidence(component: str, function: str) -> Mapping[str, Any]:
    root = Path(os.environ.get("MAHO_ROOT") or Path(__file__).resolve().parents[1])
    config = root / "config/quickshell" / component / "shell.qml"
    if component == "maho-shell":
        configured = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "quickshell/maho-shell/shell.qml"
        # IPC uses the launch spelling of the config path. Keep that spelling,
        # but only if it resolves to this exact installed source.
        try:
            if configured.resolve(strict=True) != config.resolve(strict=True):
                return {}
        except OSError:
            return {}
        config = configured
    return _run_json([
        "quickshell", "ipc", "-p", str(config),
        "call", "sessionEvidence", function,
    ])


def collect_session(*, previous_lock_started_monotonic: float | None = None) -> tuple[SessionEvidence, float | None]:
    values = _loginctl_properties()
    locked: bool | str = UNKNOWN
    if values.get("LockedHint") in {"yes", "no"}:
        locked = values["LockedHint"] == "yes"
    # The native lock reports the compositor's secure acknowledgement, rather
    # than treating locker process existence or a launch request as a lock.
    if values:
        proof = _wayland_session_evidence("maho-lock", "lockProof")
        if proof.get("secure") is True and proof.get("locked") is True:
            locked = True
    now = time.monotonic()
    lock_started = previous_lock_started_monotonic if locked != UNKNOWN else None
    if locked is True and lock_started is None:
        lock_started = now
    elif locked is False:
        lock_started = None
    dwell: float | str = max(0.0, now - lock_started) if locked is True and lock_started is not None else 0.0 if locked is False else UNKNOWN

    idle_seconds: float | str = UNKNOWN
    recent_input: float | str = UNKNOWN
    raw_since = values.get("IdleSinceHintMonotonic")
    try:
        since_micro = int(raw_since or "0")
        if values.get("IdleHint") == "yes" and 0 < since_micro <= now * 1_000_000:
            idle_seconds = now - since_micro / 1_000_000.0
            recent_input = idle_seconds
        elif values.get("IdleHint") == "no":
            idle_seconds = 0.0
            recent_input = 0.0
    except ValueError:
        pass
    compositor_inhibitors: tuple[str, ...] = ()
    if values:
        compositor = _wayland_session_evidence("maho-shell", "idle")
        duration = compositor.get("idle_seconds")
        if (
            compositor.get("observed") is True and compositor.get("respects_inhibitors") is True
            and isinstance(compositor.get("idle"), bool)
            and isinstance(duration, (int, float)) and not isinstance(duration, bool) and 0 <= duration < 365 * 86400
            and (compositor["idle"] is True or duration == 0)
        ):
            idle_seconds = float(duration)
            recent_input = idle_seconds
            if compositor.get("idle_inhibited") is True:
                compositor_inhibitors = ("wayland-idle-inhibitor",)
    return SessionEvidence(locked, dwell, idle_seconds, recent_input, _session_inhibitors() + compositor_inhibitors), lock_started


def observe_live() -> dict[str, Any]:
    session, _ = collect_session()
    window = collect_window()
    processes = collect_processes()
    active_pid = window.active_pid
    if active_pid is not None:
        processes = tuple(
            ProcessEvidence(p.pid, p.ppid, p.command, p.executable, p.age_seconds, p.cpu_seconds, p.pid == active_pid, p.gpu)
            for p in processes
        )
    workload = classify_workload(processes, window, session)
    return {"session": asdict(session), "workload": workload.as_dict()}


def main() -> None:
    parser = argparse.ArgumentParser(prog="maho_adaptive_observers.py")
    parser.add_argument("command", choices=("session", "workload", "all"), nargs="?", default="all")
    args = parser.parse_args()
    result = observe_live()
    if args.command == "session":
        result = result["session"]
    elif args.command == "workload":
        result = result["workload"]
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
