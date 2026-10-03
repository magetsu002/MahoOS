#!/usr/bin/env python3
"""Bounded system adapters for the native Maho Settings application.

Maho Settings is a presenter/requester. Hyprland, WirePlumber, power-profiles,
Maho theme/wallpaper helpers, the kernel and MahoSystem remain authoritative.
"""

from __future__ import annotations

import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
from threading import Lock
import time
import uuid
from typing import Any, Callable, Iterable

LIB_DIR = Path(__file__).resolve().parent
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))
import maho_hypr_config as hypr_config_writer

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

_HYPR_COLLECTION_LOCK = Lock()
_HYPR_COLLECTION_CACHE: tuple[dict[str, Any] | None, str] | None = None

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
    ("notifications", "Notifications", "Do Not Disturb", "notifications alerts dnd quiet focus"),
    ("notifications", "Notifications", "History", "notifications history unread clear retained"),
    ("applications", "Applications", "Default Browser", "applications apps defaults browser web handler"),
    ("applications", "Applications", "File Manager", "applications apps defaults files folders directory handler"),
    ("applications", "Applications", "Default Associations", "applications defaults mime associations file types handlers"),
    ("applications", "Applications", "Autostart", "applications startup login autostart session"),
    ("users", "Users", "Accounts", "users accounts login"),
    ("region", "Region & Time", "Time Zone", "region time timezone clock"),
    ("region", "Region & Time", "Automatic Time", "region time ntp automatic synchronized"),
    ("region", "Region & Time", "Locale", "region language locale formats"),
    ("region", "Region & Time", "Keyboard Layout", "region keyboard layout xkb language input"),
    ("shortcuts", "Shortcuts", "Keyboard Shortcuts", "shortcuts keybinds binds hotkeys keys keyboard"),
    ("rules", "Rules", "Window Rules", "rules window workspace layer behavior matching"),
    ("motion", "Motion", "Animations", "motion animations animation curves bezier transitions"),
    ("session", "Session", "Startup", "session startup autostart login logout commands"),
    ("configuration", "Configuration", "Managed Configuration", "configuration hyprland managed config source"),
    ("diagnostics", "Diagnostics", "Configuration Health", "diagnostics configuration health config errors providers backend"),
    ("accessibility", "Accessibility", "Accessibility", "accessibility contrast motion transparency"),
    ("updates", "System", "Updates", "updates update packages maintenance"),
    ("recovery", "System", "Recovery", "recovery restore rollback generation rescue"),
    ("guardian", "System", "Guardian", "guardian trust security incidents"),
    ("storage", "System", "Storage", "storage disk space filesystem"),
)

DEFERRED_ROUTES = {
    "network", "users", "accessibility", "updates", "recovery", "guardian", "storage",
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


def _lua_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _lua_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _lua_string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not (float("-inf") < value < float("inf")):
            raise ValueError("non-finite Lua number")
        return repr(value)
    raise ValueError("unsupported Lua value")


def _lua_table(path: tuple[str, ...], value: Any) -> str:
    if not path or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) for key in path):
        raise ValueError("invalid Lua config path")
    body = f"{path[-1]} = {_lua_value(value)}"
    for key in reversed(path[:-1]):
        body = f"{key} = {{ {body} }}"
    return "{ " + body + " }"


def hypr_eval(expression: str) -> tuple[bool, str]:
    code, out, err = hypr(["eval", expression])
    if code != 0:
        return False, err or out or "Hyprland Lua request failed."
    response = out.strip()
    if response != "ok":
        return False, err or response or "Hyprland did not confirm the Lua request."
    return True, ""


def _hypr_config(path: tuple[str, ...], value: Any) -> tuple[bool, str]:
    try:
        expression = f"hl.config({_lua_table(path, value)})"
    except ValueError as exc:
        return False, str(exc)
    return hypr_eval(expression)


def hypr_json(args: Iterable[str]) -> tuple[Any | None, str]:
    code, out, err = hypr(args)
    if code != 0:
        return None, err or out or "Hyprland request failed."
    try:
        return json.loads(out), ""
    except json.JSONDecodeError:
        return None, "Hyprland returned invalid JSON."


def _collect_hypr_config(*, force: bool = False) -> tuple[dict[str, Any] | None, str]:
    global _HYPR_COLLECTION_CACHE

    with _HYPR_COLLECTION_LOCK:
        if _HYPR_COLLECTION_CACHE is not None and not force:
            return _HYPR_COLLECTION_CACHE

        lua = shutil.which("lua")
        collector = ROOT / "lib" / "maho_hypr_collect.lua"
        config = CONFIG_HOME / "hypr" / "hyprland.lua"
        if not config.is_file():
            source_config = ROOT / "config" / "hypr" / "hyprland.lua"
            config = source_config if source_config.is_file() else config

        if not lua:
            result = (None, "Lua configuration collector is unavailable.")
        elif not collector.is_file():
            result = (None, "Maho Hyprland configuration collector is unavailable.")
        elif not config.is_file():
            result = (None, "Hyprland configuration source is unavailable.")
        else:
            code, out, err = run([lua, str(collector), str(config)], timeout=5.0)
            if code != 0 or not out:
                result = (None, err or out or "Hyprland configuration collection failed.")
            else:
                try:
                    payload = json.loads(out)
                except json.JSONDecodeError:
                    result = (None, "Hyprland configuration collector returned invalid JSON.")
                else:
                    if not isinstance(payload, dict):
                        result = (None, "Hyprland configuration collector returned invalid state.")
                    else:
                        collection_error = str(payload.get("error", "") or "")
                        result = (payload, collection_error)

        _HYPR_COLLECTION_CACHE = result
        return result


def _clear_hypr_collection_cache() -> None:
    global _HYPR_COLLECTION_CACHE
    with _HYPR_COLLECTION_LOCK:
        _HYPR_COLLECTION_CACHE = None


def _writer_source_is_overlay(source_file: str, writer: dict[str, Any]) -> bool:
    if not source_file:
        return False
    overlay = str(writer.get("path", "") or "")
    if not overlay:
        return False
    try:
        return Path(source_file).resolve(strict=False) == Path(overlay).resolve(strict=False)
    except OSError:
        return False


def _apply_managed_hypr_model(
    model: dict[str, Any],
    *,
    verify: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[bool, dict[str, Any], str]:
    writer = hypr_config_writer.status()
    if not bool(writer.get("mutationAvailable")):
        return False, {}, (
            "Managed Hyprland editing is not live yet. "
            "The certified Maho user-overlay loader is not installed in this runtime."
        )

    prefix, session_error = hypr_prefix()
    if prefix is None:
        return False, {}, session_error or "No unique Hyprland session is available."

    try:
        previous = hypr_config_writer.load_model()
    except hypr_config_writer.ConfigWriteError as exc:
        return False, {}, str(exc)

    runner = lambda command, timeout: run(command, timeout=timeout)
    try:
        result = hypr_config_writer.apply_model(
            model,
            hypr_prefix=prefix,
            runner=runner,
            reload_live=True,
        )
    except hypr_config_writer.ConfigWriteError as exc:
        return False, {}, str(exc)

    _clear_hypr_collection_cache()
    if verify is None:
        return True, result, ""

    observed, observe_error = _collect_hypr_config(force=True)
    if isinstance(observed, dict) and not observe_error and verify(observed):
        return True, result, ""

    verification_error = observe_error or "The requested configuration was not observed after reload."
    try:
        hypr_config_writer.apply_model(
            previous,
            hypr_prefix=prefix,
            runner=runner,
            reload_live=True,
        )
        _clear_hypr_collection_cache()
        restored, restore_error = _collect_hypr_config(force=True)
        if restore_error or not isinstance(restored, dict):
            return False, {}, (
                f"{verification_error} Rollback ran but current configuration could not be re-observed."
            )
    except hypr_config_writer.ConfigWriteError as exc:
        return False, {}, f"{verification_error} Rollback failed: {exc}"

    return False, {}, f"{verification_error} The managed change was rolled back."


def hypr_option(name: str, fallback: Any = None) -> Any:
    payload, _ = hypr_json(["getoption", name, "-j"])
    if not isinstance(payload, dict):
        return fallback
    if "bool" in payload:
        return payload["bool"]
    if "int" in payload:
        return payload["int"]
    if "float" in payload:
        return payload["float"]
    if "str" in payload:
        return payload["str"]
    return fallback


def wallpaper_state() -> dict[str, Any]:
    # The wallpaper owner publishes its last confirmed state here. Reading that
    # state is both authoritative and dramatically faster than re-querying the
    # live provider for every Settings refresh.
    published = read_json(STATE_HOME / "maho" / "wallpaper" / "current.json")
    if isinstance(published, dict):
        path = published.get("path")
        if isinstance(path, str) and Path(path).is_file():
            return published

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
    if isinstance(wallpaper, dict):
        path = wallpaper.get("path")
        preview_path = path if isinstance(path, str) and Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"} else ""
        if not preview_path and isinstance(palette, dict):
            source = palette.get("source", {})
            candidate = source.get("path") if isinstance(source, dict) else ""
            if isinstance(candidate, str) and Path(candidate).is_file():
                preview_path = candidate
        wallpaper = {**wallpaper, "previewPath": preview_path}
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
    if not isinstance(path, str) or not Path(path).is_file():
        palette = read_json(CACHE_HOME / "maho" / "theme" / "active.json")
        source = palette.get("source", {}) if isinstance(palette, dict) else {}
        candidate = source.get("path") if isinstance(source, dict) else None
        if isinstance(candidate, str) and Path(candidate).is_file():
            path = candidate

    theme = root_command("maho-theme")
    if not theme or not isinstance(path, str) or not Path(path).is_file():
        return {"ok": False, "error": "The current wallpaper/theme backend is unavailable."}

    code, out, err = run([theme, "apply", path, mode], timeout=25.0)
    if code != 0:
        return {"ok": False, "error": err or out or "Theme application failed."}

    intent_set("appearance.theme.mode", mode)
    active = read_json(CACHE_HOME / "maho" / "theme" / "active.json")
    if not isinstance(active, dict) or active.get("mode") != mode:
        return {"ok": False, "error": "Appearance owner did not confirm the requested mode."}
    return {
        "ok": True,
        "message": f"Appearance changed to {mode}.",
        "mode": mode,
        "statePatch": {"mode": mode},
    }


def set_reduced_motion(enabled: bool) -> dict[str, Any]:
    ok, error = _hypr_config(("animations", "enabled"), not enabled)
    if not ok:
        return {"ok": False, "error": error or "Hyprland rejected the motion preference."}
    intent_set("appearance.reduced_motion", enabled)
    return {
        "ok": True,
        "message": "Motion preference applied.",
        "statePatch": {"reducedMotion": enabled},
    }


def set_reduced_transparency(enabled: bool) -> dict[str, Any]:
    ok, error = _hypr_config(("decoration", "blur", "enabled"), not enabled)
    if not ok:
        return {"ok": False, "error": error or "Hyprland rejected the transparency preference."}
    intent_set("appearance.reduced_transparency", enabled)
    return {
        "ok": True,
        "message": "Transparency preference applied.",
        "statePatch": {"reducedTransparency": enabled},
    }


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
        "enabled": not bool(raw.get("disabled", False)),
        "modes": modes,
    }


def snapshot_displays() -> dict[str, Any]:
    payload, error = hypr_json(["monitors", "all", "-j"])
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
        "enabledCount": sum(1 for row in outputs if row.get("enabled")),
        "rollbackSeconds": DISPLAY_ROLLBACK_SECONDS,
        "error": "",
    }


def _refresh_text(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _monitor_eval(row: dict[str, Any]) -> str:
    output = _lua_string(str(row["name"]))
    if row.get("enabled") is False:
        return f"hl.monitor({{ output = {output}, disabled = true }})"
    mode = _lua_string(f"{row['resolution']}@{_refresh_text(float(row['refresh']))}")
    position = _lua_string(f"{int(row['x'])}x{int(row['y'])}")
    scale = _lua_value(float(row["scale"]))
    transform = int(row["transform"])
    return (
        "hl.monitor({ "
        f"output = {output}, mode = {mode}, position = {position}, "
        f"scale = {scale}, transform = {transform}, disabled = false"
        " })"
    )


def _persisted_display_rows() -> list[dict[str, Any]]:
    payload = read_json(DISPLAY_CONFIG)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return []
    outputs = payload.get("outputs")
    return outputs if isinstance(outputs, list) else []


def _rows_from_display_snapshot(snap: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {key: row[key] for key in ("name", "resolution", "refresh", "scale", "x", "y", "transform", "enabled")}
        for row in snap.get("outputs", [])
        if isinstance(row, dict) and row.get("name")
    ] if snap.get("available") else []


def _display_snapshot_rows() -> list[dict[str, Any]]:
    return _rows_from_display_snapshot(snapshot_displays())


def _apply_display_rows(rows: list[dict[str, Any]]) -> tuple[bool, str]:
    ordered = sorted(rows, key=lambda row: row.get("enabled") is False)
    for row in ordered:
        try:
            expression = _monitor_eval(row)
        except (KeyError, TypeError, ValueError) as exc:
            return False, f"Invalid display row: {exc}"
        ok, error = hypr_eval(expression)
        if not ok:
            return False, error or f"Hyprland rejected display {row.get('name', '')}."
    return True, ""


def _validate_display_candidate(payload: dict[str, Any], current: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    name = payload.get("name")
    if not isinstance(name, str) or name != current.get("name"):
        return None, "Invalid display identity."
    resolution = payload.get("resolution")
    if not isinstance(resolution, str) or not re.fullmatch(r"\d+x\d+", resolution):
        return None, "Invalid display resolution."
    enabled = payload.get("enabled", True)
    if not isinstance(enabled, bool):
        return None, "Display enabled state must be boolean."
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
        "enabled": enabled,
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
    if not candidate["enabled"] and snapshot.get("enabledCount", 0) <= 1:
        return {"ok": False, "error": "The last active display cannot be disabled."}

    baseline = _rows_from_display_snapshot(snapshot)
    proposed = [dict(row) for row in baseline]
    for index, row in enumerate(proposed):
        if row.get("name") == candidate["name"]:
            proposed[index] = dict(candidate)
            break

    token = uuid.uuid4().hex
    TX_DIR.mkdir(parents=True, exist_ok=True)
    transaction = {
        "version": 1,
        "token": token,
        "createdAt": time.time(),
        "topology": sorted(row["name"] for row in baseline),
        "baseline": baseline,
        "proposed": proposed,
        "candidate": candidate,
        "status": "preview",
    }
    atomic_json(TX_DIR / f"{token}.json", transaction)
    ok, apply_error = _apply_display_rows([candidate])
    if not ok:
        _apply_display_rows(baseline)
        try:
            (TX_DIR / f"{token}.json").unlink()
        except OSError:
            pass
        return {"ok": False, "error": apply_error}

    live_after_preview = _display_snapshot_rows()
    selected_after_preview = next(
        (row for row in live_after_preview if row.get("name") == candidate["name"]),
        None,
    )
    if selected_after_preview is None or not _display_candidate_matches(selected_after_preview, candidate):
        rollback_ok, rollback_error = _apply_display_rows(baseline)
        rollback_verified = rollback_ok and _display_layout_matches(_display_snapshot_rows(), baseline)
        try:
            (TX_DIR / f"{token}.json").unlink()
        except OSError:
            pass
        detail = "Hyprland did not apply the requested display preview."
        if not rollback_verified:
            detail += " Automatic restoration could not be verified"
            if rollback_error:
                detail += f": {rollback_error}"
            detail += "."
        return {"ok": False, "error": detail}

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


def _display_candidate_matches(current: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if current.get("name") != candidate.get("name"):
        return False
    if bool(current.get("enabled", True)) != bool(candidate.get("enabled", True)):
        return False
    if not candidate.get("enabled", True):
        return True
    try:
        return (
            current.get("resolution") == candidate.get("resolution")
            and abs(float(current.get("refresh", 0)) - float(candidate.get("refresh", 0))) <= 0.2
            and abs(float(current.get("scale", 0)) - float(candidate.get("scale", 0))) <= 0.01
            and int(current.get("x", 0)) == int(candidate.get("x", 0))
            and int(current.get("y", 0)) == int(candidate.get("y", 0))
            and int(current.get("transform", 0)) == int(candidate.get("transform", 0))
        )
    except (TypeError, ValueError):
        return False


def _display_layout_matches(current: list[dict[str, Any]], expected: list[dict[str, Any]]) -> bool:
    if {row.get("name") for row in current} != {row.get("name") for row in expected}:
        return False
    for candidate in expected:
        selected = next((row for row in current if row.get("name") == candidate.get("name")), None)
        if selected is None or not _display_candidate_matches(selected, candidate):
            return False
    return True


def display_commit(token: str) -> dict[str, Any]:
    path, transaction = _load_transaction(token)
    if path is None or transaction is None:
        return {"ok": False, "error": "Display preview transaction is missing or expired."}
    current = _display_snapshot_rows()
    if not current:
        return {"ok": False, "error": "Current display state cannot be verified."}
    topology = transaction.get("topology")
    if not isinstance(topology, list) or sorted(row.get("name") for row in current) != sorted(topology):
        return {"ok": False, "error": "Display topology changed during the preview; nothing was persisted."}
    candidate = transaction.get("candidate")
    selected = next((row for row in current if isinstance(candidate, dict) and row.get("name") == candidate.get("name")), None)
    if not isinstance(candidate, dict) or selected is None or not _display_candidate_matches(selected, candidate):
        return {"ok": False, "error": "The live display state no longer matches the preview; nothing was persisted."}
    proposed = transaction.get("proposed")
    if not isinstance(proposed, list):
        return {"ok": False, "error": "Display preview persistence evidence is invalid."}
    atomic_json(DISPLAY_CONFIG, {"version": 1, "outputs": proposed})
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
    commit_marker = TX_DIR / f"{token}.commit"
    if automatic and commit_marker.exists():
        return {"ok": True, "message": "Display preview was already committed.", "error": ""}

    marker = TX_DIR / f"{token}.revert"
    ok, error = _apply_display_rows([row for row in baseline if isinstance(row, dict)])
    if ok and automatic and commit_marker.exists():
        # A Keep request won the narrow watchdog race. Re-apply the confirmed proposal.
        proposed = transaction.get("proposed")
        if isinstance(proposed, list):
            keep_ok, keep_error = _apply_display_rows([row for row in proposed if isinstance(row, dict)])
            if keep_ok and _display_layout_matches(_display_snapshot_rows(), proposed):
                return {"ok": True, "message": "Display preview was already committed.", "error": ""}
            return {"ok": False, "error": keep_error or "Committed display state could not be restored."}

    verified = ok and _display_layout_matches(_display_snapshot_rows(), baseline)
    if verified:
        marker.write_text("automatic\n" if automatic else "requested\n", encoding="utf-8")
        try:
            path.unlink()
        except OSError:
            pass
    return {
        "ok": verified,
        "message": "Display configuration reverted." if verified else "",
        "error": (error or "Display rollback could not be verified.") if not verified else "",
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


def display_focus(name: str) -> dict[str, Any]:
    snapshot = snapshot_displays()
    row = next((item for item in snapshot.get("outputs", []) if item.get("name") == name), None)
    if not snapshot.get("available") or row is None or not row.get("enabled"):
        return {"ok": False, "error": "The requested display is not currently active."}
    ok, error = hypr_eval(
        f"hl.dispatch(hl.dsp.focus({{ monitor = {_lua_string(name)} }}))"
    )
    if not ok:
        return {"ok": False, "message": "", "error": error}
    confirmed = snapshot_displays()
    focused = next(
        (item for item in confirmed.get("outputs", []) if item.get("name") == name),
        None,
    )
    verified = bool(confirmed.get("available") and focused and focused.get("focused"))
    return {
        "ok": verified,
        "message": "Display focused for the current session." if verified else "",
        "error": "" if verified else "Hyprland did not confirm the focused display.",
    }


def _audio_rows(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sinks: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    in_audio = False
    section = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped == "Audio":
            in_audio = True
            section = ""
            continue
        if in_audio and stripped in {"Video", "Settings"}:
            break
        if not in_audio:
            continue
        if "Sinks:" in raw:
            section = "sink"
            continue
        if "Sources:" in raw:
            section = "source"
            continue
        if "Filters:" in raw:
            section = "filter"
            continue
        if "Streams:" in raw or "Devices:" in raw:
            section = ""
            continue
        if section not in {"sink", "source", "filter"}:
            continue

        cleaned = re.sub(r"^[\s│├└─]+", "", raw)
        default = cleaned.lstrip().startswith("*")
        cleaned = cleaned.lstrip().lstrip("*").strip()
        match = re.match(r"^(\d+)\.\s+(.+?)\s*(?:\[([^\]]+)\])?$", cleaned)
        if not match:
            continue
        object_id = int(match.group(1))
        name = match.group(2).strip()
        metadata = (match.group(3) or "").strip()

        target = section
        if section == "filter":
            if metadata == "Audio/Sink":
                target = "sink"
            elif metadata == "Audio/Source":
                target = "source"
            else:
                continue
        if target in {"sink", "source"}:
            row = {"id": object_id, "name": name, "default": default}
            (sinks if target == "sink" else sources).append(row)
    return sinks, sources


def _audio_friendly_name(object_id: int, fallback: str) -> str:
    if not fallback.startswith(("bluez_", "alsa_")):
        return fallback
    executable = shutil.which("wpctl")
    if not executable:
        return fallback
    code, out, _ = run([executable, "inspect", str(object_id)], timeout=2.0)
    if code != 0:
        return fallback
    for key in ("node.description", "media.name"):
        match = re.search(rf'(?m)^\s*\*?\s*{re.escape(key)}\s*=\s*"([^"]+)"\s*$', out)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return fallback


def _default_audio_state(target: str) -> dict[str, Any]:
    executable = shutil.which("wpctl")
    if not executable:
        return {
            "available": False, "volume": 0, "muted": False,
            "error": "WirePlumber wpctl is unavailable.",
        }
    code, out, err = run([executable, "get-volume", target], timeout=3.0)
    if code != 0:
        return {
            "available": False, "volume": 0, "muted": False,
            "error": err or out or "Default audio state is unavailable.",
        }
    match = re.search(r"Volume:\s*([0-9.]+)", out)
    if not match:
        return {
            "available": False, "volume": 0, "muted": False,
            "error": "WirePlumber returned an invalid volume state.",
        }
    volume = round(float(match.group(1)) * 100)
    return {
        "available": True,
        "volume": max(0, min(150, volume)),
        "muted": "[MUTED]" in out,
        "error": "",
    }


def snapshot_sound() -> dict[str, Any]:
    executable = shutil.which("wpctl")
    if not executable:
        return {"available": False, "outputs": [], "inputs": [], "error": "WirePlumber wpctl is unavailable."}
    code, out, err = run([executable, "status"], timeout=4.0)
    if code != 0:
        return {"available": False, "outputs": [], "inputs": [], "error": err or out or "PipeWire state is unavailable."}
    outputs, inputs = _audio_rows(out)
    for row in [*outputs, *inputs]:
        row["name"] = _audio_friendly_name(int(row["id"]), str(row["name"]))
    return {
        "available": True,
        "outputs": outputs,
        "inputs": inputs,
        "output": _default_audio_state("@DEFAULT_AUDIO_SINK@"),
        "input": _default_audio_state("@DEFAULT_AUDIO_SOURCE@"),
        "error": "",
    }


def sound_default(direction: str, object_id: int) -> dict[str, Any]:
    if direction not in {"output", "input"}:
        return {"ok": False, "error": "Invalid audio device direction."}
    snapshot = snapshot_sound()
    if not snapshot.get("available"):
        return {"ok": False, "error": snapshot.get("error", "Audio state is unavailable.")}
    rows = snapshot.get("outputs" if direction == "output" else "inputs", [])
    if not any(row.get("id") == object_id for row in rows):
        return {"ok": False, "error": "The selected audio device is not currently available."}
    executable = shutil.which("wpctl")
    if not executable:
        return {"ok": False, "error": "WirePlumber wpctl is unavailable."}
    code, out, err = run([executable, "set-default", str(object_id)])
    if code != 0:
        return {"ok": False, "error": err or out or "WirePlumber rejected the default-device request."}
    confirmed = snapshot_sound()
    confirmed_rows = confirmed.get("outputs" if direction == "output" else "inputs", [])
    if not confirmed.get("available") or not any(
        row.get("id") == object_id and row.get("default") for row in confirmed_rows
    ):
        return {"ok": False, "error": "WirePlumber did not confirm the requested default audio device."}
    return {"ok": True, "message": "Default audio device changed."}


def sound_volume(direction: str, percent: int) -> dict[str, Any]:
    if direction not in {"output", "input"} or not (0 <= percent <= 150):
        return {"ok": False, "error": "Invalid audio volume request."}
    executable = shutil.which("wpctl")
    if not executable:
        return {"ok": False, "error": "WirePlumber wpctl is unavailable."}
    target = "@DEFAULT_AUDIO_SINK@" if direction == "output" else "@DEFAULT_AUDIO_SOURCE@"
    before = _default_audio_state(target)
    if not before.get("available"):
        return {"ok": False, "error": before.get("error", "Default audio state is unavailable.")}
    code, out, err = run([executable, "set-volume", target, f"{percent / 100:.3f}"])
    if code != 0:
        return {"ok": False, "error": err or out or "WirePlumber rejected the volume request."}
    confirmed = _default_audio_state(target)
    if not confirmed.get("available") or abs(int(confirmed.get("volume", -999)) - percent) > 1:
        return {"ok": False, "error": "WirePlumber did not confirm the requested volume."}
    return {"ok": True, "message": "Volume updated."}


def sound_mute(direction: str, muted: bool) -> dict[str, Any]:
    if direction not in {"output", "input"}:
        return {"ok": False, "error": "Invalid audio mute request."}
    executable = shutil.which("wpctl")
    if not executable:
        return {"ok": False, "error": "WirePlumber wpctl is unavailable."}
    target = "@DEFAULT_AUDIO_SINK@" if direction == "output" else "@DEFAULT_AUDIO_SOURCE@"
    before = _default_audio_state(target)
    if not before.get("available"):
        return {"ok": False, "error": before.get("error", "Default audio state is unavailable.")}
    code, out, err = run([executable, "set-mute", target, "1" if muted else "0"])
    if code != 0:
        return {"ok": False, "error": err or out or "WirePlumber rejected the mute request."}
    confirmed = _default_audio_state(target)
    if not confirmed.get("available") or bool(confirmed.get("muted")) != muted:
        return {"ok": False, "error": "WirePlumber did not confirm the requested mute state."}
    return {"ok": True, "message": "Mute state updated."}

_INPUT_SPECS: dict[str, tuple[str, type, float, float]] = {
    "repeatRate": ("input:repeat_rate", int, 1, 100),
    "repeatDelay": ("input:repeat_delay", int, 100, 2000),
    "sensitivity": ("input:sensitivity", float, -1.0, 1.0),
    "mouseNaturalScroll": ("input:natural_scroll", bool, 0, 1),
    "leftHanded": ("input:left_handed", bool, 0, 1),
    "naturalScroll": ("input:touchpad:natural_scroll", bool, 0, 1),
    "tapToClick": ("input:touchpad:tap-to-click", bool, 0, 1),
    "disableWhileTyping": ("input:touchpad:disable_while_typing", bool, 0, 1),
}
_INPUT_ENUMS: dict[str, tuple[str, set[str]]] = {
    "accelProfile": ("input:accel_profile", {"adaptive", "flat"}),
}
_INPUT_LUA_PATHS: dict[str, tuple[str, ...]] = {
    "input:repeat_rate": ("input", "repeat_rate"),
    "input:repeat_delay": ("input", "repeat_delay"),
    "input:sensitivity": ("input", "sensitivity"),
    "input:natural_scroll": ("input", "natural_scroll"),
    "input:left_handed": ("input", "left_handed"),
    "input:accel_profile": ("input", "accel_profile"),
    "input:touchpad:natural_scroll": ("input", "touchpad", "natural_scroll"),
    "input:touchpad:tap-to-click": ("input", "touchpad", "tap_to_click"),
    "input:touchpad:disable_while_typing": ("input", "touchpad", "disable_while_typing"),
    "input:kb_layout": ("input", "kb_layout"),
}


def _hypr_set_input_option(option: str, value: Any) -> tuple[bool, str]:
    path = _INPUT_LUA_PATHS.get(option)
    if path is None:
        return False, "Unsupported Hyprland input option."
    return _hypr_config(path, value)


def _hypr_set_device_input(device: str, option: str, value: Any) -> tuple[bool, str]:
    if option != "sensitivity":
        return False, "Unsupported per-device input option."
    if not isinstance(device, str) or not device or len(device) > 256:
        return False, "Invalid input device identity."
    try:
        expression = (
            "hl.device({ "
            f"name = {_lua_string(device)}, {option} = {_lua_value(value)}"
            " })"
        )
    except ValueError as exc:
        return False, str(exc)
    return hypr_eval(expression)


def _input_current() -> dict[str, Any]:
    accel = str(hypr_option("input:accel_profile", "") or "")
    if accel in {"", "[[EMPTY]]"}:
        accel = "default"
    return {
        "repeatRate": int(hypr_option("input:repeat_rate", 25) or 25),
        "repeatDelay": int(hypr_option("input:repeat_delay", 600) or 600),
        "sensitivity": float(hypr_option("input:sensitivity", 0.0) or 0.0),
        "mouseNaturalScroll": bool(hypr_option("input:natural_scroll", False)),
        "leftHanded": bool(hypr_option("input:left_handed", False)),
        "accelProfile": accel,
        "naturalScroll": bool(hypr_option("input:touchpad:natural_scroll", False)),
        "tapToClick": bool(hypr_option("input:touchpad:tap-to-click", True)),
        "disableWhileTyping": bool(hypr_option("input:touchpad:disable_while_typing", False)),
        "keyboardLayout": str(hypr_option("input:kb_layout", "") or ""),
    }


def snapshot_input() -> dict[str, Any]:
    payload, error = hypr_json(["devices", "-j"])
    if not isinstance(payload, dict):
        return {
            "available": False, "keyboards": [], "mice": [], "touchpads": [],
            "touchpadSpeeds": {}, "error": error or "Input state is unavailable.",
        }

    def rows(key: str) -> list[dict[str, Any]]:
        value = payload.get(key)
        return [row for row in value if isinstance(row, dict) and row.get("name")] if isinstance(value, list) else []

    def names(key: str) -> list[str]:
        return [str(row["name"]) for row in rows(key)]

    pointer_rows = rows("mice")
    pointer_names = [str(row["name"]) for row in pointer_rows]
    explicit_touchpads = names("touchpads")
    touchpads = explicit_touchpads or [
        name for name in pointer_names
        if re.search(r"(touchpad|trackpad)", name, flags=re.IGNORECASE)
    ]
    touchpad_set = set(touchpads)
    mice = [name for name in pointer_names if name not in touchpad_set]
    speed_rows = {
        str(row["name"]): float(row.get("defaultSpeed", 0.0) or 0.0)
        for row in [*pointer_rows, *rows("touchpads")]
        if str(row.get("name", "")) in touchpad_set
    }
    return {
        "available": True,
        "keyboards": names("keyboards"),
        "mice": mice,
        "touchpads": touchpads,
        "touchpadSpeeds": speed_rows,
        "current": _input_current(),
        "capabilities": {
            "accelerationProfile": True,
            "primaryButton": True,
            "mouseNaturalScroll": True,
            "touchpadSpeed": bool(touchpads),
        },
        "error": "",
    }


def _persist_input_value(key: str, value: Any) -> tuple[bool, str]:
    payload = read_json(INPUT_CONFIG)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        payload = {"version": 1, "values": {}, "devices": {}}
    values = payload.setdefault("values", {})
    if not isinstance(values, dict):
        return False, "Persisted input settings are invalid."
    if "devices" not in payload:
        payload["devices"] = {}
    values[key] = value
    atomic_json(INPUT_CONFIG, payload)
    return True, ""


def _persist_input_device_value(device: str, key: str, value: Any) -> tuple[bool, str]:
    payload = read_json(INPUT_CONFIG)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        payload = {"version": 1, "values": {}, "devices": {}}
    values = payload.setdefault("values", {})
    devices = payload.setdefault("devices", {})
    if not isinstance(values, dict) or not isinstance(devices, dict):
        return False, "Persisted input settings are invalid."
    row = devices.setdefault(device, {})
    if not isinstance(row, dict):
        return False, "Persisted per-device input settings are invalid."
    row[key] = value
    atomic_json(INPUT_CONFIG, payload)
    return True, ""


def _input_value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual is expected
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            return abs(float(actual) - float(expected)) <= 0.001
        except (TypeError, ValueError):
            return False
    return str(actual) == str(expected)


def input_set(key: str, value: Any, device: str = "") -> dict[str, Any]:
    if key == "touchpadSensitivity":
        try:
            normalized_speed = float(value)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid touchpad speed."}
        if not (-1.0 <= normalized_speed <= 1.0):
            return {"ok": False, "error": "Touchpad speed is outside the supported range."}
        current = snapshot_input()
        if not current.get("available") or device not in current.get("touchpads", []):
            return {"ok": False, "error": "The selected touchpad is no longer available."}
        ok, error = _hypr_set_device_input(device, "sensitivity", normalized_speed)
        if not ok:
            return {"ok": False, "error": error or "Hyprland rejected the touchpad speed."}
        confirmed = snapshot_input()
        actual_speed = (confirmed.get("touchpadSpeeds") or {}).get(device)
        if not confirmed.get("available") or not _input_value_matches(actual_speed, normalized_speed):
            return {"ok": False, "error": "Hyprland did not confirm the requested touchpad speed."}
        persisted, persist_error = _persist_input_device_value(device, "sensitivity", normalized_speed)
        if not persisted:
            return {"ok": False, "error": persist_error}
        return {"ok": True, "message": "Touchpad speed applied and persisted."}

    if key == "keyboardLayout":
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_+,-]{1,64}", value):
            return {"ok": False, "error": "Invalid keyboard layout."}
        option, normalized = "input:kb_layout", value
    elif key in _INPUT_ENUMS:
        option, allowed = _INPUT_ENUMS[key]
        if not isinstance(value, str) or value not in allowed:
            return {"ok": False, "error": "Unsupported input setting value."}
        normalized = value
    else:
        spec = _INPUT_SPECS.get(key)
        if spec is None:
            return {"ok": False, "error": "Unsupported input setting."}
        option, kind, low, high = spec
        if kind is bool:
            if not isinstance(value, bool):
                return {"ok": False, "error": "Input toggle must be boolean."}
            normalized = value
        else:
            try:
                normalized = kind(value)
            except (TypeError, ValueError):
                return {"ok": False, "error": "Invalid input setting value."}
            if not (low <= normalized <= high):
                return {"ok": False, "error": "Input setting is outside the supported range."}

    ok, error = _hypr_set_input_option(option, normalized)
    if not ok:
        return {"ok": False, "error": error or "Hyprland rejected the input setting."}
    confirmed = hypr_option(option, None)
    if not _input_value_matches(confirmed, normalized):
        return {"ok": False, "error": "Hyprland did not confirm the requested input setting."}
    persisted, persist_error = _persist_input_value(key, normalized)
    if not persisted:
        return {"ok": False, "error": persist_error}
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
        "sessionPolicyControlAvailable": False,
        "sessionPolicyError": "No supported user-scoped screen, suspend, or lid policy backend is available.",
        "error": "",
    }


def power_profile(profile_name: str) -> dict[str, Any]:
    available, _, profiles, error = _power_profiles()
    if not available or profile_name not in profiles:
        return {"ok": False, "error": error or "Unsupported power profile."}
    executable = shutil.which("powerprofilesctl")
    code, out, err = run([executable, "set", profile_name], timeout=5.0) if executable else (127, "", "powerprofilesctl unavailable")
    if code != 0:
        return {"ok": False, "message": "", "error": err or out or "Power-profile request was rejected."}
    confirmed, current, _, confirm_error = _power_profiles()
    if not confirmed or current != profile_name:
        return {"ok": False, "message": "", "error": confirm_error or "Power profile change could not be verified."}
    return {"ok": True, "message": "Power mode changed.", "error": ""}


def snapshot_notifications() -> dict[str, Any]:
    command = root_command("maho-notify")
    if not command:
        return {
            "available": False, "active": False, "dnd": False,
            "historyCount": 0, "unreadCount": 0,
            "globalEnableSupported": False, "soundPreferenceSupported": False,
            "lockScreenPreferenceSupported": False, "historyRetentionSupported": False,
            "historyClearSupported": False,
            "error": "Maho Notify is unavailable.",
        }
    code, out, err = run([command, "settings-status", "--json"], timeout=3.0)
    if not out:
        return {
            "available": False, "active": False, "dnd": False,
            "historyCount": 0, "unreadCount": 0,
            "globalEnableSupported": False, "soundPreferenceSupported": False,
            "lockScreenPreferenceSupported": False, "historyRetentionSupported": False,
            "historyClearSupported": False,
            "error": err or "Maho Notify status is unavailable.",
        }
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return {"available": False, "error": "Maho Notify returned invalid status."}
    if not isinstance(payload, dict):
        return {"available": False, "error": "Maho Notify returned invalid status."}
    return {
        "available": code == 0 or bool(payload),
        "active": bool(payload.get("active", False)),
        "dnd": bool(payload.get("dnd", False)),
        "adaptiveQuiet": bool(payload.get("adaptive_quiet", False)),
        "historyCount": int(payload.get("history_count", 0) or 0),
        "unreadCount": int(payload.get("unread_count", 0) or 0),
        "globalEnableSupported": True,
        "soundPreferenceSupported": False,
        "lockScreenPreferenceSupported": False,
        "historyRetentionSupported": False,
        "historyClearSupported": True,
        "error": "" if payload else (err or "Maho Notify status is unavailable."),
    }


def notification_enabled(enabled: bool) -> dict[str, Any]:
    command = root_command("maho-notify")
    if not command:
        return {"ok": False, "error": "Maho Notify is unavailable."}
    code, out, err = run([command, "start" if enabled else "stop"], timeout=8.0)
    if code != 0:
        return {"ok": False, "error": err or out or "Maho Notify rejected the enable request."}
    state = snapshot_notifications()
    if not state.get("available") or bool(state.get("active")) != enabled:
        return {"ok": False, "error": "Maho Notify did not confirm the requested enabled state."}
    return {"ok": True, "message": "Notification service updated.", "state": state}


def notification_dnd(enabled: bool) -> dict[str, Any]:
    command = root_command("maho-notify")
    if not command:
        return {"ok": False, "error": "Maho Notify is unavailable."}
    code, out, err = run([command, "dnd", "on" if enabled else "off"], timeout=6.0)
    if code != 0:
        return {"ok": False, "error": err or out or "Maho Notify rejected the DND request."}
    state = snapshot_notifications()
    if not state.get("available") or bool(state.get("dnd")) != enabled:
        return {"ok": False, "error": "Maho Notify did not confirm the requested DND state."}
    return {"ok": True, "message": "Do Not Disturb updated.", "state": state}


def notification_clear_history() -> dict[str, Any]:
    command = root_command("maho-notify")
    if not command:
        return {"ok": False, "error": "Maho Notify is unavailable."}
    code, out, err = run([command, "history", "clear"], timeout=6.0)
    if code != 0:
        return {"ok": False, "error": err or out or "Maho Notify could not clear history."}
    state = snapshot_notifications()
    if not state.get("available") or int(state.get("historyCount", 0)) != 0:
        return {"ok": False, "error": "Maho Notify did not confirm that history was cleared."}
    return {"ok": True, "message": "Notification history cleared.", "state": state}


def _timedate_state() -> tuple[dict[str, str], str]:
    executable = shutil.which("timedatectl")
    if not executable:
        return {}, "systemd timedatectl is unavailable."
    code, out, err = run([
        executable, "show", "--no-pager",
        "--property=Timezone", "--property=NTP", "--property=NTPSynchronized",
    ], timeout=4.0)
    if code != 0:
        return {}, err or out or "Time state is unavailable."
    values: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values, ""


def _command_list(args: list[str], *, timeout: float = 5.0) -> list[str]:
    code, out, _ = run(args, timeout=timeout)
    return [line.strip() for line in out.splitlines() if line.strip()] if code == 0 else []


def _system_locale() -> tuple[str, str]:
    executable = shutil.which("localectl")
    if not executable:
        return "", "systemd localectl is unavailable."
    code, out, err = run([executable, "status", "--no-pager"], timeout=4.0)
    if code != 0:
        return "", err or out or "Locale state is unavailable."
    match = re.search(r"(?m)^\s*System Locale:\s+.*?\bLANG=([^\s]+)", out)
    return (match.group(1) if match else ""), ""


def snapshot_region() -> dict[str, Any]:
    time_state, time_error = _timedate_state()
    locale_value, locale_error = _system_locale()
    timedate = shutil.which("timedatectl")
    localectl = shutil.which("localectl")
    timezones = _command_list([timedate, "list-timezones", "--no-pager"], timeout=5.0) if timedate else []
    locales = _command_list([shutil.which("locale") or "locale", "-a"], timeout=4.0)
    if locale_value and locale_value not in locales:
        locales.insert(0, locale_value)
    layouts = _command_list([localectl, "list-x11-keymap-layouts", "--no-pager"], timeout=5.0) if localectl else []
    keyboard_layout = str(_input_current().get("keyboardLayout", ""))
    if keyboard_layout and keyboard_layout not in layouts:
        layouts.insert(0, keyboard_layout)
    return {
        "available": bool(time_state) or bool(locale_value),
        "timezone": time_state.get("Timezone", ""),
        "automaticTime": time_state.get("NTP", "").lower() == "yes",
        "timeSynchronized": time_state.get("NTPSynchronized", "").lower() == "yes",
        "timezoneControlAvailable": timedate is not None,
        "automaticTimeControlAvailable": timedate is not None,
        "timezones": timezones,
        "locale": locale_value,
        "localeControlAvailable": localectl is not None,
        "locales": locales,
        "keyboardLayout": keyboard_layout,
        "keyboardLayoutControlAvailable": hypr_prefix()[0] is not None and bool(layouts),
        "keyboardLayouts": layouts,
        "error": time_error or locale_error,
    }


def region_timezone(value: str) -> dict[str, Any]:
    executable = shutil.which("timedatectl")
    if not executable:
        return {"ok": False, "error": "systemd timedatectl is unavailable."}
    allowed = _command_list([executable, "list-timezones", "--no-pager"], timeout=5.0)
    if value not in allowed:
        return {"ok": False, "error": "Unknown time zone."}
    code, out, err = run([executable, "set-timezone", value], timeout=12.0)
    if code != 0:
        return {"ok": False, "error": err or out or "The time-zone request was rejected."}
    current, state_error = _timedate_state()
    if current.get("Timezone") != value:
        return {"ok": False, "error": state_error or "The time-zone change could not be verified."}
    return {"ok": True, "message": "Time zone updated."}


def region_automatic_time(enabled: bool) -> dict[str, Any]:
    executable = shutil.which("timedatectl")
    if not executable:
        return {"ok": False, "error": "systemd timedatectl is unavailable."}
    code, out, err = run([executable, "set-ntp", "true" if enabled else "false"], timeout=12.0)
    if code != 0:
        return {"ok": False, "error": err or out or "The automatic-time request was rejected."}
    current, state_error = _timedate_state()
    if (current.get("NTP", "").lower() == "yes") != enabled:
        return {"ok": False, "error": state_error or "The automatic-time change could not be verified."}
    return {"ok": True, "message": "Automatic time updated."}


def region_locale(value: str) -> dict[str, Any]:
    executable = shutil.which("localectl")
    if not executable:
        return {"ok": False, "error": "systemd localectl is unavailable."}
    allowed = _command_list([shutil.which("locale") or "locale", "-a"], timeout=4.0)
    if value not in allowed:
        return {"ok": False, "error": "Unknown locale."}
    code, out, err = run([executable, "set-locale", f"LANG={value}"], timeout=12.0)
    if code != 0:
        return {"ok": False, "error": err or out or "The locale request was rejected."}
    current, state_error = _system_locale()
    if current != value:
        return {"ok": False, "error": state_error or "The locale change could not be verified."}
    return {"ok": True, "message": "System locale updated."}


_COMMON_MIME_ASSOCIATIONS: tuple[tuple[str, str], ...] = (
    ("application/pdf", "PDF documents"),
    ("text/plain", "Text files"),
    ("image/png", "PNG images"),
    ("image/jpeg", "JPEG images"),
    ("video/mp4", "MP4 video"),
    ("audio/mpeg", "MP3 audio"),
    ("x-scheme-handler/mailto", "Email links"),
)


def _desktop_entry(path: Path) -> dict[str, Any]:
    fields: dict[str, str] = {}
    in_desktop = False
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                in_desktop = line == "[Desktop Entry]"
                continue
            if not in_desktop or "=" not in line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            if key in {"Type", "Name", "Exec", "MimeType", "Categories", "Hidden", "NoDisplay"}:
                fields[key] = value
    except OSError:
        return {}
    if fields.get("Type", "Application") != "Application":
        return {}
    return {
        "id": path.name,
        "name": fields.get("Name", path.stem),
        "exec": fields.get("Exec", ""),
        "mimes": [item for item in fields.get("MimeType", "").split(";") if item],
        "categories": [item for item in fields.get("Categories", "").split(";") if item],
        "hidden": fields.get("Hidden", "").lower() == "true",
        "noDisplay": fields.get("NoDisplay", "").lower() == "true",
    }


def _application_entries() -> dict[str, dict[str, Any]]:
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    data_dirs = [Path(item) for item in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if item]
    result: dict[str, dict[str, Any]] = {}
    for directory in [data_home, *data_dirs]:
        app_dir = directory / "applications"
        if not app_dir.is_dir():
            continue
        for path in sorted(app_dir.glob("*.desktop")):
            if path.name in result:
                continue
            row = _desktop_entry(path)
            if row:
                result[path.name] = row
    return result


def _xdg_default(mime: str) -> str:
    executable = shutil.which("xdg-mime")
    if not executable:
        return ""
    code, out, _ = run([executable, "query", "default", mime], timeout=3.0)
    return out.strip() if code == 0 else ""


def _app_candidates(entries: dict[str, dict[str, Any]], wanted: set[str]) -> list[dict[str, str]]:
    rows = []
    for row in entries.values():
        if row.get("hidden") or row.get("noDisplay"):
            continue
        if wanted.intersection(set(row.get("mimes", []))):
            rows.append({"id": row["id"], "name": row["name"]})
    rows.sort(key=lambda item: (item["name"].lower(), item["id"]))
    return rows


def _autostart_entries() -> list[dict[str, Any]]:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    config_dirs = [Path(item) for item in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":") if item]
    rows: dict[str, dict[str, Any]] = {}
    for source, directory in [("user", config_home), *[("system", item) for item in config_dirs]]:
        autostart = directory / "autostart"
        if not autostart.is_dir():
            continue
        for path in sorted(autostart.glob("*.desktop")):
            if path.name in rows:
                continue
            entry = _desktop_entry(path)
            if not entry:
                continue
            rows[path.name] = {
                "id": path.name,
                "name": entry.get("name", path.stem),
                "enabled": not entry.get("hidden", False),
                "source": source,
            }
    return sorted(rows.values(), key=lambda item: (item["name"].lower(), item["id"]))[:250]


def snapshot_applications() -> dict[str, Any]:
    entries = _application_entries()
    browser_mimes = {"x-scheme-handler/http", "x-scheme-handler/https", "text/html"}
    file_mimes = {"inode/directory"}
    browser_candidates = _app_candidates(entries, browser_mimes)
    file_candidates = _app_candidates(entries, file_mimes)
    browser = _xdg_default("x-scheme-handler/http") or _xdg_default("text/html")
    file_manager = _xdg_default("inode/directory")
    associations = []
    for mime, label in _COMMON_MIME_ASSOCIATIONS:
        candidates = _app_candidates(entries, {mime})
        current = _xdg_default(mime)
        if current or candidates:
            associations.append({
                "mime": mime,
                "label": label,
                "default": current,
                "candidates": candidates,
            })
    return {
        "available": shutil.which("xdg-mime") is not None,
        "browser": browser,
        "browserCandidates": browser_candidates,
        "fileManager": file_manager,
        "fileManagerCandidates": file_candidates,
        "mimeAssociations": associations,
        "terminalControlAvailable": False,
        "terminal": "",
        "terminalError": "No supported xdg-terminal-exec/default-terminal authority is installed.",
        "autostart": _autostart_entries(),
        "error": "" if shutil.which("xdg-mime") else "xdg-mime is unavailable.",
    }


def application_default(kind: str, desktop_id: str) -> dict[str, Any]:
    executable = shutil.which("xdg-mime")
    if not executable:
        return {"ok": False, "error": "xdg-mime is unavailable."}
    entries = _application_entries()
    if kind == "browser":
        mimes = ["x-scheme-handler/http", "x-scheme-handler/https", "text/html"]
        candidates = {row["id"] for row in _app_candidates(entries, set(mimes))}
    elif kind == "fileManager":
        mimes = ["inode/directory"]
        candidates = {row["id"] for row in _app_candidates(entries, set(mimes))}
    else:
        return {"ok": False, "error": "Unsupported default-application kind."}
    if desktop_id not in candidates:
        return {"ok": False, "error": "The selected application does not advertise support for this default."}

    before = {mime: _xdg_default(mime) for mime in mimes}
    changed: list[str] = []
    for mime in mimes:
        code, out, err = run([executable, "default", desktop_id, mime], timeout=5.0)
        if code != 0:
            for rollback_mime in reversed(changed):
                previous = before.get(rollback_mime)
                if previous:
                    run([executable, "default", previous, rollback_mime], timeout=5.0)
            return {"ok": False, "error": err or out or "The default-application request was rejected."}
        changed.append(mime)
    if any(_xdg_default(mime) != desktop_id for mime in mimes):
        for mime, previous in before.items():
            if previous:
                run([executable, "default", previous, mime], timeout=5.0)
        return {"ok": False, "error": "The default application change could not be verified and was rolled back."}
    return {"ok": True, "message": "Default application updated."}


def application_mime_default(mime: str, desktop_id: str) -> dict[str, Any]:
    allowed = {item[0] for item in _COMMON_MIME_ASSOCIATIONS}
    if mime not in allowed:
        return {"ok": False, "error": "Unsupported MIME association."}
    executable = shutil.which("xdg-mime")
    if not executable:
        return {"ok": False, "error": "xdg-mime is unavailable."}
    entries = _application_entries()
    candidates = {row["id"] for row in _app_candidates(entries, {mime})}
    if desktop_id not in candidates:
        return {"ok": False, "error": "The selected application does not advertise support for this MIME type."}
    previous = _xdg_default(mime)
    code, out, err = run([executable, "default", desktop_id, mime], timeout=5.0)
    if code != 0:
        return {"ok": False, "error": err or out or "The MIME association request was rejected."}
    if _xdg_default(mime) != desktop_id:
        if previous:
            run([executable, "default", previous, mime], timeout=5.0)
        return {"ok": False, "error": "The MIME association change could not be verified and was rolled back."}
    return {"ok": True, "message": "Default association updated."}


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


_MODIFIER_BITS = (
    (64, "Super"),
    (4, "Ctrl"),
    (8, "Alt"),
    (1, "Shift"),
    (16, "Mod2"),
    (32, "Mod3"),
    (128, "Mod5"),
)


def _shortcut_chord(row: dict[str, Any]) -> str:
    mask = int(row.get("modmask", 0) or 0)
    parts = [label for bit, label in _MODIFIER_BITS if mask & bit]
    key = str(row.get("key", "") or "").strip()
    if not key:
        code = int(row.get("keycode", 0) or 0)
        key = f"Keycode {code}" if code else "Unknown key"
    parts.append(key)
    return " + ".join(parts)


def _shortcut_identity(chord: str) -> str:
    return " + ".join(
        part.strip().casefold()
        for part in chord.split("+")
        if part.strip()
    )


def _managed_hypr_model() -> tuple[dict[str, Any] | None, str]:
    try:
        return hypr_config_writer.load_model(), ""
    except hypr_config_writer.ConfigWriteError as exc:
        return None, str(exc)


def _shortcut_collection_has(
    collection: dict[str, Any],
    chord: str,
    *,
    command: str | None = None,
    submap: str = "",
) -> bool:
    for raw in collection.get("binds", []):
        if not isinstance(raw, dict):
            continue
        if _shortcut_identity(str(raw.get("keys", "") or "")) != _shortcut_identity(chord):
            continue
        if str(raw.get("submap", "") or "") != submap:
            continue
        if command is not None and str(raw.get("command", "") or "") != command:
            continue
        return True
    return False


def shortcut_upsert(
    chord: str,
    command: str,
    description: str = "",
    *,
    submap: str = "",
    original_chord: str = "",
    original_submap: str = "",
    replace_existing: bool = False,
) -> dict[str, Any]:
    chord = chord.strip()
    command = command.strip()
    submap = submap.strip()
    original_chord = original_chord.strip()
    original_submap = original_submap.strip()
    if not chord:
        return {"ok": False, "error": "Shortcut chord cannot be empty."}
    if not command:
        return {"ok": False, "error": "Shortcut command cannot be empty."}
    if not isinstance(description, str):
        return {"ok": False, "error": "Shortcut description must be text."}

    collection, collection_error = _collect_hypr_config()
    if not isinstance(collection, dict) or collection_error:
        return {
            "ok": False,
            "error": collection_error or "Current shortcut configuration cannot be verified.",
        }

    conflict = _shortcut_collection_has(collection, chord, submap=submap)
    same_target = bool(original_chord) and (
        _shortcut_identity(original_chord) == _shortcut_identity(chord)
        and original_submap == submap
    )
    if conflict and not same_target and not replace_existing:
        scope = f" in submap {submap}" if submap else ""
        return {
            "ok": False,
            "error": f"{chord} is already assigned{scope}. Choose Override to replace it.",
        }

    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed shortcut state is unavailable."}

    preserved_id = ""
    if original_chord:
        for row in model.get("binds", []):
            if (
                isinstance(row, dict)
                and str(row.get("submap", "") or "") == original_submap
                and _shortcut_identity(str(row.get("keys", "") or "")) == _shortcut_identity(original_chord)
            ):
                preserved_id = str(row.get("id", "") or "")
                break
        model["binds"] = [
            row
            for row in model.get("binds", [])
            if not (
                isinstance(row, dict)
                and str(row.get("submap", "") or "") == original_submap
                and _shortcut_identity(str(row.get("keys", "") or "")) == _shortcut_identity(original_chord)
            )
        ]
        if original_submap != submap or _shortcut_identity(original_chord) != _shortcut_identity(chord):
            model["unbinds"] = [
                row
                for row in model.get("unbinds", [])
                if not (
                    isinstance(row, dict)
                    and str(row.get("submap", "") or "") == original_submap
                    and _shortcut_identity(str(row.get("keys", "") or "")) == _shortcut_identity(original_chord)
                )
            ]

    model["binds"] = [
        row
        for row in model.get("binds", [])
        if not (
            isinstance(row, dict)
            and str(row.get("submap", "") or "") == submap
            and _shortcut_identity(str(row.get("keys", "") or "")) == _shortcut_identity(chord)
        )
    ]

    if conflict or same_target or replace_existing:
        if not any(
            isinstance(row, dict)
            and str(row.get("submap", "") or "") == submap
            and _shortcut_identity(str(row.get("keys", "") or "")) == _shortcut_identity(chord)
            for row in model.get("unbinds", [])
        ):
            model.setdefault("unbinds", []).append({"keys": chord, "submap": submap})

    model.setdefault("binds", []).append({
        "id": preserved_id or str(uuid.uuid4()),
        "keys": chord,
        "command": command,
        "description": description.strip(),
        "submap": submap,
        "flags": [],
    })

    ok, _, apply_error = _apply_managed_hypr_model(
        model,
        verify=lambda observed: _shortcut_collection_has(
            observed, chord, command=command, submap=submap
        ),
    )
    if not ok:
        return {"ok": False, "error": apply_error}

    return {
        "ok": True,
        "message": "Shortcut updated.",
        "state": snapshot_shortcuts(),
    }


def shortcut_disable(chord: str, submap: str = "") -> dict[str, Any]:
    chord = chord.strip()
    submap = submap.strip()
    if not chord:
        return {"ok": False, "error": "Shortcut chord cannot be empty."}

    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed shortcut state is unavailable."}

    model["binds"] = [
        row
        for row in model.get("binds", [])
        if not (
            isinstance(row, dict)
            and str(row.get("submap", "") or "") == submap
            and _shortcut_identity(str(row.get("keys", "") or "")) == _shortcut_identity(chord)
        )
    ]
    if not any(
        isinstance(row, dict)
        and str(row.get("submap", "") or "") == submap
        and _shortcut_identity(str(row.get("keys", "") or "")) == _shortcut_identity(chord)
        for row in model.get("unbinds", [])
    ):
        model.setdefault("unbinds", []).append({"keys": chord, "submap": submap})

    ok, _, apply_error = _apply_managed_hypr_model(
        model,
        verify=lambda observed: not _shortcut_collection_has(observed, chord, submap=submap),
    )
    if not ok:
        return {"ok": False, "error": apply_error}
    return {
        "ok": True,
        "message": "Shortcut disabled.",
        "state": snapshot_shortcuts(),
    }


def shortcut_reset(chord: str, submap: str = "") -> dict[str, Any]:
    chord = chord.strip()
    submap = submap.strip()
    if not chord:
        return {"ok": False, "error": "Shortcut chord cannot be empty."}

    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed shortcut state is unavailable."}

    model["binds"] = [
        row
        for row in model.get("binds", [])
        if not (
            isinstance(row, dict)
            and str(row.get("submap", "") or "") == submap
            and _shortcut_identity(str(row.get("keys", "") or "")) == _shortcut_identity(chord)
        )
    ]
    model["unbinds"] = [
        row
        for row in model.get("unbinds", [])
        if not (
            isinstance(row, dict)
            and str(row.get("submap", "") or "") == submap
            and _shortcut_identity(str(row.get("keys", "") or "")) == _shortcut_identity(chord)
        )
    ]

    writer = hypr_config_writer.status()

    def verified(observed: dict[str, Any]) -> bool:
        for raw in observed.get("binds", []):
            if not isinstance(raw, dict):
                continue
            if _shortcut_identity(str(raw.get("keys", "") or "")) != _shortcut_identity(chord):
                continue
            if str(raw.get("submap", "") or "") != submap:
                continue
            if _writer_source_is_overlay(str(raw.get("source_file", "") or ""), writer):
                return False
        return True

    ok, _, apply_error = _apply_managed_hypr_model(model, verify=verified)
    if not ok:
        return {"ok": False, "error": apply_error}
    return {
        "ok": True,
        "message": "Shortcut restored to the underlying configuration.",
        "state": snapshot_shortcuts(),
    }

def snapshot_shortcuts() -> dict[str, Any]:
    collection, collection_error = _collect_hypr_config()
    live_payload, live_error = hypr_json(["binds", "-j"])
    if not isinstance(collection, dict):
        return {
            "available": False,
            "binds": [],
            "count": 0,
            "mutationAvailable": False,
            "readOnly": True,
            "error": collection_error or live_error or "Shortcut state is unavailable.",
        }

    writer = hypr_config_writer.status()
    prefix, _ = hypr_prefix()
    mutation_available = (
        bool(writer.get("mutationAvailable"))
        and prefix is not None
        and not bool(collection_error)
    )
    overlay_path = Path(str(writer.get("path", "") or ""))
    try:
        overlay_resolved = overlay_path.resolve(strict=False) if str(overlay_path) else None
    except OSError:
        overlay_resolved = None

    live_identities: set[tuple[str, str]] = set()
    if isinstance(live_payload, list):
        for raw in live_payload:
            if not isinstance(raw, dict):
                continue
            live_identities.add((
                str(raw.get("submap", "") or ""),
                _shortcut_identity(_shortcut_chord(raw)),
            ))

    binds = []
    for index, raw in enumerate(collection.get("binds", [])):
        if not isinstance(raw, dict):
            continue
        chord = str(raw.get("keys", "") or "").strip()
        if not chord:
            continue
        submap = str(raw.get("submap", "") or "")
        command = str(raw.get("command", "") or "")
        action = str(raw.get("action", "") or "")
        description = str(raw.get("description", "") or "").strip()
        source_file = str(raw.get("source_file", "") or "")
        source_line = int(raw.get("source_line", 0) or 0)
        flags = [
            str(flag)
            for flag in raw.get("flags", [])
            if isinstance(flag, str)
        ]
        try:
            source_resolved = Path(source_file).resolve(strict=False) if source_file else None
        except OSError:
            source_resolved = None
        user_owned = (
            overlay_resolved is not None
            and source_resolved is not None
            and source_resolved == overlay_resolved
        )
        bind_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"maho-shortcut:{source_file}:{source_line}:{submap}:{chord}:{index}",
        ))
        binds.append({
            "id": bind_id,
            "chord": chord,
            "command": command,
            "action": action,
            "description": description or command or action or "Shortcut action",
            "submap": submap,
            "repeat": "repeating" in flags,
            "mouse": "mouse" in flags,
            "locked": "locked" in flags,
            "flags": flags,
            "sourceFile": source_file,
            "sourceLine": source_line,
            "userOwned": user_owned,
            "canOverride": mutation_available,
            "canDelete": mutation_available and user_owned,
            "live": (submap, _shortcut_identity(chord)) in live_identities if live_identities else True,
        })

    collected_identities = {
        (str(row.get("submap", "") or ""), _shortcut_identity(str(row.get("chord", "") or "")))
        for row in binds
    }
    if isinstance(live_payload, list):
        for index, raw in enumerate(live_payload):
            if not isinstance(raw, dict):
                continue
            chord = _shortcut_chord(raw)
            submap = str(raw.get("submap", "") or "")
            identity = (submap, _shortcut_identity(chord))
            if identity in collected_identities:
                continue
            dispatcher = str(raw.get("dispatcher", "") or "")
            description = str(raw.get("description", "") or "").strip()
            binds.append({
                "id": str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"maho-live-shortcut:{submap}:{chord}:{index}",
                )),
                "chord": chord,
                "command": "",
                "action": dispatcher,
                "description": description or (
                    "Managed Maho action" if dispatcher == "__lua"
                    else dispatcher.replace("_", " ").strip() or "Shortcut action"
                ),
                "submap": submap,
                "repeat": bool(raw.get("repeat", False)),
                "mouse": bool(raw.get("mouse", False)),
                "locked": bool(raw.get("locked", False)),
                "flags": [],
                "sourceFile": "",
                "sourceLine": 0,
                "userOwned": False,
                "canOverride": mutation_available,
                "canDelete": False,
                "live": True,
            })
            collected_identities.add(identity)

    binds.sort(key=lambda row: (
        str(row["submap"]).lower(),
        str(row["chord"]).lower(),
        str(row["description"]).lower(),
    ))
    return {
        "available": True,
        "binds": binds,
        "count": len(binds),
        "mutationAvailable": mutation_available,
        "readOnly": not mutation_available,
        "writerReady": bool(writer.get("mutationAvailable")),
        "collectionError": collection_error,
        "liveError": live_error,
        "error": collection_error or "",
    }


def snapshot_motion() -> dict[str, Any]:
    payload, error = hypr_json(["animations", "-j"])
    if not isinstance(payload, list) or len(payload) < 2:
        return {
            "available": False,
            "animations": [],
            "curves": [],
            "mutationAvailable": False,
            "readOnly": True,
            "error": error or "Motion state is unavailable.",
        }

    collection, collection_error = _collect_hypr_config()
    writer = hypr_config_writer.status()
    prefix, _ = hypr_prefix()
    mutation_available = (
        bool(writer.get("mutationAvailable"))
        and prefix is not None
        and not bool(collection_error)
    )
    overlay = Path(str(writer.get("path", "") or ""))
    try:
        overlay_resolved = overlay.resolve(strict=False) if str(overlay) else None
    except OSError:
        overlay_resolved = None

    animation_sources: dict[str, dict[str, Any]] = {}
    curve_sources: dict[str, dict[str, Any]] = {}
    if isinstance(collection, dict):
        for raw in collection.get("animations", []):
            if not isinstance(raw, dict):
                continue
            fields = raw.get("fields", {})
            if not isinstance(fields, dict):
                continue
            leaf = str(fields.get("leaf", "") or raw.get("name", "") or "")
            if leaf:
                animation_sources[leaf] = raw
        for raw in collection.get("curves", []):
            if isinstance(raw, dict):
                name = str(raw.get("name", "") or "")
                if name:
                    curve_sources[name] = raw

    def source_meta(raw: dict[str, Any] | None) -> tuple[str, int, bool]:
        if not isinstance(raw, dict):
            return "", 0, False
        source_file = str(raw.get("source_file", "") or "")
        source_line = int(raw.get("source_line", 0) or 0)
        try:
            source_resolved = Path(source_file).resolve(strict=False) if source_file else None
        except OSError:
            source_resolved = None
        user_owned = (
            overlay_resolved is not None
            and source_resolved is not None
            and source_resolved == overlay_resolved
        )
        return source_file, source_line, user_owned

    raw_animations = payload[0] if isinstance(payload[0], list) else []
    raw_curves = payload[1] if isinstance(payload[1], list) else []
    animations = []
    for raw in raw_animations:
        if not isinstance(raw, dict) or not bool(raw.get("overridden", False)):
            continue
        name = str(raw.get("name", ""))
        source_file, source_line, user_owned = source_meta(animation_sources.get(name))
        animations.append({
            "name": name,
            "enabled": bool(raw.get("enabled", False)),
            "speed": float(raw.get("speed", 0.0) or 0.0),
            "curve": str(raw.get("bezier", "") or "default"),
            "style": str(raw.get("style", "") or ""),
            "sourceFile": source_file,
            "sourceLine": source_line,
            "userOwned": user_owned,
            "canOverride": mutation_available,
            "canDelete": mutation_available and user_owned,
        })
    curves = []
    for raw in raw_curves:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", ""))
        source_file, source_line, user_owned = source_meta(curve_sources.get(name))
        curves.append({
            "name": name,
            "x0": float(raw.get("X0", 0.0) or 0.0),
            "y0": float(raw.get("Y0", 0.0) or 0.0),
            "x1": float(raw.get("X1", 0.0) or 0.0),
            "y1": float(raw.get("Y1", 0.0) or 0.0),
            "sourceFile": source_file,
            "sourceLine": source_line,
            "userOwned": user_owned,
            "canOverride": mutation_available and name != "default",
            "canDelete": mutation_available and user_owned,
        })
    animations.sort(key=lambda row: row["name"].lower())
    curves.sort(key=lambda row: row["name"].lower())
    return {
        "available": True,
        "animations": animations,
        "curves": curves,
        "mutationAvailable": mutation_available,
        "readOnly": not mutation_available,
        "collectionError": collection_error,
        "error": collection_error or "",
    }


def _rule_collection_has(
    collection: dict[str, Any],
    *,
    kind: str,
    name: str,
    match: dict[str, Any],
    effects: dict[str, Any],
    require_overlay: bool = False,
) -> bool:
    key = "window_rules" if kind == "window" else "layer_rules"
    writer = hypr_config_writer.status()
    for raw in collection.get(key, []):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("name", "") or "") != name:
            continue
        if (raw.get("match", {}) if isinstance(raw.get("match"), dict) else {}) != match:
            continue
        if (raw.get("effects", {}) if isinstance(raw.get("effects"), dict) else {}) != effects:
            continue
        if require_overlay and not _writer_source_is_overlay(
            str(raw.get("source_file", "") or ""), writer
        ):
            continue
        return True
    return False


def rule_upsert(
    kind: str,
    name: str,
    match: dict[str, Any],
    effects: dict[str, Any],
    *,
    rule_id: str = "",
) -> dict[str, Any]:
    if kind not in {"window", "layer"}:
        return {"ok": False, "error": "Only window and layer rules are writable in this Settings version."}
    name = name.strip()
    if not name:
        return {"ok": False, "error": "Rule name cannot be empty."}
    if not isinstance(match, dict) or not match:
        return {"ok": False, "error": "Rule match must contain at least one condition."}
    if not isinstance(effects, dict) or not effects:
        return {"ok": False, "error": "Rule must contain at least one effect."}

    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed rule state is unavailable."}

    key = "windowRules" if kind == "window" else "layerRules"
    rows = [row for row in model.get(key, []) if isinstance(row, dict)]
    preserved_id = ""
    if rule_id:
        existing = next((row for row in rows if str(row.get("id", "")) == rule_id), None)
        if existing is None:
            return {
                "ok": False,
                "error": "Only Maho-owned custom rules can be edited. System rules remain read-only.",
            }
        preserved_id = rule_id
        rows = [row for row in rows if str(row.get("id", "")) != rule_id]

    if any(str(row.get("name", "") or "") == name for row in rows):
        return {"ok": False, "error": f"A managed {kind} rule named {name!r} already exists."}

    rows.append({
        "id": preserved_id or str(uuid.uuid4()),
        "name": name,
        "match": match,
        "effects": effects,
    })
    model[key] = rows

    ok, _, apply_error = _apply_managed_hypr_model(
        model,
        verify=lambda observed: _rule_collection_has(
            observed,
            kind=kind,
            name=name,
            match=match,
            effects=effects,
            require_overlay=True,
        ),
    )
    if not ok:
        return {"ok": False, "error": apply_error}
    return {
        "ok": True,
        "message": f"{kind.capitalize()} rule updated.",
        "state": snapshot_rules(),
    }


def rule_delete(kind: str, rule_id: str) -> dict[str, Any]:
    if kind not in {"window", "layer"}:
        return {"ok": False, "error": "Only window and layer rules are writable in this Settings version."}
    rule_id = rule_id.strip()
    if not rule_id:
        return {"ok": False, "error": "Managed rule identity is required."}

    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed rule state is unavailable."}

    key = "windowRules" if kind == "window" else "layerRules"
    rows = [row for row in model.get(key, []) if isinstance(row, dict)]
    existing = next((row for row in rows if str(row.get("id", "")) == rule_id), None)
    if existing is None:
        return {"ok": False, "error": "System rules cannot be deleted from Maho Settings."}

    name = str(existing.get("name", "") or "")
    match = existing.get("match", {}) if isinstance(existing.get("match"), dict) else {}
    effects = existing.get("effects", {}) if isinstance(existing.get("effects"), dict) else {}
    model[key] = [row for row in rows if str(row.get("id", "")) != rule_id]

    ok, _, apply_error = _apply_managed_hypr_model(
        model,
        verify=lambda observed: not _rule_collection_has(
            observed,
            kind=kind,
            name=name,
            match=match,
            effects=effects,
            require_overlay=True,
        ),
    )
    if not ok:
        return {"ok": False, "error": apply_error}
    return {
        "ok": True,
        "message": f"{kind.capitalize()} rule removed.",
        "state": snapshot_rules(),
    }


def _workspace_rule_collection_has(
    collection: dict[str, Any],
    fields: dict[str, Any],
    *,
    require_overlay: bool = False,
) -> bool:
    writer = hypr_config_writer.status()
    for raw in collection.get("workspace_rules", []):
        if not isinstance(raw, dict):
            continue
        observed = raw.get("fields", {}) if isinstance(raw.get("fields"), dict) else {}
        if observed != fields:
            continue
        if require_overlay and not _writer_source_is_overlay(
            str(raw.get("source_file", "") or ""), writer
        ):
            continue
        return True
    return False


def workspace_rule_upsert(
    fields: dict[str, Any],
    *,
    original_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(fields, dict) or not fields:
        return {"ok": False, "error": "Workspace rule fields cannot be empty."}

    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed workspace-rule state is unavailable."}
    rows = [row for row in model.get("workspaceRules", []) if isinstance(row, dict)]
    if original_fields is not None:
        if not isinstance(original_fields, dict) or not original_fields:
            return {"ok": False, "error": "Original workspace rule is invalid."}
        before = len(rows)
        rows = [row for row in rows if row != original_fields]
        if len(rows) == before:
            return {"ok": False, "error": "Only Maho-owned workspace rules can be edited."}
    if any(row == fields for row in rows):
        return {"ok": False, "error": "That managed workspace rule already exists."}
    rows.append(dict(fields))
    model["workspaceRules"] = rows

    ok, _, apply_error = _apply_managed_hypr_model(
        model,
        verify=lambda observed: _workspace_rule_collection_has(
            observed, fields, require_overlay=True
        ),
    )
    if not ok:
        return {"ok": False, "error": apply_error}
    return {"ok": True, "message": "Workspace rule updated.", "state": snapshot_rules()}


def workspace_rule_delete(fields: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(fields, dict) or not fields:
        return {"ok": False, "error": "Workspace rule identity is missing."}
    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed workspace-rule state is unavailable."}
    rows = [row for row in model.get("workspaceRules", []) if isinstance(row, dict)]
    before = len(rows)
    rows = [row for row in rows if row != fields]
    if len(rows) == before:
        return {"ok": False, "error": "System workspace rules cannot be deleted from Maho Settings."}
    model["workspaceRules"] = rows
    ok, _, apply_error = _apply_managed_hypr_model(
        model,
        verify=lambda observed: not _workspace_rule_collection_has(
            observed, fields, require_overlay=True
        ),
    )
    if not ok:
        return {"ok": False, "error": apply_error}
    return {"ok": True, "message": "Workspace rule removed.", "state": snapshot_rules()}


def _startup_collection_has(
    collection: dict[str, Any],
    *,
    command: str,
    when: str,
    workspace: str,
    require_overlay: bool = False,
) -> bool:
    writer = hypr_config_writer.status()
    for raw in collection.get("startup", []):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("command", "") or "") != command:
            continue
        if str(raw.get("when", "") or "") != when:
            continue
        if str(raw.get("workspace", "") or "") != workspace:
            continue
        if require_overlay and not _writer_source_is_overlay(
            str(raw.get("source_file", "") or ""), writer
        ):
            continue
        return True
    return False


def session_startup_upsert(
    command: str,
    when: str,
    workspace: str = "",
    *,
    startup_id: str = "",
) -> dict[str, Any]:
    command = command.strip()
    when = when.strip().lower()
    workspace = workspace.strip()
    if not command:
        return {"ok": False, "error": "Startup command cannot be empty."}
    # Top-level reload entries execute on every unrelated config reload, which
    # is too broad an authority for Settings. Keep user startup lifecycle-bound.
    if when not in {"start", "shutdown"}:
        return {"ok": False, "error": "Managed session commands may run only at login or shutdown."}

    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed session state is unavailable."}

    rows = [row for row in model.get("startup", []) if isinstance(row, dict)]
    preserved_id = ""
    if startup_id:
        existing = next((row for row in rows if str(row.get("id", "")) == startup_id), None)
        if existing is None:
            return {"ok": False, "error": "Only Maho-owned session entries can be edited."}
        preserved_id = startup_id
        rows = [row for row in rows if str(row.get("id", "")) != startup_id]

    identity = (command, when, workspace)
    if any(
        (
            str(row.get("command", "") or ""),
            str(row.get("when", "") or ""),
            str(row.get("workspace", "") or ""),
        ) == identity
        for row in rows
    ):
        return {"ok": False, "error": "That managed session command already exists."}

    rows.append({
        "id": preserved_id or str(uuid.uuid4()),
        "command": command,
        "when": when,
        "workspace": workspace,
    })
    model["startup"] = rows

    ok, _, apply_error = _apply_managed_hypr_model(
        model,
        verify=lambda observed: _startup_collection_has(
            observed,
            command=command,
            when=when,
            workspace=workspace,
            require_overlay=True,
        ),
    )
    if not ok:
        return {"ok": False, "error": apply_error}
    return {
        "ok": True,
        "message": "Session command updated.",
        "state": snapshot_session(),
    }


def session_startup_delete(startup_id: str) -> dict[str, Any]:
    startup_id = startup_id.strip()
    if not startup_id:
        return {"ok": False, "error": "Managed session entry identity is required."}

    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed session state is unavailable."}

    rows = [row for row in model.get("startup", []) if isinstance(row, dict)]
    existing = next((row for row in rows if str(row.get("id", "")) == startup_id), None)
    if existing is None:
        return {"ok": False, "error": "System session entries cannot be deleted from Maho Settings."}

    command = str(existing.get("command", "") or "")
    when = str(existing.get("when", "") or "")
    workspace = str(existing.get("workspace", "") or "")
    model["startup"] = [row for row in rows if str(row.get("id", "")) != startup_id]

    ok, _, apply_error = _apply_managed_hypr_model(
        model,
        verify=lambda observed: not _startup_collection_has(
            observed,
            command=command,
            when=when,
            workspace=workspace,
            require_overlay=True,
        ),
    )
    if not ok:
        return {"ok": False, "error": apply_error}
    return {
        "ok": True,
        "message": "Session command removed.",
        "state": snapshot_session(),
    }


def _motion_collection_has_animation(
    collection: dict[str, Any],
    leaf: str,
    *,
    require_overlay: bool = False,
) -> bool:
    writer = hypr_config_writer.status()
    for raw in collection.get("animations", []):
        if not isinstance(raw, dict):
            continue
        fields = raw.get("fields", {}) if isinstance(raw.get("fields"), dict) else {}
        if str(fields.get("leaf", "") or raw.get("name", "") or "") != leaf:
            continue
        if require_overlay and not _writer_source_is_overlay(
            str(raw.get("source_file", "") or ""), writer
        ):
            continue
        return True
    return False


def motion_animation_upsert(
    leaf: str,
    enabled: bool,
    speed: float,
    curve: str,
    style: str = "",
) -> dict[str, Any]:
    leaf = leaf.strip()
    curve = curve.strip()
    style = style.strip()
    if not leaf or not curve:
        return {"ok": False, "error": "Animation leaf and curve are required."}
    if not isinstance(enabled, bool):
        return {"ok": False, "error": "Animation enabled state must be boolean."}
    if not math.isfinite(speed) or speed < 0 or speed > 50:
        return {"ok": False, "error": "Animation speed must be between 0 and 50."}

    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed motion state is unavailable."}
    rows = [
        row
        for row in model.get("animations", [])
        if not (
            isinstance(row, dict)
            and str(row.get("leaf", "") or "") == leaf
        )
    ]
    rows.append({
        "leaf": leaf,
        "enabled": enabled,
        "speed": float(speed),
        "bezier": curve,
        "style": style,
    })
    model["animations"] = rows

    def verified(observed: dict[str, Any]) -> bool:
        if not _motion_collection_has_animation(observed, leaf, require_overlay=True):
            return False
        live, _ = hypr_json(["animations", "-j"])
        if not isinstance(live, list) or not live or not isinstance(live[0], list):
            return False
        for row in live[0]:
            if not isinstance(row, dict) or str(row.get("name", "") or "") != leaf:
                continue
            return (
                bool(row.get("enabled", False)) == enabled
                and abs(float(row.get("speed", 0.0) or 0.0) - float(speed)) < 0.001
                and str(row.get("bezier", "") or "default") == curve
                and str(row.get("style", "") or "") == style
            )
        return False

    ok, _, apply_error = _apply_managed_hypr_model(model, verify=verified)
    if not ok:
        return {"ok": False, "error": apply_error}
    return {
        "ok": True,
        "message": "Animation override updated.",
        "state": snapshot_motion(),
    }


def motion_animation_reset(leaf: str) -> dict[str, Any]:
    leaf = leaf.strip()
    if not leaf:
        return {"ok": False, "error": "Animation leaf is required."}
    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed motion state is unavailable."}
    model["animations"] = [
        row
        for row in model.get("animations", [])
        if not (isinstance(row, dict) and str(row.get("leaf", "") or "") == leaf)
    ]
    ok, _, apply_error = _apply_managed_hypr_model(
        model,
        verify=lambda observed: not _motion_collection_has_animation(
            observed, leaf, require_overlay=True
        ),
    )
    if not ok:
        return {"ok": False, "error": apply_error}
    return {
        "ok": True,
        "message": "Animation restored to the system default.",
        "state": snapshot_motion(),
    }


def _motion_collection_has_curve(
    collection: dict[str, Any],
    name: str,
    *,
    require_overlay: bool = False,
) -> bool:
    writer = hypr_config_writer.status()
    for raw in collection.get("curves", []):
        if not isinstance(raw, dict) or str(raw.get("name", "") or "") != name:
            continue
        if require_overlay and not _writer_source_is_overlay(
            str(raw.get("source_file", "") or ""), writer
        ):
            continue
        return True
    return False


def motion_curve_upsert(
    name: str,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> dict[str, Any]:
    name = name.strip()
    if not name or name == "default":
        return {"ok": False, "error": "Choose a non-default curve name."}
    points = [float(x0), float(y0), float(x1), float(y1)]
    if any(not math.isfinite(value) for value in points):
        return {"ok": False, "error": "Curve coordinates must be finite numbers."}

    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed motion state is unavailable."}
    rows = [
        row
        for row in model.get("curves", [])
        if not (isinstance(row, dict) and str(row.get("name", "") or "") == name)
    ]
    rows.append({"name": name, "points": [[x0, y0], [x1, y1]]})
    model["curves"] = rows

    def verified(observed: dict[str, Any]) -> bool:
        if not _motion_collection_has_curve(observed, name, require_overlay=True):
            return False
        live, _ = hypr_json(["animations", "-j"])
        if not isinstance(live, list) or len(live) < 2 or not isinstance(live[1], list):
            return False
        for row in live[1]:
            if not isinstance(row, dict) or str(row.get("name", "") or "") != name:
                continue
            return all(
                abs(float(row.get(key, 0.0) or 0.0) - expected) < 0.001
                for key, expected in (
                    ("X0", x0), ("Y0", y0), ("X1", x1), ("Y1", y1)
                )
            )
        return False

    ok, _, apply_error = _apply_managed_hypr_model(model, verify=verified)
    if not ok:
        return {"ok": False, "error": apply_error}
    return {
        "ok": True,
        "message": "Animation curve updated.",
        "state": snapshot_motion(),
    }


def motion_curve_reset(name: str) -> dict[str, Any]:
    name = name.strip()
    if not name or name == "default":
        return {"ok": False, "error": "Choose a non-default managed curve."}
    model, model_error = _managed_hypr_model()
    if not isinstance(model, dict):
        return {"ok": False, "error": model_error or "Managed motion state is unavailable."}
    model["curves"] = [
        row
        for row in model.get("curves", [])
        if not (isinstance(row, dict) and str(row.get("name", "") or "") == name)
    ]
    ok, _, apply_error = _apply_managed_hypr_model(
        model,
        verify=lambda observed: not _motion_collection_has_curve(
            observed, name, require_overlay=True
        ),
    )
    if not ok:
        return {"ok": False, "error": apply_error}
    return {
        "ok": True,
        "message": "Animation curve restored to the system default.",
        "state": snapshot_motion(),
    }


def configuration_reset() -> dict[str, Any]:
    empty = {"version": hypr_config_writer.MODEL_VERSION}
    ok, _, apply_error = _apply_managed_hypr_model(empty)
    if not ok:
        return {"ok": False, "error": apply_error}
    return {
        "ok": True,
        "message": "Managed Hyprland overrides were reset.",
        "state": snapshot_configuration(),
    }

def snapshot_rules() -> dict[str, Any]:
    collection, collection_error = _collect_hypr_config()
    if not isinstance(collection, dict):
        return {
            "available": False,
            "windowRules": [],
            "workspaceRules": [],
            "layerRules": [],
            "mutationAvailable": False,
            "readOnly": True,
            "error": collection_error or "Rule configuration is unavailable.",
        }

    writer = hypr_config_writer.status()
    prefix, _ = hypr_prefix()
    mutation_available = (
        bool(writer.get("mutationAvailable"))
        and prefix is not None
        and not bool(collection_error)
    )

    model = writer.get("model", {}) if isinstance(writer.get("model"), dict) else {}

    def rule_signature(name: str, match: dict[str, Any], effects: dict[str, Any]) -> str:
        return json.dumps(
            {"name": name, "match": match, "effects": effects},
            sort_keys=True,
            separators=(",", ":"),
        )

    managed_rule_ids: dict[tuple[str, str], str] = {}
    for kind, key in (("window", "windowRules"), ("layer", "layerRules")):
        for row in model.get(key, []):
            if not isinstance(row, dict):
                continue
            signature = rule_signature(
                str(row.get("name", "") or ""),
                row.get("match", {}) if isinstance(row.get("match"), dict) else {},
                row.get("effects", {}) if isinstance(row.get("effects"), dict) else {},
            )
            managed_rule_ids[(kind, signature)] = str(row.get("id", "") or "")

    def normalized_rule(raw: dict[str, Any], kind: str, index: int) -> dict[str, Any]:
        source_file = str(raw.get("source_file", "") or "")
        source_line = int(raw.get("source_line", 0) or 0)
        user_owned = _writer_source_is_overlay(source_file, writer)
        name = str(raw.get("name", "") or "")
        match = raw.get("match", {}) if isinstance(raw.get("match"), dict) else {}
        effects = raw.get("effects", {}) if isinstance(raw.get("effects"), dict) else {}
        managed_id = managed_rule_ids.get(
            (kind, rule_signature(name, match, effects)),
            "",
        )
        return {
            "id": managed_id or str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"maho-{kind}-rule:{source_file}:{source_line}:{name}:{index}",
            )),
            "name": name or f"{kind.capitalize()} rule",
            "match": match,
            "effects": effects,
            "sourceFile": source_file,
            "sourceLine": source_line,
            "userOwned": user_owned,
            "canEdit": mutation_available and user_owned and bool(managed_id),
            "canDelete": mutation_available and user_owned and bool(managed_id),
        }

    window_rules = [
        normalized_rule(raw, "window", index)
        for index, raw in enumerate(collection.get("window_rules", []))
        if isinstance(raw, dict)
    ]
    layer_rules = [
        normalized_rule(raw, "layer", index)
        for index, raw in enumerate(collection.get("layer_rules", []))
        if isinstance(raw, dict)
    ]

    workspace_rules = []
    for index, raw in enumerate(collection.get("workspace_rules", [])):
        if not isinstance(raw, dict):
            continue
        source_file = str(raw.get("source_file", "") or "")
        source_line = int(raw.get("source_line", 0) or 0)
        fields = raw.get("fields", {}) if isinstance(raw.get("fields"), dict) else {}
        workspace_rules.append({
            "id": str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"maho-workspace-rule:{source_file}:{source_line}:{index}",
            )),
            "name": str(raw.get("name", "") or fields.get("workspace", "") or "Workspace rule"),
            "fields": fields,
            "sourceFile": source_file,
            "sourceLine": source_line,
            "userOwned": _writer_source_is_overlay(source_file, writer),
            "canEdit": mutation_available and _writer_source_is_overlay(source_file, writer),
            "canDelete": mutation_available and _writer_source_is_overlay(source_file, writer),
        })

    return {
        "available": not bool(collection_error),
        "windowRules": window_rules,
        "workspaceRules": workspace_rules,
        "layerRules": layer_rules,
        "mutationAvailable": mutation_available,
        "canAddWindowRule": mutation_available,
        "canAddWorkspaceRule": mutation_available,
        "canAddLayerRule": mutation_available,
        "readOnly": not mutation_available,
        "error": collection_error,
    }


def snapshot_session() -> dict[str, Any]:
    collection, collection_error = _collect_hypr_config()
    if not isinstance(collection, dict):
        return {
            "available": False,
            "startup": [],
            "variables": [],
            "environment": [],
            "mutationAvailable": False,
            "readOnly": True,
            "error": collection_error or "Session configuration is unavailable.",
        }

    writer = hypr_config_writer.status()
    prefix, _ = hypr_prefix()
    mutation_available = (
        bool(writer.get("mutationAvailable"))
        and prefix is not None
        and not bool(collection_error)
    )
    model = writer.get("model", {}) if isinstance(writer.get("model"), dict) else {}
    managed_startup_ids: dict[tuple[str, str, str], str] = {}
    for row in model.get("startup", []):
        if not isinstance(row, dict):
            continue
        identity = (
            str(row.get("command", "") or ""),
            str(row.get("when", "") or ""),
            str(row.get("workspace", "") or ""),
        )
        managed_startup_ids[identity] = str(row.get("id", "") or "")

    startup = []
    for index, raw in enumerate(collection.get("startup", [])):
        if not isinstance(raw, dict):
            continue
        source_file = str(raw.get("source_file", "") or "")
        source_line = int(raw.get("source_line", 0) or 0)
        user_owned = _writer_source_is_overlay(source_file, writer)
        command = str(raw.get("command", "") or "")
        when = str(raw.get("when", "") or "reload")
        workspace = str(raw.get("workspace", "") or "")
        managed_id = managed_startup_ids.get((command, when, workspace), "")
        startup.append({
            "id": managed_id or str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"maho-startup:{source_file}:{source_line}:{index}",
            )),
            "command": command,
            "when": when,
            "workspace": workspace,
            "sourceFile": source_file,
            "sourceLine": source_line,
            "userOwned": user_owned,
            "canEdit": mutation_available and user_owned and bool(managed_id),
            "canDelete": mutation_available and user_owned and bool(managed_id),
        })

    variables = [
        row
        for row in collection.get("variables", [])
        if isinstance(row, dict)
    ]
    environment = [
        row
        for row in collection.get("env", [])
        if isinstance(row, dict)
    ]
    return {
        "available": not bool(collection_error),
        "startup": startup,
        "variables": variables,
        "environment": environment,
        "mutationAvailable": mutation_available,
        "canAddStartup": mutation_available,
        "readOnly": not mutation_available,
        "error": collection_error,
    }


def _hypr_config_errors() -> tuple[list[str], str]:
    code, out, err = hypr(["configerrors"], timeout=4.0)
    if code != 0:
        return [], err or out or "Hyprland configuration health is unavailable."
    errors = [line.strip() for line in out.splitlines() if line.strip()]
    return errors, ""


def snapshot_configuration() -> dict[str, Any]:
    errors, error = _hypr_config_errors()
    prefix, session_error = hypr_prefix()
    writer = hypr_config_writer.status()
    managed = [
        ROOT / "config" / "hypr" / "maho" / "core" / "binds.lua",
        ROOT / "config" / "hypr" / "maho" / "core" / "windowing.lua",
        ROOT / "config" / "hypr" / "maho" / "core" / "session.lua",
        ROOT / "config" / "hypr" / "maho" / "appearance" / "animations.lua",
    ]
    mutation_available = (
        bool(writer.get("mutationAvailable"))
        and prefix is not None
        and not bool(error)
        and not bool(errors)
    )
    writer_error = str(writer.get("modelError", "") or "")
    combined_error = error or session_error or writer_error
    return {
        "available": not bool(error) and prefix is not None,
        "healthy": not bool(errors) and not bool(error) and prefix is not None,
        "configErrors": errors,
        "managedFiles": [str(path) for path in managed if path.is_file()],
        "mutationAvailable": mutation_available,
        "readOnly": not mutation_available,
        "writer": {
            "available": bool(writer.get("available")),
            "loaderInstalled": bool(writer.get("loaderInstalled")),
            "loaderPath": str(writer.get("loaderPath", "")),
            "overlayPath": str(writer.get("path", "")),
            "modelPath": str(writer.get("modelPath", "")),
            "overlayExists": bool(writer.get("exists")),
            "backupCount": int(writer.get("backupCount", 0) or 0),
            "lastWrite": writer.get("lastWrite", {}),
            "model": writer.get("model", {"version": 1}),
        },
        "error": combined_error,
    }


def snapshot_diagnostics() -> dict[str, Any]:
    errors, hypr_error = _hypr_config_errors()
    providers = [
        {"name": "Hyprland", "available": hypr_prefix()[0] is not None},
        {"name": "Audio", "available": shutil.which("wpctl") is not None},
        {"name": "Maho Theme", "available": root_command("maho-theme") is not None},
        {"name": "Maho Notify", "available": root_command("maho-notify") is not None},
        {"name": "Region & Time", "available": shutil.which("timedatectl") is not None},
    ]
    return {
        "available": True,
        "configurationHealthy": not bool(errors) and not bool(hypr_error),
        "configErrors": errors,
        "providerError": hypr_error,
        "providers": providers,
        "error": "",
    }


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


def snapshot_providers() -> dict[str, Any]:
    return {
        "appearance": snapshot_appearance,
        "displays": snapshot_displays,
        "sound": snapshot_sound,
        "input": snapshot_input,
        "power": snapshot_power,
        "notifications": snapshot_notifications,
        "applications": snapshot_applications,
        "region": snapshot_region,
        "shortcuts": snapshot_shortcuts,
        "rules": snapshot_rules,
        "motion": snapshot_motion,
        "session": snapshot_session,
        "configuration": snapshot_configuration,
        "diagnostics": snapshot_diagnostics,
        "system": snapshot_about,
    }


def snapshot(section: str = "all") -> dict[str, Any]:
    providers = snapshot_providers()
    if section != "all":
        provider = providers.get(section)
        if provider is None:
            return {"ok": False, "error": "Unknown settings section."}
        return {"ok": True, section: provider()}

    # These providers are independent read-only observations. Running them
    # concurrently keeps the total observation bounded while preserving
    # deterministic result ordering for callers that need one complete map.
    items = list(providers.items())
    with ThreadPoolExecutor(max_workers=min(6, len(items)), thread_name_prefix="maho-settings") as executor:
        futures = [executor.submit(provider) for _, provider in items]
        values = {
            name: future.result()
            for (name, _), future in zip(items, futures, strict=True)
        }
    return {"ok": True, **values}


def warmup_stream() -> None:
    """Emit independent Settings sections as soon as each provider finishes."""
    providers = snapshot_providers()
    items = list(providers.items())
    with ThreadPoolExecutor(max_workers=min(6, len(items)), thread_name_prefix="maho-settings-warmup") as executor:
        pending = {
            executor.submit(provider): name
            for name, provider in items
        }
        for future in as_completed(pending):
            name = pending[future]
            try:
                state = future.result()
                payload = {"ok": True, "section": name, "state": state}
            except Exception as exc:
                payload = {
                    "ok": False,
                    "section": name,
                    "error": f"Settings provider failure: {exc}",
                }
            print(
                json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                flush=True,
            )


def _apply_persisted_input() -> list[str]:
    payload = read_json(INPUT_CONFIG)
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return []
    values = payload.get("values", {})
    devices = payload.get("devices", {})
    if not isinstance(values, dict) or not isinstance(devices, dict):
        return []

    applied: list[str] = []
    for key, value in values.items():
        if key == "keyboardLayout":
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_+,-]{1,64}", value):
                continue
            option, value_to_apply = "input:kb_layout", value
        elif key in _INPUT_ENUMS:
            option, allowed = _INPUT_ENUMS[key]
            if not isinstance(value, str) or value not in allowed:
                continue
            value_to_apply = value
        else:
            spec = _INPUT_SPECS.get(key)
            if spec is None:
                continue
            option, kind, low, high = spec
            if kind is bool:
                if not isinstance(value, bool):
                    continue
                value_to_apply = value
            else:
                try:
                    normalized = kind(value)
                except (TypeError, ValueError):
                    continue
                if not (low <= normalized <= high):
                    continue
                value_to_apply = normalized
        ok, _ = _hypr_set_input_option(option, value_to_apply)
        if ok:
            applied.append(key)

    live = snapshot_input()
    active_touchpads = set(live.get("touchpads", [])) if live.get("available") else set()
    for device, row in devices.items():
        if device not in active_touchpads or not isinstance(row, dict):
            continue
        value = row.get("sensitivity")
        try:
            sensitivity = float(value)
        except (TypeError, ValueError):
            continue
        if not (-1.0 <= sensitivity <= 1.0):
            continue
        ok, _ = _hypr_set_device_input(device, "sensitivity", sensitivity)
        if ok:
            applied.append(f"touchpadSensitivity:{device}")
    return applied

def apply_session() -> dict[str, Any]:
    applied: list[str] = []
    skipped: list[str] = []
    if hypr_prefix()[0] is None:
        return {"ok": True, "applied": [], "skipped": ["hyprland-unavailable"]}

    reduced_motion = bool(intent_get("appearance.reduced_motion", False))
    if _hypr_config(("animations", "enabled"), not reduced_motion)[0]:
        applied.append("appearance.reduced_motion")

    reduced_transparency = bool(intent_get("appearance.reduced_transparency", False))
    if _hypr_config(("decoration", "blur", "enabled"), not reduced_transparency)[0]:
        applied.append("appearance.reduced_transparency")

    applied.extend(f"input.{key}" for key in _apply_persisted_input())

    persisted = _persisted_display_rows()
    if persisted:
        current = _display_snapshot_rows()
        if {row.get("name") for row in current} == {row.get("name") for row in persisted}:
            ok, _ = _apply_display_rows([row for row in persisted if isinstance(row, dict)])
            verified = ok and _display_layout_matches(_display_snapshot_rows(), persisted)
            if verified:
                applied.append("displays")
            else:
                rollback_ok, _ = _apply_display_rows([row for row in current if isinstance(row, dict)])
                rollback_verified = rollback_ok and _display_layout_matches(_display_snapshot_rows(), current)
                skipped.append(
                    "displays-apply-failed-rolled-back"
                    if rollback_verified else "displays-apply-failed-rollback-unverified"
                )
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
    if name == "display.focus":
        return display_focus(str(payload.get("name", "")))
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
        return input_set(
            str(payload.get("key", "")),
            payload.get("value"),
            str(payload.get("device", "")),
        )
    if name == "notification.enabled":
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "Notification enabled value must be boolean."}
        return notification_enabled(enabled)
    if name == "notification.dnd":
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "DND value must be boolean."}
        return notification_dnd(enabled)
    if name == "notification.clearHistory":
        return notification_clear_history()
    if name == "region.timezone":
        return region_timezone(str(payload.get("timezone", "")))
    if name == "region.automaticTime":
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "Automatic-time value must be boolean."}
        return region_automatic_time(enabled)
    if name == "region.locale":
        return region_locale(str(payload.get("locale", "")))
    if name == "region.keyboardLayout":
        return input_set("keyboardLayout", payload.get("layout"))
    if name == "applications.default":
        return application_default(str(payload.get("kind", "")), str(payload.get("desktopId", "")))
    if name == "applications.mimeDefault":
        return application_mime_default(
            str(payload.get("mime", "")),
            str(payload.get("desktopId", "")),
        )
    if name == "power.profile":
        return power_profile(str(payload.get("profile", "")))
    if name == "shortcuts.upsert":
        replace_existing = payload.get("replaceExisting", False)
        if not isinstance(replace_existing, bool):
            return {"ok": False, "error": "Shortcut override flag must be boolean."}
        description = payload.get("description", "")
        if not isinstance(description, str):
            return {"ok": False, "error": "Shortcut description must be text."}
        return shortcut_upsert(
            str(payload.get("chord", "")),
            str(payload.get("command", "")),
            description,
            submap=str(payload.get("submap", "")),
            original_chord=str(payload.get("originalChord", "")),
            original_submap=str(payload.get("originalSubmap", "")),
            replace_existing=replace_existing,
        )
    if name == "shortcuts.disable":
        return shortcut_disable(
            str(payload.get("chord", "")),
            str(payload.get("submap", "")),
        )
    if name == "shortcuts.reset":
        return shortcut_reset(
            str(payload.get("chord", "")),
            str(payload.get("submap", "")),
        )
    if name == "rules.upsert":
        match = payload.get("match")
        effects = payload.get("effects")
        if not isinstance(match, dict) or not isinstance(effects, dict):
            return {"ok": False, "error": "Rule match and effects must be objects."}
        return rule_upsert(
            str(payload.get("kind", "")),
            str(payload.get("name", "")),
            match,
            effects,
            rule_id=str(payload.get("id", "")),
        )
    if name == "rules.delete":
        return rule_delete(
            str(payload.get("kind", "")),
            str(payload.get("id", "")),
        )
    if name == "rules.workspaceUpsert":
        fields = payload.get("fields")
        original_fields = payload.get("originalFields")
        if not isinstance(fields, dict):
            return {"ok": False, "error": "Workspace rule fields must be an object."}
        if original_fields is not None and not isinstance(original_fields, dict):
            return {"ok": False, "error": "Original workspace rule fields must be an object."}
        return workspace_rule_upsert(fields, original_fields=original_fields)
    if name == "rules.workspaceDelete":
        fields = payload.get("fields")
        if not isinstance(fields, dict):
            return {"ok": False, "error": "Workspace rule fields must be an object."}
        return workspace_rule_delete(fields)
    if name == "session.startupUpsert":
        return session_startup_upsert(
            str(payload.get("command", "")),
            str(payload.get("when", "")),
            str(payload.get("workspace", "")),
            startup_id=str(payload.get("id", "")),
        )
    if name == "session.startupDelete":
        return session_startup_delete(str(payload.get("id", "")))
    if name == "motion.animationUpsert":
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "Animation enabled state must be boolean."}
        try:
            speed = float(payload.get("speed"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Animation speed must be numeric."}
        return motion_animation_upsert(
            str(payload.get("leaf", "")),
            enabled,
            speed,
            str(payload.get("curve", "")),
            str(payload.get("style", "")),
        )
    if name == "motion.animationReset":
        return motion_animation_reset(str(payload.get("leaf", "")))
    if name == "motion.curveUpsert":
        try:
            x0 = float(payload.get("x0"))
            y0 = float(payload.get("y0"))
            x1 = float(payload.get("x1"))
            y1 = float(payload.get("y1"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Curve coordinates must be numeric."}
        return motion_curve_upsert(
            str(payload.get("name", "")),
            x0,
            y0,
            x1,
            y1,
        )
    if name == "motion.curveReset":
        return motion_curve_reset(str(payload.get("name", "")))
    if name == "configuration.reset":
        return configuration_reset()
    return {"ok": False, "error": "Unsupported settings action."}


def usage() -> int:
    print("Usage: maho-settings-backend snapshot [all|SECTION] | warmup | search QUERY | action NAME JSON | apply-session", file=sys.stderr)
    return 2


def main(argv: list[str]) -> int:
    try:
        if not argv:
            return usage()
        command = argv[0]
        if command == "snapshot":
            emit(snapshot(argv[1] if len(argv) > 1 else "all"))
            return 0
        if command == "warmup" and len(argv) == 1:
            warmup_stream()
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
