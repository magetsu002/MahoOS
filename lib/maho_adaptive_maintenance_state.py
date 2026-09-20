#!/usr/bin/env python3
"""Closed, expiring execution state for Adaptive's maintenance veto."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import pwd
import re
import stat
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1
KIND = "maho-adaptive-maintenance-veto"
OPERATION = "set-adaptive-maintenance-veto"
EFFECT = "maintenance"
VALUE = "suspended"
MAX_VALIDITY_SECONDS = 120
MAX_STATE_BYTES = 16 * 1024

CONVENIENCE_SOURCE_POLICIES = frozenset({
    "gaming.foreground",
    "workload.interactive",
    "compile.sustained",
    "render.sustained",
})
SAFETY_SOURCE_POLICIES = frozenset({
    "battery.low",
    "battery.conserving",
    "battery.critical",
    "thermal.hot-sustained",
    "thermal.critical-sustained",
    "guardian.reliability-state",
})
ALLOWED_SOURCE_POLICIES = CONVENIENCE_SOURCE_POLICIES | SAFETY_SOURCE_POLICIES

_LEASE = re.compile(r"lease-[0-9a-f]{20}")
_PROPOSAL = re.compile(r"prop-[0-9a-f]{20}")
_STATE_FIELDS = {
    "schema_version", "kind", "active", "lease_id", "effect", "value",
    "source_policy", "source_proposal_id", "captured_at", "updated_at", "valid_until",
}


class MaintenanceVetoError(ValueError):
    pass


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_stamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise MaintenanceVetoError(f"adaptive maintenance {name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MaintenanceVetoError(f"adaptive maintenance {name} is invalid") from exc
    if parsed.tzinfo is None:
        raise MaintenanceVetoError(f"adaptive maintenance {name} is invalid")
    return parsed.astimezone(timezone.utc)


def state_for_lease(
    *, lease_id: str, source_policy: str, source_proposal_id: str,
    captured_at: str, now: datetime,
) -> dict[str, Any]:
    current = now.astimezone(timezone.utc)
    state = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "active": True,
        "lease_id": lease_id,
        "effect": EFFECT,
        "value": VALUE,
        "source_policy": source_policy,
        "source_proposal_id": source_proposal_id,
        "captured_at": captured_at,
        "updated_at": _stamp(current),
        "valid_until": _stamp(current + timedelta(seconds=MAX_VALIDITY_SECONDS)),
    }
    return validate_state(state)


def validate_state(value: Mapping[str, Any]) -> dict[str, Any]:
    state = dict(value)
    if set(state) != _STATE_FIELDS or state.get("schema_version") != SCHEMA_VERSION or state.get("kind") != KIND:
        raise MaintenanceVetoError("adaptive maintenance veto schema is invalid")
    if state.get("active") is not True or state.get("effect") != EFFECT or state.get("value") != VALUE:
        raise MaintenanceVetoError("adaptive maintenance veto scope is invalid")
    if not isinstance(state.get("lease_id"), str) or _LEASE.fullmatch(state["lease_id"]) is None:
        raise MaintenanceVetoError("adaptive maintenance lease identity is invalid")
    if not isinstance(state.get("source_proposal_id"), str) or _PROPOSAL.fullmatch(state["source_proposal_id"]) is None:
        raise MaintenanceVetoError("adaptive maintenance proposal identity is invalid")
    if state.get("source_policy") not in ALLOWED_SOURCE_POLICIES:
        raise MaintenanceVetoError("adaptive maintenance source policy is not certified")
    captured = _parse_stamp(state.get("captured_at"), "capture time")
    updated = _parse_stamp(state.get("updated_at"), "update time")
    valid_until = _parse_stamp(state.get("valid_until"), "validity time")
    if captured > updated or valid_until <= updated:
        raise MaintenanceVetoError("adaptive maintenance veto time ordering is invalid")
    if (valid_until - updated).total_seconds() > MAX_VALIDITY_SECONDS:
        raise MaintenanceVetoError("adaptive maintenance veto validity exceeds certified bound")
    return state


def default_path() -> Path:
    override = os.environ.get("MAHO_ADAPTIVE_MAINTENANCE_VETO_PATH")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    return base / "maho/adaptive/maintenance-veto.json"


def path_for_user(username: str) -> tuple[Path, int]:
    try:
        account = pwd.getpwnam(username)
    except KeyError as exc:
        raise MaintenanceVetoError("adaptive maintenance user identity is unavailable") from exc
    home = Path(account.pw_dir)
    if not home.is_absolute() or home == Path("/"):
        raise MaintenanceVetoError("adaptive maintenance user home is unsafe")
    return home / ".local/state/maho/adaptive/maintenance-veto.json", account.pw_uid


def maintenance_gate_for_user(
    username: str, *, now: datetime | None = None, path: Path | None = None,
    expected_uid: int | None = None,
) -> dict[str, Any]:
    if path is None:
        path, account_uid = path_for_user(username)
        expected_uid = account_uid
    state = read_state(path, now=now, expected_uid=expected_uid)
    if state is None:
        return {
            "ok": True,
            "adaptive_maintenance": "unchanged",
            "veto_active": False,
            "state_path": str(path),
        }
    return {
        "ok": False,
        "adaptive_maintenance": "suspended",
        "veto_active": True,
        "state_path": str(path),
        "lease_id": state["lease_id"],
        "source_policy": state["source_policy"],
        "valid_until": state["valid_until"],
    }


def read_state(
    path: Path, *, now: datetime | None = None, expected_uid: int | None = None,
    require_fresh: bool = True,
) -> dict[str, Any] | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise MaintenanceVetoError("adaptive maintenance veto state is unavailable") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise MaintenanceVetoError("adaptive maintenance veto path is unsafe")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise MaintenanceVetoError("adaptive maintenance veto mode is unsafe")
        if expected_uid is not None and info.st_uid != expected_uid:
            raise MaintenanceVetoError("adaptive maintenance veto owner is invalid")
        if info.st_size > MAX_STATE_BYTES:
            raise MaintenanceVetoError("adaptive maintenance veto state is oversized")
        with os.fdopen(descriptor, "r", encoding="utf-8", errors="strict") as stream:
            descriptor = -1
            raw = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MaintenanceVetoError("adaptive maintenance veto state is unreadable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(raw, Mapping):
        raise MaintenanceVetoError("adaptive maintenance veto state is invalid")
    state = validate_state(raw)
    if require_fresh:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        updated = _parse_stamp(state["updated_at"], "update time")
        valid_until = _parse_stamp(state["valid_until"], "validity time")
        if current < updated - timedelta(seconds=5):
            raise MaintenanceVetoError("adaptive maintenance veto is from the future")
        if current > valid_until:
            raise MaintenanceVetoError("adaptive maintenance veto is stale")
    return state


def _atomic_write(path: Path, state: Mapping[str, Any]) -> None:
    value = validate_state(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _desired(raw: str) -> tuple[bool, dict[str, Any] | None]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MaintenanceVetoError("adaptive maintenance desired state is invalid") from exc
    if not isinstance(value, Mapping) or value.get("operation") != OPERATION or not isinstance(value.get("active"), bool):
        raise MaintenanceVetoError("adaptive maintenance desired state is invalid")
    if value["active"] is False:
        if set(value) != {"operation", "active"}:
            raise MaintenanceVetoError("inactive adaptive maintenance state has extra fields")
        return False, None
    if set(value) != {"operation", "active", "state"} or not isinstance(value.get("state"), Mapping):
        raise MaintenanceVetoError("active adaptive maintenance state is incomplete")
    return True, validate_state(value["state"])


def _capture(path: Path) -> dict[str, Any]:
    state = read_state(path, require_fresh=False)
    return {"present": False} if state is None else {"present": True, "state": state}


def _restore(path: Path, raw: str) -> None:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MaintenanceVetoError("adaptive maintenance rollback state is invalid") from exc
    if not isinstance(value, Mapping) or not isinstance(value.get("present"), bool):
        raise MaintenanceVetoError("adaptive maintenance rollback state is invalid")
    if value["present"] is False:
        if set(value) != {"present"}:
            raise MaintenanceVetoError("adaptive maintenance rollback state has extra fields")
        _remove(path)
        return
    if set(value) != {"present", "state"} or not isinstance(value.get("state"), Mapping):
        raise MaintenanceVetoError("adaptive maintenance rollback state is incomplete")
    _atomic_write(path, value["state"])


def adapter_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="adaptive-maintenance-veto-adapter")
    parser.add_argument("command", choices=("capture", "apply", "verify", "rollback", "verify-rollback"))
    parser.add_argument("payload", nargs="?", default="")
    args = parser.parse_args(argv)
    path = default_path()
    try:
        if args.command == "capture":
            print(json.dumps(_capture(path), sort_keys=True, separators=(",", ":")))
            return 0
        if args.command == "apply":
            active, state = _desired(args.payload)
            _atomic_write(path, state) if active and state is not None else _remove(path)
            return 0
        if args.command == "verify":
            active, state = _desired(args.payload)
            observed = read_state(path, require_fresh=False)
            return 0 if (observed == state if active else observed is None) else 1
        if args.command == "rollback":
            _restore(path, args.payload)
            return 0
        expected = json.loads(args.payload)
        observed = _capture(path)
        return 0 if observed == expected else 1
    except (MaintenanceVetoError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"adaptive-maintenance-veto-adapter: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(adapter_main())
