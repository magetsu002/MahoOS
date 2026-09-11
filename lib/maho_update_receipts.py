#!/usr/bin/env python3
"""Authoritative update receipts and quiet product-facing status projections."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
from typing import Any, Mapping

from maho_update_state import UpdateState, transaction_receipt, validate_transaction


def build_receipt(transaction: Mapping[str, Any]) -> dict[str, Any]:
    data = validate_transaction(transaction)
    base = transaction_receipt(data)
    timestamps = base.pop("timestamps")
    receipt = {
        **base,
        "discovered_time": timestamps["discovered"],
        "staged_time": timestamps["staged"],
        "prepared_time": timestamps["prepared"],
        "maintenance_ready_time": timestamps["maintenance_ready"],
        "installation_time": timestamps["installed_pending_activation"],
        "activation_time": timestamps["active_verifying"],
        "verification_time": timestamps["healthy"],
        "recovery_time": timestamps["recovered"],
        "attention_time": timestamps["attention_required"],
        "updated_at": data["updated_at"],
    }
    return receipt


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o755)
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o644)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def record_receipt(root: str | os.PathLike[str], transaction: Mapping[str, Any]) -> Path:
    receipt = build_receipt(transaction)
    directory = Path(root) / "receipts"
    path = directory / f"{receipt['transaction_id']}.json"
    if path.is_symlink():
        raise ValueError("receipt path cannot be a symlink")
    if path.is_file():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"existing receipt is invalid: {exc}") from exc
        for key in ("transaction_id", "source_revision", "package_generation_id"):
            if previous.get(key) != receipt[key]:
                raise ValueError("receipt immutable identity changed")
        previous_time = previous.get("updated_at")
        if not isinstance(previous_time, str) or previous_time > receipt["updated_at"]:
            raise ValueError("receipt history cannot move backward")
    _write_json_atomic(path, receipt)
    return path


def load_history(root: str | os.PathLike[str], *, limit: int = 50) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise ValueError("receipt history limit must be between 1 and 500")
    directory = Path(root) / "receipts"
    if not directory.is_dir():
        return []
    receipts: list[dict[str, Any]] = []
    for path in directory.glob("upd-*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("transaction_id") == path.stem and isinstance(value.get("updated_at"), str):
            receipts.append(value)
    receipts.sort(key=lambda item: (item["updated_at"], item["transaction_id"]), reverse=True)
    return receipts[:limit]


def product_status(transaction: Mapping[str, Any], *, history: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    data = validate_transaction(transaction)
    receipt = build_receipt(data)
    state = UpdateState(data["state"])
    labels = {
        UpdateState.HEALTHY: "Healthy",
        UpdateState.INSTALLED_PENDING_ACTIVATION: "Activates next restart",
        UpdateState.ATTENTION_REQUIRED: "Attention required",
        UpdateState.RECOVERED: "Recovered",
        UpdateState.RECOVERING: "Recovering",
        UpdateState.INSTALLING: "Maintaining",
        UpdateState.ACTIVE_VERIFYING: "Verifying",
    }
    label = labels.get(state, "Maintenance queued")
    prior = list(history or [])
    healthy = next((item for item in prior if item.get("state") == UpdateState.HEALTHY.value), None)
    last_maintenance = receipt["verification_time"] if state is UpdateState.HEALTHY else (healthy or {}).get("verification_time")
    attention = state is UpdateState.ATTENTION_REQUIRED
    return {
        "schema_version": 1,
        "transaction_id": data["transaction_id"],
        "authority_state": state.value,
        "status": label,
        "last_maintenance": last_maintenance,
        "activation_pending": state is UpdateState.INSTALLED_PENDING_ACTIVATION,
        "attention_required": attention,
        "blockers": list(data["blockers"]) if state in {UpdateState.BLOCKED, UpdateState.ATTENTION_REQUIRED} else [],
        "notification_policy": "one-meaningful-attention" if attention else "none",
        "receipt": receipt,
    }


def format_receipt(receipt: Mapping[str, Any]) -> str:
    changes = receipt.get("package_changes", [])
    package_lines = [f"  {item['name']}: {item['from']} -> {item['to']}" for item in changes]
    blockers = receipt.get("blockers", [])
    lines = [
        "Maho Update receipt",
        f"Transaction: {receipt.get('transaction_id', 'unknown')}",
        f"State: {receipt.get('state', 'unknown')}",
        f"Discovered: {receipt.get('discovered_time') or 'not recorded'}",
        f"Staged: {receipt.get('staged_time') or 'not recorded'}",
        f"Prepared: {receipt.get('prepared_time') or 'not recorded'}",
        f"Installed: {receipt.get('installation_time') or 'not recorded'}",
        f"Activated: {receipt.get('activation_time') or 'not recorded'}",
        f"Verified: {receipt.get('verification_time') or 'not recorded'}",
        f"Recovery generation: {receipt.get('recovery_generation') or 'not bound'}",
        "Package changes:",
        *(package_lines or ["  none"]),
        f"Result: {receipt.get('result') or 'in progress'}",
        f"Blockers: {', '.join(blockers) if blockers else 'none'}",
    ]
    return "\n".join(lines)
