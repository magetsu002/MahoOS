#!/usr/bin/env python3
"""Durable host authority for production normal-impact Maho Update execution."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from typing import Any, Mapping, Sequence

_SHA40 = re.compile(r"[0-9a-f]{40}")
_SHA64 = re.compile(r"[0-9a-f]{64}")
_TX = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
_PKG = re.compile(r"pkg-[0-9a-f]{64}")
_ART = re.compile(r"art-[0-9a-f]{64}")
DEFAULT_AUTHORITY_PATH = Path("/var/lib/maho/update/normal-execution-authority.json")


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def machine_identity() -> str:
    try:
        value = Path("/etc/machine-id").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("machine identity is unavailable") from exc
    if not value:
        raise ValueError("machine identity is unavailable")
    return hashlib.sha256(value.encode()).hexdigest()


def certification_confirmation(source_revision: str) -> str:
    if _SHA40.fullmatch(source_revision) is None:
        raise ValueError("normal certification source revision is invalid")
    return f"CERTIFY-NORMAL:{source_revision}"


def issue_normal_execution_authority(
    *,
    source_revision: str,
    transaction_id: str,
    package_generation_id: str,
    graph_id: str,
    packages: Sequence[Mapping[str, Any]],
    effects: Sequence[str],
    activation_requirements: Sequence[str],
    verification: Mapping[str, Any],
    candidate_root_identity: str,
    base_root_identity: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    if _SHA40.fullmatch(source_revision) is None or _TX.fullmatch(transaction_id) is None:
        raise ValueError("normal execution authority source/transaction identity is invalid")
    if _PKG.fullmatch(package_generation_id) is None or _ART.fullmatch(graph_id) is None:
        raise ValueError("normal execution authority package/graph identity is invalid")
    if not candidate_root_identity or not base_root_identity:
        raise ValueError("normal execution authority root identity is incomplete")
    rows: list[dict[str, Any]] = []
    for raw in packages:
        row = dict(raw)
        required = {"name", "installed_version", "candidate_version", "sha256"}
        if set(row) != required or any(not isinstance(row[k], str) or not row[k] for k in required):
            raise ValueError("normal execution authority package evidence is invalid")
        if _SHA64.fullmatch(row["sha256"]) is None or row["installed_version"] == row["candidate_version"]:
            raise ValueError("normal execution authority package transition is invalid")
        rows.append(row)
    if not rows or not isinstance(verification, Mapping) or verification.get("ok") is not True:
        raise ValueError("normal execution authority requires successful verification evidence")
    stamp = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    material = {
        "schema_version": 1,
        "kind": "maho-normal-update-host-authority",
        "authority_scope": "execute-normal-impact-update-generations",
        "source_revision": source_revision,
        "machine_identity_sha256": machine_identity(),
        "certified_at": stamp,
        "certification_transaction_id": transaction_id,
        "certification_package_generation_id": package_generation_id,
        "certification_graph_id": graph_id,
        "candidate_root_identity": candidate_root_identity,
        "base_root_identity": base_root_identity,
        "packages": sorted(rows, key=lambda item: item["name"]),
        "certified_effects": sorted(set(str(item) for item in effects)),
        "certified_activation_requirements": sorted(set(str(item) for item in activation_requirements)),
        "verification": dict(verification),
    }
    return material | {"authority_id": "normal-" + hashlib.sha256(_canonical(material)).hexdigest()}


def verify_normal_execution_authority(value: Mapping[str, Any], *, source_revision: str) -> dict[str, Any]:
    data = dict(value)
    authority_id = data.pop("authority_id", None)
    if data.get("schema_version") != 1 or data.get("kind") != "maho-normal-update-host-authority":
        raise ValueError("normal execution authority schema is invalid")
    if data.get("authority_scope") != "execute-normal-impact-update-generations":
        raise ValueError("normal execution authority scope is invalid")
    if data.get("source_revision") != source_revision or _SHA40.fullmatch(source_revision) is None:
        raise ValueError("normal execution authority source revision drifted")
    if data.get("machine_identity_sha256") != machine_identity():
        raise ValueError("normal execution authority belongs to another machine")
    if _TX.fullmatch(str(data.get("certification_transaction_id", ""))) is None:
        raise ValueError("normal execution authority transaction identity is invalid")
    if _PKG.fullmatch(str(data.get("certification_package_generation_id", ""))) is None:
        raise ValueError("normal execution authority package generation identity is invalid")
    if _ART.fullmatch(str(data.get("certification_graph_id", ""))) is None:
        raise ValueError("normal execution authority Guardian graph identity is invalid")
    effects = data.get("certified_effects")
    activation = data.get("certified_activation_requirements")
    if not isinstance(effects, list) or not effects or any(not isinstance(x, str) or not x for x in effects):
        raise ValueError("normal execution authority effect scope is invalid")
    if not isinstance(activation, list) or any(not isinstance(x, str) or not x for x in activation):
        raise ValueError("normal execution authority activation scope is invalid")
    packages = data.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("normal execution authority package evidence is missing")
    for raw in packages:
        if not isinstance(raw, Mapping):
            raise ValueError("normal execution authority package evidence is invalid")
        if _SHA64.fullmatch(str(raw.get("sha256", ""))) is None:
            raise ValueError("normal execution authority package digest is invalid")
        if not all(isinstance(raw.get(k), str) and raw[k] for k in ("name", "installed_version", "candidate_version")):
            raise ValueError("normal execution authority package identity is invalid")
        if raw["installed_version"] == raw["candidate_version"]:
            raise ValueError("normal execution authority package transition is invalid")
    if not isinstance(data.get("verification"), Mapping) or data["verification"].get("ok") is not True:
        raise ValueError("normal execution authority lacks successful verification")
    expected = "normal-" + hashlib.sha256(_canonical(data)).hexdigest()
    if authority_id != expected:
        raise ValueError("normal execution authority identity mismatch")
    return data | {"authority_id": authority_id}



def authorize_normal_plan(
    value: Mapping[str, Any], *, source_revision: str,
    effects: Sequence[str], activation_requirements: Sequence[str],
) -> dict[str, Any]:
    authority = verify_normal_execution_authority(value, source_revision=source_revision)
    certified_effects = set(authority.get("certified_effects", []))
    certified_activation = set(authority.get("certified_activation_requirements", []))
    requested_effects = set(str(item) for item in effects)
    requested_activation = set(str(item) for item in activation_requirements)
    if not requested_effects or not requested_effects.issubset(certified_effects):
        raise ValueError("normal execution effects exceed certified host authority")
    if not requested_activation.issubset(certified_activation):
        raise ValueError("normal activation requirements exceed certified host authority")
    return authority

def publish_normal_execution_authority(value: Mapping[str, Any], path: Path = DEFAULT_AUTHORITY_PATH) -> Path:
    verified = verify_normal_execution_authority(value, source_revision=str(value.get("source_revision", "")))
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o755)
    encoded = (json.dumps(verified, indent=2, sort_keys=True) + "\n").encode()
    temp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path); os.chmod(path, 0o644)
    finally:
        try: temp.unlink()
        except FileNotFoundError: pass
    return path


def load_normal_execution_authority(*, source_revision: str, path: Path = DEFAULT_AUTHORITY_PATH) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("normal execution authority is unavailable") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("normal execution authority is invalid")
    return verify_normal_execution_authority(raw, source_revision=source_revision)
