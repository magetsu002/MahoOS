#!/usr/bin/env python3
"""Read-only product CLI for authoritative Maho Update state and receipts."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from typing import Any

from maho_update_receipts import build_receipt, format_receipt, load_history, product_status
from maho_update_normal_authority import DEFAULT_AUTHORITY_PATH, load_normal_execution_authority
from maho_update_state import read_transaction, transaction_path

_TXID = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")


def state_root() -> Path:
    override = os.environ.get("MAHO_UPDATE_STATE_ROOT")
    return Path(override) if override else Path("/var/lib/maho/update")


def current_transaction(root: Path) -> dict[str, Any] | None:
    pointer = root / "current"
    if not pointer.exists():
        return None
    if pointer.is_symlink() or not pointer.is_file():
        raise ValueError("current update pointer is unsafe")
    transaction_id = pointer.read_text(encoding="utf-8").strip()
    if _TXID.fullmatch(transaction_id) is None:
        raise ValueError("current update pointer identity is invalid")
    return read_transaction(transaction_path(root, transaction_id))


def unavailable_status(root: Path) -> dict[str, Any]:
    history = load_history(root)
    healthy = next((item for item in history if item.get("state") == "HEALTHY"), None)
    return {
        "schema_version": 1,
        "transaction_id": None,
        "authority_state": "NONE",
        "status": "Healthy",
        "last_maintenance": (healthy or {}).get("verification_time"),
        "activation_pending": False,
        "attention_required": False,
        "blockers": [],
        "notification_policy": "none",
        "history_count": len(history),
        "receipt": None,
    }


def failed_closed_status(reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "transaction_id": None,
        "authority_state": "ATTENTION_REQUIRED",
        "status": "Attention required",
        "last_maintenance": None,
        "activation_pending": False,
        "attention_required": True,
        "blockers": [reason],
        "notification_policy": "one-meaningful-attention",
        "history_count": 0,
        "receipt": None,
    }


def _runtime_source_revision() -> str | None:
    root = Path(os.environ.get("MAHO_ROOT", ""))
    path = root / "share/maho/runtime-source-revision"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def _attach_normal_authority(status: dict[str, Any]) -> dict[str, Any]:
    revision = _runtime_source_revision()
    status["normal_execution_certified"] = False
    status["normal_authority_id"] = None
    status["normal_certified_effects"] = []
    status["normal_certified_activation_requirements"] = []
    if revision is None or not DEFAULT_AUTHORITY_PATH.exists():
        return status
    try:
        authority = load_normal_execution_authority(source_revision=revision)
    except ValueError:
        status["normal_authority_state"] = "stale-or-invalid"
        return status
    status["normal_execution_certified"] = True
    status["normal_authority_state"] = "current"
    status["normal_authority_id"] = authority["authority_id"]
    status["normal_certified_effects"] = authority.get("certified_effects", [])
    status["normal_certified_activation_requirements"] = authority.get("certified_activation_requirements", [])
    return status


def status_payload(root: Path) -> dict[str, Any]:
    try:
        transaction = current_transaction(root)
        history = load_history(root)
        if transaction is None:
            return _attach_normal_authority(unavailable_status(root))
        status = product_status(transaction, history=history)
        status["history_count"] = len(history)
        return _attach_normal_authority(status)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return _attach_normal_authority(failed_closed_status("authoritative_update_state_unreadable"))


def main() -> None:
    parser = argparse.ArgumentParser(prog="maho-update")
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--json", action="store_true")
    history = subparsers.add_parser("history")
    history.add_argument("--json", action="store_true")
    history.add_argument("--limit", type=int, default=50)
    receipt = subparsers.add_parser("receipt")
    receipt.add_argument("transaction_id", nargs="?", default="current")
    receipt.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = state_root()

    if args.command == "status":
        payload = status_payload(root)
        if args.json:
            print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        else:
            print(payload["status"])
            if payload["last_maintenance"]:
                print(f"Last maintenance: {payload['last_maintenance']}")
            if payload["activation_pending"]:
                print("Activation: next explicit restart")
            if payload["blockers"]:
                print("Blockers: " + ", ".join(payload["blockers"]))
            if payload.get("normal_execution_certified"):
                scope = ", ".join(payload.get("normal_certified_effects", [])) or "none"
                print(f"Normal update execution: certified ({scope})")
            else:
                print("Normal update execution: uncertified")
        return
    if args.command == "history":
        payload = load_history(root, limit=args.limit)
        if args.json:
            print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        else:
            for item in payload:
                print(f"{item['updated_at']}  {item['state']}  {item['transaction_id']}")
        return
    if args.transaction_id == "current":
        transaction = current_transaction(root)
        if transaction is None:
            raise SystemExit("maho-update: no current transaction")
        payload = build_receipt(transaction)
    else:
        if _TXID.fullmatch(args.transaction_id) is None:
            raise SystemExit("maho-update: invalid transaction identity")
        path = root / "receipts" / f"{args.transaction_id}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"maho-update: receipt unavailable: {exc}") from exc
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")) if args.json else format_receipt(payload))


if __name__ == "__main__":
    main()
