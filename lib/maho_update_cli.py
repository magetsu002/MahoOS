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
_SHA40 = re.compile(r"[0-9a-f]{40}")
DEFAULT_CAMPAIGN_ROOT = Path("/usr/lib/maho/update-campaign/current")


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


def _campaign_source_revision(campaign_root: Path | None = None) -> str | None:
    root = (
        Path(os.environ.get("MAHO_UPDATE_CAMPAIGN_ROOT", str(DEFAULT_CAMPAIGN_ROOT)))
        if campaign_root is None else Path(campaign_root)
    )
    path = root / "SOURCE_REVISION"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if _SHA40.fullmatch(value) else None


def _attach_normal_authority(
    status: dict[str, Any], *, campaign_root: Path | None = None,
    authority_path: Path = DEFAULT_AUTHORITY_PATH,
) -> dict[str, Any]:
    revision = _campaign_source_revision(campaign_root)
    status["normal_execution_certified"] = False
    status["normal_authority_state"] = "absent"
    status["normal_authority_id"] = None
    status["normal_certified_profile"] = None
    status["normal_certified_effects"] = []
    status["normal_certified_activation_requirements"] = []
    if not authority_path.exists():
        return status
    if revision is None:
        status["normal_authority_state"] = "campaign-unavailable"
        return status
    try:
        authority = load_normal_execution_authority(source_revision=revision, path=authority_path)
    except ValueError:
        status["normal_authority_state"] = "stale-or-invalid"
        return status
    status["normal_execution_certified"] = True
    status["normal_authority_state"] = "current"
    status["normal_authority_id"] = authority["authority_id"]
    status["normal_certified_profile"] = authority.get("certified_profile")
    status["normal_certified_effects"] = authority.get("certified_effects", [])
    status["normal_certified_activation_requirements"] = authority.get("certified_activation_requirements", [])
    return status


def _coordinator_status(root: Path) -> dict[str, Any] | None:
    path = root / "coordinator.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        return None
    return value


def _attach_coordinator(status: dict[str, Any], root: Path) -> dict[str, Any]:
    coordinator = _coordinator_status(root)
    status["coordinator"] = coordinator
    status["coordinator_phase"] = coordinator.get("phase") if coordinator else None
    status["update_debt_seconds"] = coordinator.get("update_debt_seconds", 0) if coordinator else 0
    return status


def _presentation_status(status: dict[str, Any]) -> str:
    blockers = status.get("blockers") if isinstance(status.get("blockers"), list) else []
    coordinator = status.get("coordinator") if isinstance(status.get("coordinator"), dict) else {}
    coordinator_blockers = coordinator.get("blockers") if isinstance(coordinator.get("blockers"), list) else []
    coordinator_phase = str(coordinator.get("phase") or "")
    if blockers or status.get("attention_required") is True:
        if coordinator_blockers:
            return "Blocked: " + str(coordinator_blockers[0])
        return "Review required"
    receipt = status.get("receipt") if isinstance(status.get("receipt"), dict) else {}
    state = str(receipt.get("state") or status.get("authority_state") or "").upper()
    if state in {"BLOCKED", "FAILED_RECOVERABLE", "ATTENTION_REQUIRED"}:
        return "Review required"
    if state == "RECOVERING":
        return "Recovering"
    if state == "RECOVERED":
        return "Recovered"
    if state == "ACTIVE_VERIFYING":
        return "Verifying"
    if state == "INSTALLING":
        return "Installing"
    if state == "INSTALLED_PENDING_ACTIVATION":
        if coordinator_phase == "VERIFYING_AFTER_RESTART":
            return "Verifying after restart"
        return "Ready to restart"
    if coordinator_phase == "UP_TO_DATE":
        return "Up to date"
    if coordinator_phase in {"CHECKING", "COALESCED"}:
        return "Checking"
    if coordinator_phase in {"PREPARING", "WAITING_PREPARATION"}:
        return "Preparing" if not coordinator_blockers else "Blocked: " + str(coordinator_blockers[0])
    if coordinator_phase == "WAITING_MAINTENANCE":
        return "Waiting for maintenance opportunity"
    if coordinator_phase == "MAINTENANCE_READY":
        return "Ready when safe"
    if coordinator_phase == "READY_TO_RESTART":
        return "Ready to restart"
    if coordinator_phase == "VERIFYING_AFTER_RESTART":
        return "Verifying after restart"
    if coordinator_phase in {"BLOCKED", "INVALIDATED", "RETRY_DEFERRED"}:
        return "Blocked: " + str(coordinator_blockers[0] if coordinator_blockers else "automatic maintenance unavailable")
    if state == "HEALTHY":
        return "Healthy"
    if state in {"DISCOVERED", "STAGED"}:
        return "Preparing"
    if state in {"PREPARED", "MAINTENANCE_READY"}:
        effects = status.get("normal_certified_effects")
        if isinstance(effects, list) and any(str(item).startswith("boot") for item in effects):
            return "Deferred to boot-safe path"
        return "Ready" if status.get("normal_execution_certified") is True else "Waiting for certification"
    return str(status.get("status") or "Unknown")


def status_payload(
    root: Path, *, maho_root: Path | None = None,
    authority_path: Path = DEFAULT_AUTHORITY_PATH,
    campaign_root: Path | None = None,
) -> dict[str, Any]:
    try:
        transaction = current_transaction(root)
        history = load_history(root)
        if transaction is None:
            status = _attach_normal_authority(
                unavailable_status(root), campaign_root=campaign_root,
                authority_path=authority_path,
            )
            status = _attach_coordinator(status, root)
            status["presentation_status"] = _presentation_status(status)
            return status
        status = product_status(transaction, history=history)
        status["history_count"] = len(history)
        status = _attach_normal_authority(
            status, campaign_root=campaign_root, authority_path=authority_path,
        )
        status = _attach_coordinator(status, root)
        status["presentation_status"] = _presentation_status(status)
        return status
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        status = _attach_normal_authority(
            failed_closed_status("authoritative_update_state_unreadable"), campaign_root=campaign_root,
            authority_path=authority_path,
        )
        status = _attach_coordinator(status, root)
        status["presentation_status"] = _presentation_status(status)
        return status


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
            print(payload.get("presentation_status") or payload["status"])
            if payload["last_maintenance"]:
                print(f"Last maintenance: {payload['last_maintenance']}")
            if payload["activation_pending"]:
                print("Activation: next explicit restart")
            if payload["blockers"]:
                print("Blockers: " + ", ".join(payload["blockers"]))
            if payload.get("normal_execution_certified"):
                scope = ", ".join(payload.get("normal_certified_effects", [])) or "none"
                profile = payload.get("normal_certified_profile") or "unknown-profile"
                print(f"Normal update execution: certified ({profile}; {scope})")
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
