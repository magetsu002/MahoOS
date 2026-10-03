#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Single-owner writer for Maho Settings' user Hyprland overlay.

This module adapts the safe-write ideas used by Hyprbind's writer/backup
subsystem at upstream commit b55e527b439ffd3f97d4d8c1102052095dcf7b9a:
managed ownership, backup-before-write, deterministic Lua rendering, and atomic
replacement. Maho deliberately does not edit immutable runtime config files.

Hyprbind Copyright (c) 2026 Mashrur Rahman Rawnok (NullifiedSec).
Original project: https://github.com/NullifiedSec/hyprbind
Used under the Hyprbind -> MahoOS Special License Exception v1.0 preserved in
LICENSES/HYPRBIND-MAHOOS-SPECIAL-LICENSE-EXCEPTION-v1.0.txt.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence

MODEL_VERSION = 1
MAX_ITEMS = 256
MAX_STRING = 4096
BACKUP_KEEP = 12

ALLOWED_BIND_FLAGS = {
    "locked",
    "release",
    "click",
    "drag",
    "long_press",
    "repeating",
    "non_consuming",
    "auto_consuming",
    "mouse",
    "transparent",
    "ignore_mods",
    "dont_inhibit",
    "submap_universal",
}

LUA_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENV_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConfigWriteError(RuntimeError):
    """Fail-closed error from the managed Hyprland writer."""


@dataclass(frozen=True)
class WriterPaths:
    loader: Path
    config: Path
    model: Path
    state_dir: Path
    backups: Path
    receipt: Path
    lock: Path


RunResult = tuple[int, str, str]
Runner = Callable[[Sequence[str], float], RunResult]


def default_paths() -> WriterPaths:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    state_dir = state_home / "maho" / "settings" / "hypr-config"
    return WriterPaths(
        loader=config_home / "hypr" / "hyprland.lua",
        config=config_home / "hypr" / "maho" / "user" / "settings.lua",
        model=config_home / "maho" / "settings" / "hypr-managed.json",
        state_dir=state_dir,
        backups=state_dir / "backups",
        receipt=state_dir / "last-write.json",
        lock=state_dir / "writer.lock",
    )


def _bounded_string(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ConfigWriteError(f"{name} must be a string")
    if "\x00" in value or "\r" in value:
        raise ConfigWriteError(f"{name} contains an unsupported control character")
    if len(value) > MAX_STRING:
        raise ConfigWriteError(f"{name} is too long")
    if not allow_empty and not value.strip():
        raise ConfigWriteError(f"{name} cannot be empty")
    return value


def _bounded_list(value: Any, name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigWriteError(f"{name} must be a list")
    if len(value) > MAX_ITEMS:
        raise ConfigWriteError(f"{name} exceeds the {MAX_ITEMS} item limit")
    return value


def _optional_id(value: Any, name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ConfigWriteError(f"{name} must be a string or integer")
    return _bounded_string(str(value), name, allow_empty=True)


def _lua_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _lua_value(value: Any, depth: int = 0) -> str:
    if depth > 8:
        raise ConfigWriteError("managed value nesting is too deep")
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigWriteError("non-finite numbers are not allowed")
        return repr(value)
    if isinstance(value, str):
        return _lua_string(_bounded_string(value, "value", allow_empty=True))
    if isinstance(value, list):
        if len(value) > MAX_ITEMS:
            raise ConfigWriteError("managed list is too large")
        return "{ " + ", ".join(_lua_value(item, depth + 1) for item in value) + " }"
    if isinstance(value, dict):
        if len(value) > MAX_ITEMS:
            raise ConfigWriteError("managed table is too large")
        rows = []
        for key in sorted(value):
            if not isinstance(key, str):
                raise ConfigWriteError("managed table keys must be strings")
            rendered_key = key if LUA_IDENT.fullmatch(key) else f"[{_lua_string(key)}]"
            rows.append(f"{rendered_key} = {_lua_value(value[key], depth + 1)}")
        return "{ " + ", ".join(rows) + " }"
    raise ConfigWriteError(f"unsupported managed value type: {type(value).__name__}")


def _mapping(value: Any, name: str, *, require_nonempty: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigWriteError(f"{name} must be an object")
    if require_nonempty and not value:
        raise ConfigWriteError(f"{name} cannot be empty")
    if len(value) > MAX_ITEMS:
        raise ConfigWriteError(f"{name} is too large")
    # Rendering performs recursive type validation.
    _lua_value(value)
    return dict(value)


def _normalize_bind(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ConfigWriteError("bind entry must be an object")
    flags = _bounded_list(row.get("flags", []), "bind flags")
    clean_flags: list[str] = []
    for flag in flags:
        flag = _bounded_string(flag, "bind flag")
        if flag not in ALLOWED_BIND_FLAGS:
            raise ConfigWriteError(f"unsupported bind flag: {flag}")
        if flag not in clean_flags:
            clean_flags.append(flag)
    return {
        "id": _optional_id(row.get("id"), "bind id"),
        "keys": _bounded_string(row.get("keys"), "bind keys"),
        "command": _bounded_string(row.get("command"), "bind command"),
        "description": _bounded_string(row.get("description", ""), "bind description", allow_empty=True),
        "submap": _bounded_string(row.get("submap", ""), "bind submap", allow_empty=True),
        "flags": clean_flags,
    }


def _normalize_rule(row: Any, kind: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ConfigWriteError(f"{kind} rule entry must be an object")
    match = _mapping(row.get("match", {}), f"{kind} rule match", require_nonempty=True)
    effects = _mapping(row.get("effects", {}), f"{kind} rule effects", require_nonempty=True)
    reserved = sorted(set(effects) & {"name", "match", "enabled"})
    if reserved:
        raise ConfigWriteError(
            f"{kind} rule effects contain reserved metadata: {', '.join(reserved)}"
        )
    return {
        "id": _optional_id(row.get("id"), f"{kind} rule id"),
        "name": _bounded_string(row.get("name", ""), f"{kind} rule name", allow_empty=True),
        "match": match,
        "effects": effects,
    }


def _normalize_startup(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ConfigWriteError("startup entry must be an object")
    when = _bounded_string(row.get("when", "start"), "startup timing").lower()
    aliases = {"once": "start", "exec-once": "start", "exec": "reload", "exit": "shutdown"}
    when = aliases.get(when, when)
    if when not in {"start", "reload", "shutdown"}:
        raise ConfigWriteError("startup timing must be start, reload, or shutdown")
    return {
        "id": _optional_id(row.get("id"), "startup id"),
        "command": _bounded_string(row.get("command"), "startup command"),
        "when": when,
        "workspace": _bounded_string(row.get("workspace", ""), "startup workspace", allow_empty=True),
    }


def _normalize_curve(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ConfigWriteError("curve entry must be an object")
    name = _bounded_string(row.get("name"), "curve name")
    points = _bounded_list(row.get("points"), "curve points")
    if len(points) != 2:
        raise ConfigWriteError("Bezier curves require exactly two control points")
    clean_points: list[list[float]] = []
    for point in points:
        if not isinstance(point, list) or len(point) != 2:
            raise ConfigWriteError("each curve point must contain x and y")
        pair = []
        for value in point:
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise ConfigWriteError("curve coordinates must be finite numbers")
            pair.append(float(value))
        clean_points.append(pair)
    return {"name": name, "points": clean_points}


def _normalize_animation(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ConfigWriteError("animation entry must be an object")
    speed = row.get("speed", 1.0)
    if not isinstance(speed, (int, float)) or isinstance(speed, bool) or not math.isfinite(float(speed)):
        raise ConfigWriteError("animation speed must be a finite number")
    if float(speed) < 0:
        raise ConfigWriteError("animation speed cannot be negative")
    return {
        "leaf": _bounded_string(row.get("leaf"), "animation leaf"),
        "enabled": bool(row.get("enabled", True)),
        "speed": float(speed),
        "bezier": _bounded_string(row.get("bezier", "default"), "animation curve"),
        "style": _bounded_string(row.get("style", ""), "animation style", allow_empty=True),
    }


def normalize_model(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigWriteError("managed configuration must be an object")
    allowed = {
        "version", "variables", "environment", "unbinds", "binds", "submaps",
        "windowRules", "workspaceRules", "layerRules", "curves", "animations", "startup",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigWriteError(f"unknown managed configuration keys: {', '.join(unknown)}")
    if raw.get("version", MODEL_VERSION) != MODEL_VERSION:
        raise ConfigWriteError(f"unsupported managed configuration version: {raw.get('version')}")

    variables = []
    seen_vars: set[str] = set()
    for row in _bounded_list(raw.get("variables", []), "variables"):
        if not isinstance(row, dict):
            raise ConfigWriteError("variable entry must be an object")
        name = _bounded_string(row.get("name"), "variable name")
        if not LUA_IDENT.fullmatch(name):
            raise ConfigWriteError(f"invalid Lua variable name: {name}")
        if name in seen_vars:
            raise ConfigWriteError(f"duplicate variable: {name}")
        seen_vars.add(name)
        variables.append({
            "name": name,
            "value": _bounded_string(row.get("value", ""), "variable value", allow_empty=True),
        })

    environment = []
    seen_env: set[str] = set()
    for row in _bounded_list(raw.get("environment", []), "environment"):
        if not isinstance(row, dict):
            raise ConfigWriteError("environment entry must be an object")
        name = _bounded_string(row.get("name"), "environment name")
        if not ENV_IDENT.fullmatch(name):
            raise ConfigWriteError(f"invalid environment variable name: {name}")
        if name in seen_env:
            raise ConfigWriteError(f"duplicate environment variable: {name}")
        seen_env.add(name)
        environment.append({
            "name": name,
            "value": _bounded_string(row.get("value", ""), "environment value", allow_empty=True),
        })

    unbinds = []
    seen_unbinds: set[tuple[str, str]] = set()
    for value in _bounded_list(raw.get("unbinds", []), "unbinds"):
        if isinstance(value, str):
            keys = _bounded_string(value, "unbind chord")
            submap = ""
        elif isinstance(value, dict):
            keys = _bounded_string(value.get("keys"), "unbind chord")
            submap = _bounded_string(
                value.get("submap", ""), "unbind submap", allow_empty=True
            )
        else:
            raise ConfigWriteError("unbind entry must be a chord string or object")
        identity = (submap, keys)
        if identity not in seen_unbinds:
            seen_unbinds.add(identity)
            unbinds.append({"keys": keys, "submap": submap})

    submaps = []
    seen_submaps: set[str] = set()
    for row in _bounded_list(raw.get("submaps", []), "submaps"):
        if not isinstance(row, dict):
            raise ConfigWriteError("submap entry must be an object")
        name = _bounded_string(row.get("name"), "submap name")
        if name in {"reset", "global"}:
            raise ConfigWriteError(f"reserved submap name: {name}")
        if name in seen_submaps:
            raise ConfigWriteError(f"duplicate submap: {name}")
        seen_submaps.add(name)
        submaps.append({
            "name": name,
            "reset": _bounded_string(row.get("reset", ""), "submap reset", allow_empty=True),
        })

    for unbind in unbinds:
        if unbind["submap"] and unbind["submap"] not in seen_submaps:
            seen_submaps.add(unbind["submap"])
            submaps.append({"name": unbind["submap"], "reset": ""})

    binds = [_normalize_bind(row) for row in _bounded_list(raw.get("binds", []), "binds")]
    seen_bind_keys: set[tuple[str, str]] = set()
    seen_bind_ids: set[str] = set()
    for bind in binds:
        identity = (bind["submap"], bind["keys"])
        if identity in seen_bind_keys:
            scope = bind["submap"] or "global"
            raise ConfigWriteError(f"duplicate bind in {scope}: {bind['keys']}")
        seen_bind_keys.add(identity)
        if bind["id"]:
            if bind["id"] in seen_bind_ids:
                raise ConfigWriteError(f"duplicate bind id: {bind['id']}")
            seen_bind_ids.add(bind["id"])
        if bind["submap"] and bind["submap"] not in seen_submaps:
            seen_submaps.add(bind["submap"])
            submaps.append({"name": bind["submap"], "reset": ""})

    return {
        "version": MODEL_VERSION,
        "variables": variables,
        "environment": environment,
        "unbinds": unbinds,
        "binds": binds,
        "submaps": submaps,
        "windowRules": [
            _normalize_rule(row, "window")
            for row in _bounded_list(raw.get("windowRules", []), "window rules")
        ],
        "workspaceRules": [
            _mapping(row, "workspace rule", require_nonempty=True)
            for row in _bounded_list(raw.get("workspaceRules", []), "workspace rules")
        ],
        "layerRules": [
            _normalize_rule(row, "layer")
            for row in _bounded_list(raw.get("layerRules", []), "layer rules")
        ],
        "curves": [
            _normalize_curve(row)
            for row in _bounded_list(raw.get("curves", []), "curves")
        ],
        "animations": [
            _normalize_animation(row)
            for row in _bounded_list(raw.get("animations", []), "animations")
        ],
        "startup": [
            _normalize_startup(row)
            for row in _bounded_list(raw.get("startup", []), "startup")
        ],
    }


def _render_bind(bind: Mapping[str, Any], indent: str = "") -> str:
    opts = [f"description = {_lua_string(bind['description'])}"]
    opts.extend(f"{flag} = true" for flag in bind["flags"])
    options = "{ " + ", ".join(opts) + " }"
    return (
        f"{indent}hl.bind({_lua_string(bind['keys'])}, "
        f"hl.dsp.exec_cmd({_lua_string(bind['command'])}), {options})"
    )


def _render_rule(function: str, rule: Mapping[str, Any]) -> str:
    fields: dict[str, Any] = {}
    if rule["name"]:
        fields["name"] = rule["name"]
    fields["match"] = rule["match"]
    for key in sorted(rule["effects"]):
        fields[key] = rule["effects"][key]
    rows = [f"  {key} = {_lua_value(value)}," for key, value in fields.items()]
    return f"{function}({{\n" + "\n".join(rows) + "\n})"


def _render_startup_line(row: Mapping[str, Any], indent: str = "") -> str:
    if row["workspace"]:
        return (
            f"{indent}hl.exec_cmd({_lua_string(row['command'])}, "
            f"{{ workspace = {_lua_string(row['workspace'])} }})"
        )
    return f"{indent}hl.exec_cmd({_lua_string(row['command'])})"


def render_model(raw: Any) -> tuple[dict[str, Any], str]:
    model = normalize_model(raw)
    out = [
        "-- Generated by Maho Settings. Do not hand-edit; use Maho Settings instead.",
        "-- Hyprbind-derived writer architecture attribution is recorded in THIRD_PARTY_NOTICES.md.",
        "-- This file is user-owned state and is loaded after immutable Maho defaults.",
        "",
    ]

    if model["variables"]:
        out.append("-- Variables")
        for row in model["variables"]:
            out.append(f"local {row['name']} = {_lua_string(row['value'])}")
        out.append("")

    if model["environment"]:
        out.append("-- Environment")
        for row in model["environment"]:
            out.append(f"hl.env({_lua_string(row['name'])}, {_lua_string(row['value'])})")
        out.append("")

    global_unbinds = [row for row in model["unbinds"] if not row["submap"]]
    if global_unbinds:
        out.append("-- Shortcut overrides")
        for row in global_unbinds:
            out.append(f"hl.unbind({_lua_string(row['keys'])})")
        out.append("")

    global_binds = [row for row in model["binds"] if not row["submap"]]
    if global_binds:
        out.append("-- Shortcuts")
        out.extend(_render_bind(row) for row in global_binds)
        out.append("")

    for submap in model["submaps"]:
        rows = [row for row in model["binds"] if row["submap"] == submap["name"]]
        removals = [row for row in model["unbinds"] if row["submap"] == submap["name"]]
        if not rows and not removals:
            continue
        out.append(f"-- Submap: {submap['name']}")
        if submap["reset"]:
            out.append(
                f"hl.define_submap({_lua_string(submap['name'])}, "
                f"{_lua_string(submap['reset'])}, function()"
            )
        else:
            out.append(f"hl.define_submap({_lua_string(submap['name'])}, function()")
        out.extend(f"  hl.unbind({_lua_string(row['keys'])})" for row in removals)
        out.extend(_render_bind(row, "  ") for row in rows)
        out.append("end)")
        out.append("")

    if model["windowRules"]:
        out.append("-- Window rules")
        for row in model["windowRules"]:
            out.append(_render_rule("hl.window_rule", row))
            out.append("")

    if model["workspaceRules"]:
        out.append("-- Workspace rules")
        for fields in model["workspaceRules"]:
            out.append(f"hl.workspace_rule({_lua_value(fields)})")
        out.append("")

    if model["layerRules"]:
        out.append("-- Layer rules")
        for row in model["layerRules"]:
            out.append(_render_rule("hl.layer_rule", row))
            out.append("")

    if model["curves"]:
        out.append("-- Curves")
        for row in model["curves"]:
            payload = {"type": "bezier", "points": row["points"]}
            out.append(f"hl.curve({_lua_string(row['name'])}, {_lua_value(payload)})")
        out.append("")

    if model["animations"]:
        out.append("-- Animations")
        for row in model["animations"]:
            payload = {
                "leaf": row["leaf"],
                "enabled": row["enabled"],
                "speed": row["speed"],
                "bezier": row["bezier"],
            }
            if row["style"]:
                payload["style"] = row["style"]
            out.append(f"hl.animation({_lua_value(payload)})")
        out.append("")

    reload_rows = [row for row in model["startup"] if row["when"] == "reload"]
    start_rows = [row for row in model["startup"] if row["when"] == "start"]
    shutdown_rows = [row for row in model["startup"] if row["when"] == "shutdown"]
    if reload_rows or start_rows or shutdown_rows:
        out.append("-- Session startup")
        out.extend(_render_startup_line(row) for row in reload_rows)
        if start_rows:
            out.append('hl.on("hyprland.start", function()')
            out.extend(_render_startup_line(row, "  ") for row in start_rows)
            out.append("end)")
        if shutdown_rows:
            out.append('hl.on("hyprland.shutdown", function()')
            out.extend(_render_startup_line(row, "  ") for row in shutdown_rows)
            out.append("end)")
        out.append("")

    return model, "\n".join(out).rstrip() + "\n"


def _default_run(command: Sequence[str], timeout: float) -> RunResult:
    try:
        proc = subprocess.run(
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "operation timed out"
    except OSError as exc:
        return 127, "", str(exc)


def _reject_symlink(path: Path, label: str) -> None:
    try:
        if path.is_symlink():
            raise ConfigWriteError(f"{label} must not be a symlink: {path}")
    except OSError as exc:
        raise ConfigWriteError(f"could not inspect {label}: {exc}") from exc


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink(path, "managed file")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(temporary, flags, mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
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


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    data = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    _atomic_write(path, data)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot_backup(paths: WriterPaths, previous: bytes | None) -> Path | None:
    if previous is None:
        return None
    paths.backups.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    backup = paths.backups / f"settings.lua.{stamp}.{_sha256(previous)[:12]}.bak"
    counter = 0
    while backup.exists():
        counter += 1
        backup = paths.backups / f"settings.lua.{stamp}.{_sha256(previous)[:12]}.{counter}.bak"
    _atomic_write(backup, previous)
    backups = sorted(
        paths.backups.glob("settings.lua.*.bak"),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )
    for old in backups[BACKUP_KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass
    return backup


def _loader_installed(paths: WriterPaths) -> bool:
    try:
        # The live Maho runtime intentionally exposes hyprland.lua through a
        # symlink. Reading is allowed; this writer never mutates the loader.
        text = paths.loader.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    return 'maho.user.settings' in text and 'package.searchpath' in text


def _syntax_check(path: Path, runner: Runner) -> None:
    lua = shutil.which("lua")
    if not lua:
        raise ConfigWriteError("Lua syntax checker is unavailable")
    # Pass the path inside the -e chunk. Supplying it as the Lua
    # "script" argument would compile it and then execute the generated config,
    # which is not a syntax check and can block on runtime-only APIs.
    check = f"assert(loadfile({_lua_string(str(path))}))"
    code, out, err = runner([lua, "-e", check], 4.0)
    if code != 0:
        raise ConfigWriteError(err or out or "generated Lua failed syntax validation")


def _config_errors(prefix: Sequence[str], runner: Runner) -> tuple[str, ...]:
    code, out, err = runner([*prefix, "configerrors"], 4.0)
    if code != 0:
        raise ConfigWriteError(err or out or "Hyprland config health is unavailable")
    return tuple(line.strip() for line in out.splitlines() if line.strip())


def _reload(prefix: Sequence[str], runner: Runner) -> None:
    code, out, err = runner([*prefix, "reload"], 4.0)
    if code != 0 or (out and out.strip() != "ok"):
        raise ConfigWriteError(err or out or "Hyprland rejected the reload")


@contextmanager
def _writer_lock(paths: WriterPaths):
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    _reject_symlink(paths.lock, "writer lock")
    descriptor = os.open(paths.lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def apply_model(
    raw: Any,
    *,
    paths: WriterPaths | None = None,
    hypr_prefix: Sequence[str] | None = None,
    runner: Runner = _default_run,
    reload_live: bool = True,
    settle_seconds: float = 0.08,
) -> dict[str, Any]:
    paths = paths or default_paths()
    model, rendered = render_model(raw)
    rendered_bytes = rendered.encode("utf-8")
    model_bytes = (json.dumps(model, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")

    with _writer_lock(paths):
        _reject_symlink(paths.config, "managed Hyprland config")
        _reject_symlink(paths.model, "managed Hyprland model")

        previous_config = paths.config.read_bytes() if paths.config.is_file() else None
        previous_model = paths.model.read_bytes() if paths.model.is_file() else None

        if previous_config == rendered_bytes and previous_model == model_bytes:
            return {
                "ok": True,
                "changed": False,
                "path": str(paths.config),
                "modelPath": str(paths.model),
                "sha256": _sha256(rendered_bytes),
            }

        paths.config.parent.mkdir(parents=True, exist_ok=True)
        probe = paths.config.with_name(f".{paths.config.name}.{os.getpid()}.syntax.lua")
        try:
            _atomic_write(probe, rendered_bytes)
            _syntax_check(probe, runner)
        finally:
            try:
                probe.unlink()
            except OSError:
                pass

        baseline_errors: tuple[str, ...] = ()
        if reload_live:
            if not _loader_installed(paths):
                raise ConfigWriteError(
                    "the live Hyprland configuration does not load the Maho Settings user overlay"
                )
            if not hypr_prefix:
                raise ConfigWriteError("a verified Hyprland instance is required for live mutation")
            baseline_errors = _config_errors(hypr_prefix, runner)

        backup = _snapshot_backup(paths, previous_config)
        _atomic_write(paths.config, rendered_bytes)

        try:
            if reload_live:
                _reload(hypr_prefix or [], runner)
                if settle_seconds > 0:
                    time.sleep(settle_seconds)
                observed_errors = _config_errors(hypr_prefix or [], runner)
                if observed_errors != baseline_errors:
                    raise ConfigWriteError(
                        "Hyprland reported new configuration errors after the managed write: "
                        + ("; ".join(observed_errors) if observed_errors else "state changed unexpectedly")
                    )

            _atomic_write(paths.model, model_bytes)
        except BaseException as exc:
            try:
                if previous_config is None:
                    paths.config.unlink(missing_ok=True)
                else:
                    _atomic_write(paths.config, previous_config)
                if previous_model is None:
                    paths.model.unlink(missing_ok=True)
                else:
                    _atomic_write(paths.model, previous_model)
                if reload_live and hypr_prefix:
                    _reload(hypr_prefix, runner)
                    if settle_seconds > 0:
                        time.sleep(settle_seconds)
                    restored = _config_errors(hypr_prefix, runner)
                    if restored != baseline_errors:
                        raise ConfigWriteError(
                            "managed write failed and rollback did not restore baseline config health"
                        ) from exc
            except BaseException as rollback_exc:
                raise ConfigWriteError(f"managed write rollback failed: {rollback_exc}") from exc
            if isinstance(exc, ConfigWriteError):
                raise
            raise ConfigWriteError(str(exc)) from exc

        receipt = {
            "version": 1,
            "timestamp": int(time.time()),
            "path": str(paths.config),
            "modelPath": str(paths.model),
            "configSha256": _sha256(rendered_bytes),
            "modelSha256": _sha256(model_bytes),
            "backup": str(backup) if backup else "",
            "liveReloadVerified": bool(reload_live),
            "baselineConfigErrors": list(baseline_errors),
        }
        _atomic_json(paths.receipt, receipt)
        return {
            "ok": True,
            "changed": True,
            "path": str(paths.config),
            "modelPath": str(paths.model),
            "sha256": receipt["configSha256"],
            "backup": receipt["backup"],
        }


def load_model(*, paths: WriterPaths | None = None) -> dict[str, Any]:
    paths = paths or default_paths()
    try:
        raw = json.loads(paths.model.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {"version": MODEL_VERSION}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigWriteError(f"managed configuration state is unreadable: {exc}") from exc
    return normalize_model(raw)


def status(*, paths: WriterPaths | None = None) -> dict[str, Any]:
    paths = paths or default_paths()
    model_error = ""
    try:
        model = load_model(paths=paths)
    except ConfigWriteError as exc:
        model = {"version": MODEL_VERSION}
        model_error = str(exc)
    receipt: Any = None
    try:
        receipt = json.loads(paths.receipt.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        receipt = None
    backup_count = 0
    try:
        backup_count = sum(1 for _ in paths.backups.glob("settings.lua.*.bak"))
    except OSError:
        pass
    loader_installed = _loader_installed(paths)
    lua_available = shutil.which("lua") is not None
    return {
        "available": lua_available and loader_installed,
        "mutationAvailable": lua_available and loader_installed,
        "loaderInstalled": loader_installed,
        "loaderPath": str(paths.loader),
        "path": str(paths.config),
        "modelPath": str(paths.model),
        "exists": paths.config.is_file() and not paths.config.is_symlink(),
        "model": model,
        "modelError": model_error,
        "backupCount": backup_count,
        "lastWrite": receipt if isinstance(receipt, dict) else {},
    }
