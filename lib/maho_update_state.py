#!/usr/bin/env python3
"""Authoritative, durable state model for one coherent Maho Update transaction."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1
_SHA40 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TRANSACTION_ID = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")


class UpdateState(str, Enum):
    DISCOVERED = "DISCOVERED"
    STAGED = "STAGED"
    PREPARED = "PREPARED"
    MAINTENANCE_READY = "MAINTENANCE_READY"
    INSTALLING = "INSTALLING"
    INSTALLED_PENDING_ACTIVATION = "INSTALLED_PENDING_ACTIVATION"
    ACTIVE_VERIFYING = "ACTIVE_VERIFYING"
    HEALTHY = "HEALTHY"
    BLOCKED = "BLOCKED"
    FAILED_RECOVERABLE = "FAILED_RECOVERABLE"
    RECOVERING = "RECOVERING"
    RECOVERED = "RECOVERED"
    ATTENTION_REQUIRED = "ATTENTION_REQUIRED"


_PROGRESS = (
    UpdateState.DISCOVERED,
    UpdateState.STAGED,
    UpdateState.PREPARED,
    UpdateState.MAINTENANCE_READY,
    UpdateState.INSTALLING,
    UpdateState.INSTALLED_PENDING_ACTIVATION,
    UpdateState.ACTIVE_VERIFYING,
    UpdateState.HEALTHY,
)
_PROGRESS_INDEX = {state: index for index, state in enumerate(_PROGRESS)}
_TERMINAL = {UpdateState.HEALTHY, UpdateState.RECOVERED, UpdateState.ATTENTION_REQUIRED}
_FAILURE = {
    UpdateState.BLOCKED,
    UpdateState.FAILED_RECOVERABLE,
    UpdateState.RECOVERING,
    UpdateState.RECOVERED,
    UpdateState.ATTENTION_REQUIRED,
}
_TRANSITIONS = {
    UpdateState.DISCOVERED: {UpdateState.STAGED, UpdateState.BLOCKED, UpdateState.FAILED_RECOVERABLE, UpdateState.ATTENTION_REQUIRED},
    UpdateState.STAGED: {UpdateState.PREPARED, UpdateState.BLOCKED, UpdateState.FAILED_RECOVERABLE, UpdateState.ATTENTION_REQUIRED},
    UpdateState.PREPARED: {UpdateState.MAINTENANCE_READY, UpdateState.BLOCKED, UpdateState.FAILED_RECOVERABLE, UpdateState.ATTENTION_REQUIRED},
    UpdateState.MAINTENANCE_READY: {UpdateState.INSTALLING, UpdateState.BLOCKED, UpdateState.FAILED_RECOVERABLE, UpdateState.ATTENTION_REQUIRED},
    UpdateState.INSTALLING: {UpdateState.INSTALLED_PENDING_ACTIVATION, UpdateState.FAILED_RECOVERABLE, UpdateState.RECOVERING, UpdateState.ATTENTION_REQUIRED},
    UpdateState.INSTALLED_PENDING_ACTIVATION: {UpdateState.ACTIVE_VERIFYING, UpdateState.RECOVERING, UpdateState.ATTENTION_REQUIRED},
    UpdateState.ACTIVE_VERIFYING: {UpdateState.HEALTHY, UpdateState.RECOVERING, UpdateState.ATTENTION_REQUIRED},
    UpdateState.FAILED_RECOVERABLE: {UpdateState.RECOVERING, UpdateState.ATTENTION_REQUIRED},
    UpdateState.RECOVERING: {UpdateState.RECOVERED, UpdateState.ATTENTION_REQUIRED},
}


def utc_stamp(now: datetime | None = None) -> str:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return current.isoformat(timespec="seconds").replace("+00:00", "Z")


def new_transaction_id(*, now: datetime | None = None, entropy: str | None = None) -> str:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    suffix = entropy or secrets.token_hex(6)
    if re.fullmatch(r"[0-9a-f]{12}", suffix) is None:
        raise ValueError("update transaction entropy must be twelve lowercase hex characters")
    return f"upd-{current.strftime('%Y%m%dT%H%M%SZ')}-{suffix}"


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} must be a list of non-empty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not contain duplicates")
    return list(value)


def normalize_packages(packages: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for raw in packages:
        package = _mapping(raw, "package")
        name = package.get("name")
        installed = package.get("installed_version")
        candidate = package.get("candidate_version")
        repository = package.get("repository")
        if not isinstance(name, str) or re.fullmatch(r"[a-zA-Z0-9@._+:-]+", name) is None:
            raise ValueError("package name is invalid")
        if name in names:
            raise ValueError("package names must be unique")
        if not isinstance(installed, str) or not installed:
            raise ValueError("installed package version is required")
        if not isinstance(candidate, str) or not candidate or candidate == installed:
            raise ValueError("candidate package version must differ from installed version")
        if not isinstance(repository, str) or not repository:
            raise ValueError("package repository is required")
        names.add(name)
        normalized.append({
            "name": name,
            "installed_version": installed,
            "candidate_version": candidate,
            "repository": repository,
            "download_size": int(package.get("download_size", 0)),
            "installed_size": int(package.get("installed_size", 0)),
            "security_relevant": bool(package.get("security_relevant", False)),
            "roles": sorted(_string_list(package.get("roles", []), f"package {name} roles")),
        })
        if normalized[-1]["download_size"] < 0 or normalized[-1]["installed_size"] < 0:
            raise ValueError("package sizes cannot be negative")
    if not normalized:
        raise ValueError("a coherent update requires at least one package")
    return sorted(normalized, key=lambda item: item["name"])


def package_generation_id(packages: Iterable[Mapping[str, Any]]) -> str:
    canonical = normalize_packages(packages)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return "pkg-" + hashlib.sha256(encoded).hexdigest()


def _validate_package_generation(value: Any) -> dict[str, Any]:
    generation = dict(_mapping(value, "package_generation"))
    packages = normalize_packages(generation.get("packages", []))
    expected = package_generation_id(packages)
    if generation.get("id") != expected:
        raise ValueError("package generation identity does not match exact candidates")
    generation["packages"] = packages
    return generation


def _validate_activation(value: Any) -> dict[str, Any]:
    activation = dict(_mapping(value, "activation"))
    if not isinstance(activation.get("required"), bool):
        raise ValueError("activation.required must be boolean")
    activation["requirements"] = _string_list(activation.get("requirements"), "activation requirements")
    if activation["required"] != bool(activation["requirements"]):
        raise ValueError("activation requirement identity is ambiguous")
    if activation.get("native_execution_certified") is not False:
        raise ValueError("M4A native execution certification must remain false")
    return activation


def _validate_recovery(value: Any) -> dict[str, Any]:
    recovery = dict(_mapping(value, "recovery"))
    generation_id = recovery.get("generation_id")
    if generation_id is not None and (not isinstance(generation_id, str) or not generation_id.startswith("g3-")):
        raise ValueError("recovery generation identity is invalid")
    if recovery.get("native_l3_certified") is not False:
        raise ValueError("native L3 certification must remain false in M4A")
    return recovery


def _state(value: Any) -> UpdateState:
    try:
        return UpdateState(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid update state") from exc


def _validate_history(data: Mapping[str, Any]) -> None:
    history = data.get("history")
    if not isinstance(history, list) or not history:
        raise ValueError("update history is required")
    previous: UpdateState | None = None
    previous_time = ""
    last_progress = UpdateState.DISCOVERED
    for index, raw in enumerate(history):
        event = _mapping(raw, f"history[{index}]")
        state = _state(event.get("state"))
        at = event.get("at")
        if not isinstance(at, str) or not at or at < previous_time:
            raise ValueError("update history timestamps must be monotonic")
        blockers = _string_list(event.get("blockers", []), "event blockers")
        reason = event.get("reason", "")
        if not isinstance(reason, str):
            raise ValueError("event reason must be text")
        if state in {UpdateState.BLOCKED, UpdateState.ATTENTION_REQUIRED} and not (blockers or reason):
            raise ValueError("blocked and attention states require an explanation")
        if state not in {UpdateState.BLOCKED, UpdateState.ATTENTION_REQUIRED} and blockers:
            raise ValueError("blockers are only valid on blocked or attention states")
        if previous is None:
            if state is not UpdateState.DISCOVERED:
                raise ValueError("update history must begin DISCOVERED")
        else:
            allowed = set(_TRANSITIONS.get(previous, set()))
            if previous is UpdateState.BLOCKED:
                allowed = {last_progress, UpdateState.ATTENTION_REQUIRED}
            if state not in allowed:
                raise ValueError(f"illegal update transition: {previous.value} -> {state.value}")
        if state in _PROGRESS_INDEX:
            if _PROGRESS_INDEX[state] < _PROGRESS_INDEX[last_progress]:
                raise ValueError("update progress cannot move backward")
            last_progress = state
        previous = state
        previous_time = at
    if previous != _state(data.get("state")):
        raise ValueError("update state does not match history tail")
    if data.get("updated_at") != history[-1].get("at"):
        raise ValueError("update timestamp does not match history tail")


def validate_transaction(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported update transaction schema")
    transaction_id = data.get("transaction_id")
    if not isinstance(transaction_id, str) or _TRANSACTION_ID.fullmatch(transaction_id) is None:
        raise ValueError("invalid update transaction identity")
    if not isinstance(data.get("source_revision"), str) or _SHA40.fullmatch(data["source_revision"]) is None:
        raise ValueError("update source revision must be an exact Git SHA")
    for key in ("created_at", "updated_at"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError(f"{key} is required")
    data["state"] = _state(data.get("state")).value
    data["package_generation"] = _validate_package_generation(data.get("package_generation"))
    data["activation"] = _validate_activation(data.get("activation"))
    data["recovery"] = _validate_recovery(data.get("recovery"))
    if not isinstance(data.get("reason", ""), str):
        raise ValueError("transaction reason must be text")
    data["blockers"] = _string_list(data.get("blockers", []), "transaction blockers")
    _validate_history(data)
    tail = data["history"][-1]
    if data["reason"] != tail.get("reason", "") or data["blockers"] != tail.get("blockers", []):
        raise ValueError("transaction explanation does not match history tail")
    return data


def create_transaction(
    *,
    transaction_id: str,
    source_revision: str,
    packages: Sequence[Mapping[str, Any]],
    activation_requirements: Sequence[str],
    recovery_generation_id: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized = normalize_packages(packages)
    stamp = utc_stamp(now)
    return validate_transaction({
        "schema_version": SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "state": UpdateState.DISCOVERED.value,
        "created_at": stamp,
        "updated_at": stamp,
        "source_revision": source_revision,
        "package_generation": {"id": package_generation_id(normalized), "packages": normalized},
        "activation": {
            "required": bool(activation_requirements),
            "requirements": list(activation_requirements),
            "native_execution_certified": False,
        },
        "recovery": {"generation_id": recovery_generation_id, "native_l3_certified": False},
        "reason": "",
        "blockers": [],
        "history": [{"state": UpdateState.DISCOVERED.value, "at": stamp, "reason": "", "blockers": []}],
    })


def transition_transaction(
    payload: Mapping[str, Any],
    next_state: UpdateState | str,
    *,
    reason: str = "",
    blockers: Sequence[str] = (),
    evidence: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = validate_transaction(payload)
    previous = _state(current["state"])
    target = _state(next_state)
    if previous in _TERMINAL:
        raise ValueError(f"terminal update state cannot transition: {previous.value}")
    allowed = set(_TRANSITIONS.get(previous, set()))
    if previous is UpdateState.BLOCKED:
        prior = [_state(item["state"]) for item in current["history"][:-1] if _state(item["state"]) in _PROGRESS_INDEX]
        allowed = {prior[-1], UpdateState.ATTENTION_REQUIRED} if prior else {UpdateState.ATTENTION_REQUIRED}
    if target not in allowed:
        raise ValueError(f"illegal update transition: {previous.value} -> {target.value}")
    stamp = utc_stamp(now)
    event: dict[str, Any] = {"state": target.value, "at": stamp, "reason": reason, "blockers": list(blockers)}
    if evidence is not None:
        json.dumps(evidence, sort_keys=True)
        event["evidence"] = dict(evidence)
    updated = dict(current)
    updated["state"] = target.value
    updated["updated_at"] = stamp
    updated["reason"] = reason
    updated["blockers"] = list(blockers)
    updated["history"] = [dict(item) for item in current["history"]] + [event]
    return validate_transaction(updated)


def transaction_path(root: str | os.PathLike[str], transaction_id: str) -> Path:
    if _TRANSACTION_ID.fullmatch(transaction_id) is None:
        raise ValueError("invalid update transaction identity")
    return Path(root) / "transactions" / f"{transaction_id}.json"


def write_transaction(path: str | os.PathLike[str], payload: Mapping[str, Any]) -> None:
    destination = Path(path)
    data = validate_transaction(payload)
    if destination.name != f"{data['transaction_id']}.json":
        raise ValueError("transaction path does not match immutable identity")
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = destination.parent / f".{destination.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def read_transaction(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read update transaction: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("update transaction root must be an object")
    data = validate_transaction(raw)
    if source.name != f"{data['transaction_id']}.json":
        raise ValueError("transaction path does not match immutable identity")
    return data


def publish_transaction(root: str | os.PathLike[str], payload: Mapping[str, Any]) -> Path:
    """Durably publish a transaction and its exact current pointer for product consumers."""
    data = validate_transaction(payload)
    base = Path(root)
    path = transaction_path(base, data["transaction_id"])
    write_transaction(path, data)
    pointer = base / "current"
    pointer.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = pointer.parent / f".current.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data["transaction_id"] + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, pointer)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return path


def transaction_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = validate_transaction(payload)
    timestamps = {state.value.lower(): None for state in UpdateState}
    for event in data["history"]:
        timestamps[event["state"].lower()] = event["at"]
    packages = data["package_generation"]["packages"]
    return {
        "schema_version": SCHEMA_VERSION,
        "transaction_id": data["transaction_id"],
        "state": data["state"],
        "source_revision": data["source_revision"],
        "package_generation_id": data["package_generation"]["id"],
        "timestamps": timestamps,
        "package_changes": [{"name": item["name"], "from": item["installed_version"], "to": item["candidate_version"]} for item in packages],
        "maho_runtime_changes": [item["name"] for item in packages if "maho-runtime" in item["roles"]],
        "kernel_changes": [item["name"] for item in packages if "kernel" in item["roles"]],
        "security_changes": [item["name"] for item in packages if item["security_relevant"]],
        "recovery_generation": data["recovery"]["generation_id"],
        "activation_required": data["activation"]["required"],
        "activation_requirements": data["activation"]["requirements"],
        "result": data["reason"],
        "blockers": data["blockers"],
    }
