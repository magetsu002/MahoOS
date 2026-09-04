#!/usr/bin/env python3
"""Single, atomic position authority for every Maho Link mode."""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = 3


def finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def v3_position(payload: dict[str, Any]) -> tuple[float, float] | None:
    if payload.get("version") != VERSION:
        return None
    x = finite(payload.get("x"))
    y = finite(payload.get("y"))
    return (x, y) if x is not None and y is not None else None


def migrated_position(
    payload: dict[str, Any], monitor_width: float, monitor_height: float,
    margin_x: float, margin_y: float,
) -> tuple[float, float] | None:
    """Read legacy v1/v2 coordinates without ever preferring them to v3."""
    if payload.get("valid") is False:
        return None

    version = payload.get("version")
    if version == 2:
        x = finite(payload.get("pixelX"))
        y = finite(payload.get("pixelY"))
        if x is not None and y is not None:
            return x, y

    if version == 1:
        normalized_x = finite(payload.get("normalizedX"))
        normalized_y = finite(payload.get("normalizedY"))
        if normalized_x is not None and normalized_y is not None:
            span_x = max(1.0, monitor_width - margin_x * 2.0)
            span_y = max(1.0, monitor_height - margin_y * 2.0)
            return (
                margin_x + span_x * min(1.0, max(0.0, normalized_x)),
                margin_y + span_y * min(1.0, max(0.0, normalized_y)),
            )
    return None


def clamp_position(
    x: float, y: float, monitor_width: float, monitor_height: float,
    surface_width: float, surface_height: float, margin_x: float, margin_y: float,
) -> tuple[float, float]:
    maximum_x = max(margin_x, monitor_width - surface_width - margin_x)
    maximum_y = max(margin_y, monitor_height - surface_height - margin_y)
    return (
        min(maximum_x, max(margin_x, x)),
        min(maximum_y, max(margin_y, y)),
    )


def make_state(
    x: float, y: float, monitor: str, monitor_width: float, monitor_height: float,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "version": VERSION,
        "x": x,
        "y": y,
        "monitor_width": monitor_width,
        "monitor_height": monitor_height,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if monitor:
        state["monitor"] = monitor
    return state


def load_position(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.path)
    payload = read_json(path) if path.exists() else None
    requested = v3_position(payload) if payload is not None else None
    source = "v3"

    if path.exists() and requested is None:
        legacy = migrated_position(
            payload or {}, args.monitor_width, args.monitor_height,
            args.margin_x, args.margin_y,
        )
        if legacy is None:
            return {"valid": False, "mode": args.mode, "source": "invalid"}
        requested = legacy
        source = "migrated-target"
        atomic_json_write(path, make_state(
            requested[0], requested[1], args.monitor,
            args.monitor_width, args.monitor_height,
        ))

    if requested is None:
        for legacy_name in args.legacy:
            legacy_path = Path(legacy_name)
            legacy_payload = read_json(legacy_path)
            if legacy_payload is None:
                continue
            requested = migrated_position(
                legacy_payload, args.monitor_width, args.monitor_height,
                args.margin_x, args.margin_y,
            )
            if requested is None:
                continue
            source = f"migrated:{legacy_path}"
            atomic_json_write(path, make_state(
                requested[0], requested[1], args.monitor,
                args.monitor_width, args.monitor_height,
            ))
            break

    if requested is None:
        return {"valid": False, "mode": args.mode, "source": "missing"}

    applied = clamp_position(
        requested[0], requested[1], args.monitor_width, args.monitor_height,
        args.surface_width, args.surface_height, args.margin_x, args.margin_y,
    )
    return {
        "valid": True,
        "version": VERSION,
        "mode": args.mode,
        "source": source,
        "requested_x": requested[0],
        "requested_y": requested[1],
        "x": applied[0],
        "y": applied[1],
        "clamped": applied != requested,
    }


def add_geometry(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--monitor", default="")
    parser.add_argument("--monitor-width", type=float, required=True)
    parser.add_argument("--monitor-height", type=float, required=True)
    parser.add_argument("--surface-width", type=float, required=True)
    parser.add_argument("--surface-height", type=float, required=True)
    parser.add_argument("--margin-x", type=float, required=True)
    parser.add_argument("--margin-y", type=float, required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    load = commands.add_parser("load")
    load.add_argument("--path", required=True)
    load.add_argument("--legacy", action="append", default=[])
    load.add_argument("--mode", choices=("wifi", "bluetooth"), required=True)
    add_geometry(load)

    save = commands.add_parser("save")
    save.add_argument("--path", required=True)
    save.add_argument("--mode", choices=("wifi", "bluetooth"), required=True)
    save.add_argument("--x", type=float, required=True)
    save.add_argument("--y", type=float, required=True)
    save.add_argument("--monitor", default="")
    save.add_argument("--monitor-width", type=float, required=True)
    save.add_argument("--monitor-height", type=float, required=True)

    report = commands.add_parser("report")
    report.add_argument("--path", required=True)
    report.add_argument("--mode", choices=("wifi", "bluetooth"), required=True)
    report.add_argument("--requested-x", type=float, required=True)
    report.add_argument("--requested-y", type=float, required=True)
    report.add_argument("--x", type=float, required=True)
    report.add_argument("--y", type=float, required=True)
    report.add_argument("--width", type=float, required=True)
    report.add_argument("--height", type=float, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "load":
        print(json.dumps(load_position(args), ensure_ascii=False))
        return 0
    if args.command == "save":
        atomic_json_write(Path(args.path), make_state(
            args.x, args.y, args.monitor, args.monitor_width, args.monitor_height,
        ))
        return 0
    if args.command == "report":
        atomic_json_write(Path(args.path), {
            "version": 1,
            "mode": args.mode,
            "requested_x": args.requested_x,
            "requested_y": args.requested_y,
            "x": args.x,
            "y": args.y,
            "width": args.width,
            "height": args.height,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
