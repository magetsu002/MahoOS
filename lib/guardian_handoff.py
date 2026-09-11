#!/usr/bin/env python3
"""Bounded evidence preservation and L4 handoff records for Guardian."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

MAX_ITEMS = 32
MAX_PROCESS_ROWS = 24
MAX_BYTES = 262144

_SECRET_KEY_PARTS = ("password", "token", "cookie", "private_key", "secret", "authorization")
_SECRET_VALUE = re.compile(
    r"(?i)(?:\bbearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"\b(?:sk|gh[pousr])[-_][A-Za-z0-9_-]{12,}|"
    r"\b(?:password|token|secret|api[_-]?key)\s*[=:]\s*\S+)"
)

_SIMPLE_TOP = {
    "boot_id", "guardian_version", "guardian_source_revision",
}
_SCHEMA = {
    "incident_identity": {"id", "incident_id", "subject_type", "subject_id", "source_kind"},
    "timestamps": {"detected_at", "observed_at", "updated_at", "captured_at", "booted_at"},
    "runtime_identity": {"generation", "path", "content_sha256", "source_revision", "manifest_version"},
    "kernel_identity": {"release", "package", "version", "path", "sha256"},
    "root_filesystem_identity": {"uuid", "source", "fsroot", "fstype", "subvolume"},
}
_ROW_SCHEMA = {
    "recovery_generation_evidence": {
        "id", "generation_id", "snapshot_id", "filesystem_uuid", "home_scope", "eligible",
        "coherent", "boot_state_coherent", "kernel_package", "kernel_version", "kernel_sha256",
        "initramfs_sha256", "verification_status", "rejection_reasons",
    },
    "active_high_severity_signals": {
        "class", "status", "confidence", "source", "subject", "observed_at", "sha256", "risk",
    },
    "process_metadata": {"pid", "uid", "gid", "name", "comm", "exe", "package", "unit", "cgroup"},
}
_EVENT_ITEM_FIELDS = {"path", "kind", "risk", "sha256", "expected_sha256", "observed_sha256", "package"}
_NETWORK_ITEM_FIELDS = {"address", "port", "protocol", "family", "pid", "uid", "exe", "package", "exposure"}
_DECISION_FIELDS = {
    "severity", "label", "catastrophic", "lifecycle", "terminal_state",
    "automatic_recovery_allowed", "automatic_host_mutation_allowed", "trusted_boundaries",
    "untrusted_boundaries", "unknown_boundaries", "catastrophic_reasons", "safe_actions",
    "unsafe_actions", "evidence_preservation_required", "recovery_handoff", "fail_closed",
    "host_mutation_performed", "prevented", "guardian_authority_degraded",
}


def _safe_text(value: str, limit: int = 4096) -> str:
    text = value[:limit]
    return "[redacted]" if _SECRET_VALUE.search(text) else text


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _safe_text(str(value), 1024)


def _safe_sequence(value: Any) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_safe_scalar(item) for item in value[:MAX_ITEMS]]


def _select_mapping(value: Any, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key in sorted(allowed):
        if key not in value or any(part in key.lower() for part in _SECRET_KEY_PARTS):
            continue
        item = value[key]
        if isinstance(item, (list, tuple)):
            out[key] = _safe_sequence(item)
        elif isinstance(item, Mapping):
            continue
        else:
            out[key] = _safe_scalar(item)
    return out


def _select_rows(value: Any, allowed: set[str], limit: int = MAX_ITEMS) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_select_mapping(row, allowed) for row in value[:limit] if isinstance(row, Mapping)]


def _event_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    out = _select_mapping(
        value,
        {"result", "status", "state_sha256", "baseline_sha256", "package", "packages", "observed_at"},
    )
    for field in ("added", "removed", "changed", "missing", "unreadable", "items"):
        if field in value:
            out[field] = _select_rows(value[field], _EVENT_ITEM_FIELDS)
    return out


def _network_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    out = _select_mapping(value, {"result", "status", "state_sha256", "observed_at"})
    for field in ("listeners", "exposed"):
        if field in value:
            out[field] = _select_rows(value[field], _NETWORK_ITEM_FIELDS)
    single = _select_mapping(value, _NETWORK_ITEM_FIELDS)
    out.update(single)
    return out


def _authority_decision(value: Mapping[str, Any]) -> dict[str, Any]:
    out = _select_mapping(value, _DECISION_FIELDS)
    for field in (
        "trusted_boundaries", "untrusted_boundaries", "unknown_boundaries", "catastrophic_reasons",
        "safe_actions", "unsafe_actions", "recovery_handoff",
    ):
        if field in value:
            out[field] = _safe_sequence(value[field])
    return out


def build_evidence_record(observation: Mapping[str, Any], authority_decision: Mapping[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {"version": 1, "kind": "guardian-catastrophic-evidence"}
    for key in _SIMPLE_TOP:
        if key in observation:
            record[key] = _safe_scalar(observation[key])
    for key, schema in _SCHEMA.items():
        if key in observation:
            record[key] = _select_mapping(observation[key], schema)
    for key, schema in _ROW_SCHEMA.items():
        if key in observation:
            limit = MAX_PROCESS_ROWS if key == "process_metadata" else MAX_ITEMS
            record[key] = _select_rows(observation[key], schema, limit)
    for key in ("privilege_evidence", "integrity_evidence", "persistence_evidence"):
        if key in observation:
            record[key] = _event_evidence(observation[key])
    if "network_evidence" in observation:
        record["network_evidence"] = _network_evidence(observation["network_evidence"])
    record["authority_decision"] = _authority_decision(authority_decision)
    return record


def preserve_evidence(path: Path, record: Mapping[str, Any]) -> Path:
    data = (json.dumps(record, sort_keys=True, indent=2) + "\n").encode()
    if len(data) > MAX_BYTES:
        raise ValueError("catastrophic evidence record exceeds bounded storage contract")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return path


def handoff_summary(decision: Mapping[str, Any], evidence_path: str | None = None) -> dict[str, Any]:
    return {
        "severity": 4,
        "label": "catastrophic",
        "automatic_recovery_allowed": False,
        "automatic_host_mutation_allowed": False,
        "trusted_boundaries": list(decision.get("trusted_boundaries") or []),
        "untrusted_boundaries": list(decision.get("untrusted_boundaries") or []),
        "catastrophic_reasons": list(decision.get("catastrophic_reasons") or []),
        "safe_actions": list(decision.get("safe_actions") or []),
        "unsafe_actions": list(decision.get("unsafe_actions") or []),
        "evidence_preservation_required": True,
        "evidence_path": evidence_path,
        "recovery_handoff": list(decision.get("recovery_handoff") or []),
        "host_mutation_performed": False,
    }
