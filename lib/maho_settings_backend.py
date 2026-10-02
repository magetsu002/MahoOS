#!/usr/bin/env python3
"""Bounded system adapters for the native Maho Settings application.

Maho Settings is a presenter/requester. Hyprland, WirePlumber, power-profiles,
Maho theme/wallpaper helpers, the kernel and MahoSystem remain authoritative.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from typing import Any, Iterable

ROOT = Path(os.environ.get("MAHO_ROOT", Path(__file__).resolve().parents[1])).resolve()
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
CACHE_HOME = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
SETTINGS_CONFIG = CONFIG_HOME / "maho" / "settings"
SETTINGS_STATE = STATE_HOME / "maho" / "settings"
TX_DIR = SETTINGS_STATE / "display-transactions"
INTENT_DEFAULTS = ROOT / "config" / "intent.json"
INTENT_USER = CONFIG_HOME / "maho" / "intent.json"
DISPLAY_CONFIG = SETTINGS_CONFIG / "displays.json"
INPUT_CONFIG = SETTINGS_CONFIG / "input.json"
DISPLAY_ROLLBACK_SECONDS = 15

SEARCH_TARGETS = (
    ("appearance", "Appearance", "Theme", "light dark automatic theme appearance palette wallpaper color"),
    ("appearance", "Appearance", "Reduced Motion", "motion animation animations accessibility reduce reduced"),
    ("appearance", "Appearance", "Reduced Transparency", "transparency blur glass accessibility reduce reduced"),
    ("displays", "Displays", "Resolution", "resolution monitor screen display pixels"),
    ("displays", "Displays", "Refresh Rate", "refresh hz hertz monitor display screen"),
    ("displays", "Displays", "Scale", "scale scaling dpi display monitor"),
    ("displays", "Displays", "Orientation", "orientation rotate rotation portrait landscape display"),
    ("sound", "Sound", "Output", "speaker speakers headphones output sink audio sound"),
    ("sound", "Sound", "Input", "mic microphone input source audio sound"),
    ("sound", "Sound", "Volume", "volume mute audio sound"),
    ("input", "Keyboard & Pointer", "Keyboard", "keyboard repeat rate delay keys"),
    ("input", "Keyboard & Pointer", "Mouse", "mouse pointer sensitivity acceleration"),
    ("input", "Keyboard & Pointer", "Touchpad", "touchpad trackpad tap natural scroll typing"),
    ("power", "Power", "Battery", "battery charge health power energy"),
    ("power", "Power", "Power Mode", "performance balanced saver profile power"),
    ("system", "System", "About", "about version kernel hardware session system mahoos"),
    ("network", "Network & Bluetooth", "Advanced Settings", "network wifi ethernet bluetooth connectivity"),
    ("notifications", "Notifications", "Preferences", "notifications alerts dnd quiet"),
    ("applications", "Applications", "Defaults", "applications apps defaults handlers"),
    ("users", "Users", "Accounts", "users accounts login"),
    ("region", "Region & Time", "Locale & Time", "region language locale time timezone"),
    ("accessibility", "Accessibility", "Accessibility", "accessibility contrast motion transparency"),
    ("updates", "System", "Updates", "updates update packages maintenance"),
    ("recovery", "System", "Recovery", "recovery restore rollback generation rescue"),
    ("guardian", "System", "Guardian", "guardian trust security incidents"),
    ("storage", "System", "Storage", "storage disk space filesystem"),
)

DEFERRED_ROUTES = {
    "network", "notifications", "applications", "users", "region",
    "accessibility", "updates", "recovery", "guardian", "storage",
}


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def run(args: Iterable[str], *, timeout: float = 6.0, input_text: str | None = None) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            list(args),
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "operation timed out"
    except (OSError, ValueError) as exc:
        return 127, "", str(exc)


def atomic_json(path: Path, payload: Any, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def intent_values(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return {}
    values = payload.get("values")
    return values if isinstance(values, dict) else {}


def intent_get(key: str, fallback: Any = None) -> Any:
    user = intent_values(INTENT_USER)
    if key in user:
        return user[key]
    return intent_values(INTENT_DEFAULTS).get(key, fallback)


def intent_set(key: str, value: Any) -> None:
    allowed = {
        "appearance.theme.mode",
        "appearance.reduced_motion",
        "appearance.reduced_transparency",
    }
    if key not in allowed:
        raise ValueError("unsupported settings intent")
    payload = read_json(INTENT_USER)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        payload = {"version": 1, "values": {}}
    values = payload.setdefault("values", {})
    if not isinstance(values, dict):
        raise ValueError("invalid user intent registry")
    values[key] = value
    atomic_json(INTENT_USER, payload)


def root_command(name: str) -> str | None:
    local = ROOT / "bin" / name
    if local.is_file():
        return str(local)
    return shutil.which(name)


def hypr_prefix() -> tuple[list[str] | None, str]:
    executable = shutil.which("hyprctl")
    if not executable:
        return None, "Hyprland control is unavailable."
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return [executable], ""
    code, out, err = run([executable, "instances", "-j"], timeout=3.0)
    if code != 0:
        return None, err or out or "No Hyprland session is available."
    try:
        instances = json.loads(out)
    except json.JSONDecodeError:
        return None, "Hyprland returned an invalid instance list."
    if not isinstance(instances, list) or len(instances) != 1:
        return None, "A unique Hyprland session could not be identified."
    instance = instances[0].get("instance") if isinstance(instances[0], dict) else None
    if not isinstance(instance, str) or not instance:
        return None, "Hyprland instance identity is missing."
    return [executable, "-i", instance], ""


def hypr(args: Iterable[str], *, timeout: float = 5.0) -> tuple[int, str, str]:
    prefix, error = hypr_prefix()
    if prefix is None:
        return 127, "", error
    return run([*prefix, *args], timeout=timeout)


def hypr_json(args: Iterable[str]) -> tuple[Any | None, str]:
    code, out, err = hypr(args)
    if code != 0:
        return None, err or out or "Hyprland request failed."
    try:
        return json.loads(out), ""
    except json.JSONDecodeError:
        return None, "Hyprland returned invalid JSON."


def hypr_option(name: str, fallback: Any = None) -> Any:
    payload, _ = hypr_json(["getoption", name, "-j"])
    if not isinstance(payload, dict):
        return fallback
    if "int" in payload:
        return payload["int"]
    if "float" in payload:
        return payload["float"]
    if "str" in payload:
        return payload["str"]
    return fallback


def wallpaper_state() -> dict[str, Any]:
    command = root_command("maho-wallpaper")
    if not command:
        return {}
    code, out, _ = run([command, "current"], timeout=4.0)
    if code != 0:
        return {}
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def snapshot_appearance() -> dict[str, Any]:
    palette = read_json(CACHE_HOME / "maho" / "theme" / "active.json")
    wallpaper = wallpaper_state()
    hypr_available = hypr_prefix()[0] is not None
    return {
        "available": True,
        "mode": intent_get("appearance.theme.mode", "dark"),
        "automaticSupported": False,
        "reducedMotion": bool(intent_get("appearance.reduced_motion", False)),
        "reducedTransparency": bool(intent_get("appearance.reduced_transparency", False)),
        "runtimeHooksAvailable": hypr_available,
        "wallpaper": wallpaper,
        "palette": palette if isinstance(palette, dict) else {},
        "themeBackendAvailable": root_command("maho-theme") is not None,
        "error": "",
    }


def set_appearance_mode(mode: str) -> dict[str, Any]:
    if mode not in {"dark", "light"}:
        return {"ok": False, "error": "Automatic appearance is not supported by the current theme backend."}
    wall = wallpaper_state()
    path = wall.get("path")
    theme = root_command("maho-theme")
    if not theme or not isinstance(path, str) or not Path(path).is_file():
        return {"ok": False, "error": "The current wallpaper/theme backend is unavailable."}
    code, out, err = run([theme, "apply", path, mode], timeout=25.0)
    if code != 0:
        return {"ok": False, "error": err or out or "Theme application failed."}
    intent_set("appearance.theme.mode", mode)
    return {"ok": True, "message": f"Appearance changed to {mode}.", "mode": mode}


def set_reduced_motion(enabled: bool) -> dict[str, Any]:
    code, out, err = hypr(["keyword", "animations:enabled", "0" if enabled else "1"])
    if code != 0:
        return {"ok": False, "error": err or out or "Hyprland rejected the motion preference."}
    intent_set("appearance.reduced_motion", enabled)
    return {"ok": True, "message": "Motion preference applied."}


def set_reduced_transparency(enabled: bool) -> dict[str, Any]:
    code, out, err = hypr(["keyword", "decoration:blur:enabled", "0" if enabled else "1"])
    if code != 0:
        return {"ok": False, "error": err or out or "Hyprland rejected the transparency preference."}
    intent_set("appearance.reduced_transparency", enabled)
    return {"ok": True, "message": "Transparency preference applied."}


_MODE_RE = re.compile(r"^(?P<w>\d+)x(?P<h>\d+)@(?P<r>\d+(?:\.\d+)?)Hz$")


def _mode_row(value: str) -> dict[str, Any] | None:
    match = _MODE_RE.fullmatch(value.strip())
    if not match:
        return None
    width = int(match.group("w"))
    height = int(match.group("h"))
    refresh = float(match.group("r"))
    return {
        "resolution": f"{width}x{height}",
        "width": width,
        "height": height,
        "refresh": refresh,
        "label": f"{width} × {height} @ {refresh:g} Hz",
    }


def _display_row(raw: dict[str, Any]) -> dict[str, Any]:
    modes = []
    for value in raw.get("availableModes", []) if isinstance(raw.get("availableModes"), list) else []:
        if isinstance(value, str):
            row = _mode_row(value)
            if row:
                modes.append(row)
    return {
        "name": str(raw.get("name", "")),
        "description": str(raw.get("description", "")),
        "width": int(raw.get("width", 0) or 0),
        "height": int(raw.get("height", 0) or 0),
        "resolution": f"{int(raw.get('width', 0) or 0)}x{int(raw.get('height', 0) or 0)}",
        "refresh": float(raw.get("refreshRate", 0.0) or 0.0),
        "scale": float(raw.get("scale", 1.0) or 1.0),
        "x": int(raw.get("x", 0) or 0),
        "y": int(raw.get("y", 0) or 0),
        "transform": int(raw.get("transform", 0) or 0),
        "focused": bool(raw.get("focused", False)),
        "disabled": bool(raw.get("disabled", False)),
        "modes": modes,
    }


def snapshot_displays() -> dict[str, Any]:
    payload, error = hypr_json(["monitors", "-j"])
    if not isinstance(payload, list):
        return {
            "available": False,
            "outputs": [],
            "primarySupported": False,
            "arrangementSupported": False,
            "error": error or "Display state is unavailable.",
        }
    outputs = [_display_row(row) for row in payload if isinstance(row, dict) and row.get("name")]
    return {
        "available": True,
        "outputs": outputs,
        "primarySupported": False,
        "primaryOutput": "",
        "arrangementSupported": True,
        "rollbackSeconds": DISPLAY_ROLLBACK_SECONDS,
        "error": "",
    }


def _refresh_text(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _monitor_spec(row: dict[str, Any]) -> str:
    return ",".join([
        str(row["name"]),
        f"{row['resolution']}@{_refresh_text(float(row['refresh']))}",
        f"{int(row['x'])}x{int(row['y'])}",
        _refresh_text(float(row["scale"])),
        "transform",
        str(int(row["transform"])),
    ])


def _persisted_display_rows() -> list[dict[str, Any]]:
    payload = read_json(DISPLAY_CONFIG)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return []
    outputs = payload.get("outputs")
    return outputs if isinstance(outputs, list) else []


def _display_snapshot_rows() -> list[dict[str, Any]]:
    snap = snapshot_displays()
    return [
        {key: row[key] for key in ("name", "resolution", "refresh", "scale", "x", "y", "transform")}
        for row in snap.get("outputs", [])
    ] if snap.get("available") else []


def _apply_display_rows(rows: list[dict[str, Any]]) -> tuple[bool, str]:
    for row in rows:
        code, out, err = hypr(["keyword", "monitor", _monitor_spec(row)])
        if code != 0:
            return False, err or out or f"Hyprland rejected display {row.get('name', '')}."
    return True, ""


def _validate_display_candidate(payload: dict[str, Any], current: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    name = payload.get("name")
    if not isinstance(name, str) or name != current.get("name"):
        return None, "Invalid display identity."
    resolution = payload.get("resolution")
    if not isinstance(resolution, str) or not re.fullmatch(r"\d+x\d+", resolution):
        return None, "Invalid display resolution."
    try:
        refresh = float(payload.get("refresh"))
        scale = float(payload.get("scale"))
        x = int(payload.get("x"))
        y = int(payload.get("y"))
        transform = int(payload.get("transform"))
    except (TypeError, ValueError):
        return None, "Invalid display configuration."
    if not (20.0 <= refresh <= 1000.0 and 0.5 <= scale <= 4.0):
        return None, "Display refresh rate or scale is outside the supported range."
    if transform not in {0, 1, 2, 3} or not (-32768 <= x <= 32768 and -32768 <= y <= 32768):
        return None, "Display orientation or position is invalid."
    modes = current.get("modes", [])
    if modes and not any(
        item.get("resolution") == resolution and abs(float(item.get("refresh", 0)) - refresh) <= 0.2
        for item in modes if isinstance(item, dict)
    ):
        return None, "The selected resolution/refresh pair is not advertised by this output."
    return {
        "name": name,
        "resolution": resolution,
        "refresh": refresh,
        "scale": scale,
        "x": x,
        "y": y,
        "transform": transform,
    }, ""


def display_preview(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = snapshot_displays()
    if not snapshot.get("available"):
        return {"ok": False, "error": snapshot.get("error", "Display state is unavailable.")}
    current = next((row for row in snapshot["outputs"] if row["name"] == payload.get("name")), None)
    if current is None:
        return {"ok": False, "error": "The selected output is no longer available."}
    candidate, error = _validate_display_candidate(payload, current)
    if candidate is None:
        return {"ok": False, "error": error}
    baseline = _display_snapshot_rows()
    token = uuid.uuid4().hex
    TX_DIR.mkdir(parents=True, exist_ok=True)
    transaction = {
        "version": 1,
        "token": token,
        "createdAt": time.time(),
        "baseline": baseline,
        "candidate": candidate,
        "status": "preview",
    }
    atomic_json(TX_DIR / f"{token}.json", transaction)
    ok, apply_error = _apply_display_rows([candidate])
    if not ok:
        try:
            (TX_DIR / f"{token}.json").unlink()
        except OSError:
            pass
        return {"ok": False, "error": apply_error}
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "_display-watch", token],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {
        "ok": True,
        "token": token,
        "rollbackSeconds": DISPLAY_ROLLBACK_SECONDS,
        "message": "Display preview applied. Confirm to keep it.",
    }


def _load_transaction(token: str) -> tuple[Path | None, dict[str, Any] | None]:
    if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
        return None, None
    path = TX_DIR / f"{token}.json"
    payload = read_json(path)
    if not isinstance(payload, dict) or payload.get("token") != token:
        return path, None
    return path, payload


def display_commit(token: str) -> dict[str, Any]:
    path, transaction = _load_transaction(token)
    if path is None or transaction is None:
        return {"ok": False, "error": "Display preview transaction is missing or expired."}
    current = _display_snapshot_rows()
    if not current:
        return {"ok": False, "error": "Current display state cannot be verified."}
    atomic_json(DISPLAY_CONFIG, {"version": 1, "outputs": current})
    marker = TX_DIR / f"{token}.commit"
    marker.write_text("committed\n", encoding="utf-8")
    try:
        path.unlink()
    except OSError:
        pass
    return {"ok": True, "message": "Display configuration kept and persisted."}


def display_revert(token: str, *, automatic: bool = False) -> dict[str, Any]:
    path, transaction = _load_transaction(token)
    if path is None or transaction is None:
        return {"ok": False, "error": "Display preview transaction is missing or expired."}
    baseline = transaction.get("baseline")
    if not isinstance(baseline, list):
        return {"ok": False, "error": "Display rollback evidence is invalid."}
    marker = TX_DIR / f"{token}.revert"
    ok, error = _apply_display_rows([row for row in baseline if isinstance(row, dict)])
    if ok:
        marker.write_text("automatic\n" if automatic else "requested\n", encoding="utf-8")
        try:
            path.unlink()
        except OSError:
            pass
    return {
        "ok": ok,
        "message": "Display configuration reverted." if ok else "",
        "error": error if not ok else "",
    }


def display_watch(token: str) -> int:
    time.sleep(DISPLAY_ROLLBACK_SECONDS)
    commit = TX_DIR / f"{token}.commit"
    revert = TX_DIR / f"{token}.revert"
    if commit.exists() or revert.exists():
        for marker in (commit, revert):
            try:
                marker.unlink()
            except OSError:
                pass
        return 0
    result = display_revert(token, automatic=True)
    return 0 if result.get("ok") else 1


def _audio_rows(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sinks: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    section = ""
    for raw in text.splitlines():
        if "Sinks:" in raw:
            section = "sink"
            continue
        if "Sources:" in raw:
            section = "source"
            continue
        if section not in {"sink", "source"}:
            continue
        cleaned = re.sub(r"^[\s│├└─]+", "", raw)
        default = cleaned.lstrip().startswith("*")
        cleaned = cleaned.lstrip().lstrip("*").strip()
        match = re.match(r"^(\d+)\.\s+(.+?)(?:\s+\[vol:.*)?$", cleaned)
        if not match:
            continue
        row = {"id": int(match.group(1)), "name": match.group(2).strip(), "default": default}
        (sinks if section == "sink" else sources).append(row)
    return sinks, sources


def _default_audio_state(target: str) -> dict[str, Any]:
    executable = shutil.which("wpctl")
    if not executable:
        return {"volume": 0, "muted": False}
    code, out, _ = run([executable, "get-volume", target], timeout=3.0)
    if code != 0:
        return {"volume": 0, "muted": False}
    match = re.search(r"Volume:\s*([0-9.]+)", out)
    volume = round(float(match.group(1)) * 100) if match else 0
    return {"volume": max(0, min(150, volume)), "muted": "[MUTED]" in out}


def snapshot_sound() -> dict[str, Any]:
    executable = shutil.which("wpctl")
    if not executable:
        return {"available": False, "outputs": [], "inputs": [], "error": "WirePlumber wpctl is unavailable."}
    code, out, err = run([executable, "status", "--name"], timeout=4.0)
    if code != 0:
        return {"available": False, "outputs": [], "inputs": [], "error": err or out or "PipeWire state is unavailable."}
    outputs, inputs = _audio_rows(out)
    return {
        "available": True,
        "outputs": outputs,
        "inputs": inputs,
        "output": _default_audio_state("@DEFAULT_AUDIO_SINK@"),
        "input": _default_audio_state("@DEFAULT_AUDIO_SOURCE@"),
        "error": "",
    }


def sound_default(direction: str, object_id: int) -> dict[str, Any]:
    snapshot = snapshot_sound()
    rows = snapshot.get("outputs" if direction == "output" else "inputs", []) if direction in {"output", "input"} else []
    if not any(row.get("id") == object_id for row in rows):
        return {"ok": False, "error": "The selected audio device is not currently available."}
    executable = shutil.which("wpctl")
    code, out, err = run([executable, "set-default", str(object_id)]) if executable else (127, "", "wpctl unavailable")
    return {"ok": code == 0, "message": "Default audio device changed." if code == 0 else "", "error": (err or out) if code != 0 else ""}


def sound_volume(direction: str, percent: int) -> dict[str, Any]:
    if direction not in {"output", "input"} or not (0 <= percent <= 150):
        return {"ok": False, "error": "Invalid audio volume request."}
    executable = shutil.which("wpctl")
    target = "@DEFAULT_AUDIO_SINK@" if direction == "output" else "@DEFAULT_AUDIO_SOURCE@"
    code, out, err = run([executable, "set-volume", target, f"{percent / 100:.3f}"]) if executable else (127, "", "wpctl unavailable")
    return {"ok": code == 0, "message": "Volume updated." if code == 0 else "", "error": (err or out) if code != 0 else ""}


def sound_mute(direction: str, muted: bool) -> dict[str, Any]:
    if direction not in {"output", "input"}:
        return {"ok": False, "error": "Invalid audio mute request."}
    executable = shutil.which("wpctl")
    target = "@DEFAULT_AUDIO_SINK@" if direction == "output" else "@DEFAULT_AUDIO_SOURCE@"
    code, out, err = run([executable, "set-mute", target, "1" if muted else "0"]) if executable else (127, "", "wpctl unavailable")
    return {"ok": code == 0, "message": "Mute state updated." if code == 0 else "", "error": (err or out) if code != 0 else ""}


_INPUT_SPECS: dict[str, tuple[str, type, float, float]] = {
    "repeatRate": ("input:repeat_rate", int, 1, 100),
    "repeatDelay": ("input:repeat_delay", int, 100, 2000),
    "sensitivity": ("input:sensitivity", float, -1.0, 1.0),
    "naturalScroll": ("input:touchpad:natural_scroll", bool, 0, 1),
    "tapToClick": ("input:touchpad:tap-to-click", bool, 0, 1),
    "disableWhileTyping": ("input:touchpad:disable_while_typing", bool, 0, 1),
}


def _input_current() -> dict[str, Any]:
    return {
        "repeatRate": int(hypr_option("input:repeat_rate", 25) or 25),
        "repeatDelay": int(hypr_option("input:repeat_delay", 600) or 600),
        "sensitivity": float(hypr_option("input:sensitivity", 0.0) or 0.0),
        "naturalScroll": bool(hypr_option("input:touchpad:natural_scroll", 0)),
        "tapToClick": bool(hypr_option("input:touchpad:tap-to-click", 1)),
        "disableWhileTyping": bool(hypr_option("input:touchpad:disable_while_typing", 0)),
    }


def snapshot_input() -> dict[str, Any]:
    payload, error = hypr_json(["devices", "-j"])
    if not isinstance(payload, dict):
        return {"available": False, "keyboards": [], "mice": [], "touchpads": [], "error": error or "Input state is unavailable."}

    def names(key: str) -> list[str]:
        rows = payload.get(key)
        return [str(row.get("name")) for row in rows if isinstance(row, dict) and row.get("name")] if isinstance(rows, list) else []

    pointer_names = names("mice")
    explicit_touchpads = names("touchpads")
    touchpads = explicit_touchpads or [
        name for name in pointer_names
        if re.search(r"(touchpad|trackpad)", name, flags=re.IGNORECASE)
    ]
    touchpad_set = set(touchpads)
    mice = [name for name in pointer_names if name not in touchpad_set]
    return {
        "available": True,
        "keyboards": names("keyboards"),
        "mice": mice,
        "touchpads": touchpads,
        "current": _input_current(),
        "error": "",
    }


def input_set(key: str, value: Any) -> dict[str, Any]:
    spec = _INPUT_SPECS.get(key)
    if spec is None:
        return {"ok": False, "error": "Unsupported input setting."}
    option, kind, low, high = spec
    if kind is bool:
        if not isinstance(value, bool):
            return {"ok": False, "error": "Input toggle must be boolean."}
        encoded = "true" if value else "false"
        normalized: Any = value
    else:
        try:
            normalized = kind(value)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid input setting value."}
        if not (low <= normalized <= high):
            return {"ok": False, "error": "Input setting is outside the supported range."}
        encoded = str(normalized)
    code, out, err = hypr(["keyword", option, encoded])
    if code != 0:
        return {"ok": False, "error": err or out or "Hyprland rejected the input setting."}
    payload = read_json(INPUT_CONFIG)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        payload = {"version": 1, "values": {}}
    values = payload.setdefault("values", {})
    if not isinstance(values, dict):
        return {"ok": False, "error": "Persisted input settings are invalid."}
    values[key] = normalized
    atomic_json(INPUT_CONFIG, payload)
    return {"ok": True, "message": "Input preference applied and persisted."}


def _battery_rows() -> list[dict[str, Any]]:
    base = Path("/sys/class/power_supply")
    rows: list[dict[str, Any]] = []
    if not base.is_dir():
        return rows
    for path in sorted(base.iterdir()):
        def read(name: str) -> str:
            try:
                return (path / name).read_text().strip()
            except OSError:
                return ""
        if read("type") != "Battery":
            continue
        try:
            capacity = int(read("capacity"))
        except ValueError:
            capacity = -1
        health = -1.0
        try:
            full = float(read("energy_full") or read("charge_full"))
            design = float(read("energy_full_design") or read("charge_full_design"))
            if design > 0:
                health = round(full / design * 100, 1)
        except ValueError:
            pass
        rows.append({
            "name": path.name,
            "capacity": capacity,
            "status": read("status"),
            "health": health,
            "manufacturer": read("manufacturer"),
            "model": read("model_name"),
        })
    return rows


def _power_profiles() -> tuple[bool, str, list[str], str]:
    executable = shutil.which("powerprofilesctl")
    if not executable:
        return False, "", [], "power-profiles-daemon is unavailable."
    code, current, err = run([executable, "get"], timeout=3.0)
    if code != 0:
        return False, "", [], err or "Power profile state is unavailable."
    code, listing, _ = run([executable, "list"], timeout=3.0)
    profiles = []
    if code == 0:
        for value in ("performance", "balanced", "power-saver"):
            if re.search(rf"(?m)^\s*\*?\s*{re.escape(value)}:", listing):
                profiles.append(value)
    if current not in profiles:
        profiles.append(current)
    return True, current, [p for p in profiles if p], ""


def snapshot_power() -> dict[str, Any]:
    available, current, profiles, error = _power_profiles()
    return {
        "available": True,
        "batteries": _battery_rows(),
        "profileControlAvailable": available,
        "profile": current,
        "profiles": profiles,
        "profileError": error,
        "error": "",
    }


def power_profile(profile_name: str) -> dict[str, Any]:
    available, _, profiles, error = _power_profiles()
    if not available or profile_name not in profiles:
        return {"ok": False, "error": error or "Unsupported power profile."}
    executable = shutil.which("powerprofilesctl")
    code, out, err = run([executable, "set", profile_name], timeout=5.0) if executable else (127, "", "powerprofilesctl unavailable")
    return {"ok": code == 0, "message": "Power mode changed." if code == 0 else "", "error": (err or out) if code != 0 else ""}


def _os_release() -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key] = value.strip().strip('"')
    except OSError:
        pass
    return result


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("model name") and ":" in line:
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor()


def _memory_total() -> str:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                kib = int(line.split()[1])
                return f"{kib / 1024 / 1024:.1f} GiB"
    except (OSError, ValueError):
        pass
    return ""


def _maho_release_identity() -> dict[str, str]:
    payload = read_json(ROOT / "share" / "maho" / "release.json")
    if isinstance(payload, dict):
        return {
            "version": str(payload.get("maho_version", "")),
            "sourceRevision": str(payload.get("source_revision", "")),
            "runtimeRelease": str(payload.get("runtime_release", "")),
        }
    code, out, _ = run(["git", "-C", str(ROOT), "rev-parse", "--short=12", "HEAD"], timeout=2.0)
    revision = out if code == 0 and re.fullmatch(r"[0-9a-f]{7,40}", out) else ""
    return {"version": "Development", "sourceRevision": revision, "runtimeRelease": ""}


def snapshot_about() -> dict[str, Any]:
    release = _os_release()
    maho_release = _maho_release_identity()
    hypr_version, _ = hypr_json(["version", "-j"])
    return {
        "available": True,
        "mahoVersion": maho_release["version"],
        "sourceRevision": maho_release["sourceRevision"],
        "runtimeRelease": maho_release["runtimeRelease"],
        "osName": release.get("PRETTY_NAME", release.get("NAME", "MahoOS")),
        "osVersion": release.get("VERSION_ID", ""),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "hostname": socket.gethostname(),
        "cpu": _cpu_model(),
        "memory": _memory_total(),
        "sessionType": os.environ.get("XDG_SESSION_TYPE", ""),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "Hyprland"),
        "hyprland": hypr_version if isinstance(hypr_version, dict) else {},
        "error": "",
    }


def search(query: str) -> list[dict[str, Any]]:
    normalized = " ".join(re.findall(r"[a-z0-9]+", query.lower()))
    if not normalized:
        return []
    tokens = normalized.split()
    results = []
    for route, category, title, keywords in SEARCH_TARGETS:
        haystack = f"{category} {title} {keywords}".lower()
        score = 0
        if normalized == title.lower():
            score += 100
        if normalized in title.lower():
            score += 45
        if normalized in category.lower():
            score += 30
        for token in tokens:
            words = re.findall(r"[a-z0-9]+", haystack)
            if token in words:
                score += 22
            elif any(word.startswith(token) for word in words):
                score += 12
            elif token in haystack:
                score += 6
            else:
                score -= 25
        if score > 0:
            results.append({
                "route": route if route not in DEFERRED_ROUTES else "system" if route in {"updates", "recovery", "guardian", "storage"} else route,
                "target": route,
                "category": category,
                "title": title,
                "label": f"{category} / {title}",
                "deferred": route in DEFERRED_ROUTES,
                "score": score,
            })
    results.sort(key=lambda row: (-row["score"], row["category"], row["title"]))
    return results[:12]


def snapshot(section: str = "all") -> dict[str, Any]:
    providers = {
        "appearance": snapshot_appearance,
        "displays": snapshot_displays,
        "sound": snapshot_sound,
        "input": snapshot_input,
        "power": snapshot_power,
        "system": snapshot_about,
    }
    if section != "all":
        provider = providers.get(section)
        if provider is None:
            return {"ok": False, "error": "Unknown settings section."}
        return {"ok": True, section: provider()}
    return {"ok": True, **{name: provider() for name, provider in providers.items()}}


def _apply_persisted_input() -> list[str]:
    payload = read_json(INPUT_CONFIG)
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("values"), dict):
        return []
    applied = []
    for key, value in payload["values"].items():
        spec = _INPUT_SPECS.get(key)
        if spec is None:
            continue
        option, kind, low, high = spec
        if kind is bool and isinstance(value, bool):
            encoded = "true" if value else "false"
        elif kind is not bool:
            try:
                normalized = kind(value)
            except (TypeError, ValueError):
                continue
            if not (low <= normalized <= high):
                continue
            encoded = str(normalized)
        else:
            continue
        code, _, _ = hypr(["keyword", option, encoded])
        if code == 0:
            applied.append(key)
    return applied


def apply_session() -> dict[str, Any]:
    applied: list[str] = []
    skipped: list[str] = []
    if hypr_prefix()[0] is None:
        return {"ok": True, "applied": [], "skipped": ["hyprland-unavailable"]}

    reduced_motion = bool(intent_get("appearance.reduced_motion", False))
    if hypr(["keyword", "animations:enabled", "0" if reduced_motion else "1"])[0] == 0:
        applied.append("appearance.reduced_motion")

    reduced_transparency = bool(intent_get("appearance.reduced_transparency", False))
    if hypr(["keyword", "decoration:blur:enabled", "0" if reduced_transparency else "1"])[0] == 0:
        applied.append("appearance.reduced_transparency")

    applied.extend(f"input.{key}" for key in _apply_persisted_input())

    persisted = _persisted_display_rows()
    if persisted:
        current = _display_snapshot_rows()
        if {row.get("name") for row in current} == {row.get("name") for row in persisted}:
            ok, _ = _apply_display_rows([row for row in persisted if isinstance(row, dict)])
            if ok:
                applied.append("displays")
            else:
                _apply_display_rows([row for row in current if isinstance(row, dict)])
                skipped.append("displays-apply-failed-rolled-back")
        else:
            skipped.append("displays-topology-changed")

    return {"ok": True, "applied": applied, "skipped": skipped}


def action(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if name == "appearance.mode":
        return set_appearance_mode(str(payload.get("mode", "")))
    if name in {"appearance.reducedMotion", "appearance.reducedTransparency", "sound.mute"}:
        enabled = payload.get("enabled") if name.startswith("appearance.") else payload.get("muted")
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "Toggle value must be boolean."}
        if name == "appearance.reducedMotion":
            return set_reduced_motion(enabled)
        if name == "appearance.reducedTransparency":
            return set_reduced_transparency(enabled)
        return sound_mute(str(payload.get("direction", "")), enabled)
    if name == "display.preview":
        return display_preview(payload)
    if name == "display.commit":
        return display_commit(str(payload.get("token", "")))
    if name == "display.revert":
        return display_revert(str(payload.get("token", "")))
    if name == "sound.default":
        try:
            object_id = int(payload.get("id"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid audio device identity."}
        return sound_default(str(payload.get("direction", "")), object_id)
    if name == "sound.volume":
        try:
            percent = int(payload.get("percent"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid volume."}
        return sound_volume(str(payload.get("direction", "")), percent)
    if name == "input.set":
        return input_set(str(payload.get("key", "")), payload.get("value"))
    if name == "power.profile":
        return power_profile(str(payload.get("profile", "")))
    return {"ok": False, "error": "Unsupported settings action."}


def usage() -> int:
    print("Usage: maho-settings-backend snapshot [all|SECTION] | search QUERY | action NAME JSON | apply-session", file=sys.stderr)
    return 2


def main(argv: list[str]) -> int:
    try:
        if not argv:
            return usage()
        command = argv[0]
        if command == "snapshot":
            emit(snapshot(argv[1] if len(argv) > 1 else "all"))
            return 0
        if command == "search" and len(argv) == 2:
            emit({"ok": True, "results": search(argv[1])})
            return 0
        if command == "action" and len(argv) == 3:
            try:
                payload = json.loads(argv[2])
            except json.JSONDecodeError:
                emit({"ok": False, "error": "Action payload must be valid JSON."})
                return 0
            if not isinstance(payload, dict):
                emit({"ok": False, "error": "Action payload must be an object."})
                return 0
            emit(action(argv[1], payload))
            return 0
        if command == "apply-session" and len(argv) == 1:
            emit(apply_session())
            return 0
        if command == "_display-watch" and len(argv) == 2:
            return display_watch(argv[1])
        return usage()
    except Exception as exc:
        emit({"ok": False, "error": f"Settings backend failure: {exc}"})
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
