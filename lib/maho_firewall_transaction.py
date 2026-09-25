#!/usr/bin/env python3
"""Fail-safe transaction owner for the MahoOS V1 host-input firewall table."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

TABLE_FAMILY = "inet"
TABLE_NAME = "maho_host"
CHAIN_NAME = "input"


def root_dir() -> Path:
    explicit = os.environ.get("MAHO_ROOT")
    return Path(explicit).expanduser().resolve() if explicit else Path(__file__).resolve().parent.parent


def receipt_path() -> Path:
    return Path("/run/maho/firewall/status.json")


def host_root_authority() -> bool:
    if os.geteuid() != 0:
        return False
    try:
        mappings = Path("/proc/self/uid_map").read_text(encoding="utf-8").splitlines()
        for line in mappings:
            inside, outside, length = (int(part) for part in line.split())
            if inside <= 0 < inside + length:
                return outside + (0 - inside) == 0
    except (OSError, ValueError):
        return True
    return False


def invalidate_receipt() -> None:
    if not host_root_authority():
        return
    try:
        receipt_path().unlink()
    except FileNotFoundError:
        pass


def nft(args: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["nft", *args], input=input_text, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def table_json() -> tuple[str, dict[str, Any] | None, str]:
    result = nft(["-j", "list", "table", TABLE_FAMILY, TABLE_NAME])
    if result.returncode == 0:
        try:
            return "present", json.loads(result.stdout), ""
        except json.JSONDecodeError:
            return "visibility-error", None, "nft returned invalid JSON"
    lower = result.stderr.lower()
    if "no such file" in lower or "does not exist" in lower:
        return "absent", None, result.stderr.strip()
    return "visibility-error", None, result.stderr.strip() or "nft inspection failed"


def table_text() -> tuple[str, str]:
    result = nft(["list", "table", TABLE_FAMILY, TABLE_NAME])
    if result.returncode == 0:
        return "present", result.stdout
    lower = result.stderr.lower()
    if "no such file" in lower or "does not exist" in lower:
        return "absent", ""
    raise RuntimeError(result.stderr.strip() or "unable to snapshot Maho firewall table")


def strip_handles(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_handles(v) for k, v in value.items() if k not in {"handle", "index"}}
    if isinstance(value, list):
        return [strip_handles(v) for v in value]
    return value


def verify_table(payload: dict[str, Any] | None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not isinstance(payload, dict):
        return False, ["table-json-unavailable"]
    rows = payload.get("nftables")
    if not isinstance(rows, list):
        return False, ["ruleset-list-unavailable"]
    chains: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        table = row.get("table")
        if isinstance(table, dict) and table.get("family") == TABLE_FAMILY and table.get("name") == TABLE_NAME:
            tables.append(table)
        chain = row.get("chain")
        if isinstance(chain, dict) and chain.get("family") == TABLE_FAMILY and chain.get("table") == TABLE_NAME:
            chains.append(chain)
    if len(tables) != 1:
        reasons.append("maho-table-count-not-one")
    input_chains = [row for row in chains if row.get("name") == CHAIN_NAME]
    if len(input_chains) != 1:
        reasons.append("input-chain-count-not-one")
    else:
        chain = input_chains[0]
        if chain.get("hook") != "input": reasons.append("input-hook-invalid")
        if int(chain.get("prio", -99999)) != 10: reasons.append("input-priority-invalid")
        if chain.get("policy") != "drop": reasons.append("input-policy-not-drop")
        if chain.get("type") != "filter": reasons.append("input-type-invalid")
    if any(row.get("hook") in {"output", "forward"} for row in chains):
        reasons.append("maho-table-owns-non-input-hook")
    return not reasons, reasons


def live_status_payload() -> dict[str, Any]:
    state, payload, detail = table_json()
    result: dict[str, Any] = {
        "schema_version": 1,
        "authority": "table inet maho_host only",
        "state": state,
        "table_present": state == "present",
        "decision_usable": state in {"present", "absent"},
    }
    if state == "present":
        verified, reasons = verify_table(payload)
        result.update({"verified": verified, "result": "protected" if verified else "partial", "reasons": reasons})
    elif state == "absent":
        result.update({"verified": True, "result": "unprotected", "reasons": []})
    else:
        result.update({"verified": False, "result": "insufficient-visibility", "reasons": [detail] if detail else []})
    return result


def validate_policy_scope(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    lowered = re.sub(r"#.*", "", text).lower()
    if re.search(r"\bflush\s+ruleset\b", lowered):
        raise ValueError("policy must never flush the whole ruleset")
    table_defs = re.findall(r"\btable\s+(\w+)\s+([\w.-]+)\s*\{", lowered)
    if table_defs != [(TABLE_FAMILY, TABLE_NAME)]:
        raise ValueError("policy must define exactly table inet maho_host")
    destructive = re.findall(r"\b(?:delete|destroy|flush)\s+table\s+(\w+)\s+([\w.-]+)", lowered)
    if any(item != (TABLE_FAMILY, TABLE_NAME) for item in destructive):
        raise ValueError("policy may mutate only table inet maho_host")
    check = nft(["-c", "-f", str(path)])
    if check.returncode != 0:
        raise ValueError(check.stderr.strip() or "nft syntax validation failed")
    return text


def rollback(previous_state: str, previous_text: str, previous_json: dict[str, Any] | None) -> tuple[bool, str]:
    batch = f"destroy table {TABLE_FAMILY} {TABLE_NAME}\n"
    if previous_state == "present":
        batch += previous_text
    result = nft(["-f", "-"], input_text=batch)
    if result.returncode != 0:
        return False, result.stderr.strip() or "rollback nft transaction failed"
    state, current_json, detail = table_json()
    if state != previous_state:
        return False, f"rollback state mismatch: expected {previous_state}, got {state}: {detail}"
    if previous_state == "present" and strip_handles(current_json) != strip_handles(previous_json):
        return False, "rollback content mismatch"
    return True, "restored"


def apply_policy(path: Path) -> dict[str, Any]:
    validate_policy_scope(path)
    previous_state, previous_text = table_text()
    invalidate_receipt()
    _, previous_json, _ = table_json()
    result = nft(["-f", str(path)])
    if result.returncode != 0:
        return {"schema_version": 1, "operation": "apply", "success": False, "changed": False, "rollback": "not-needed", "error": result.stderr.strip() or "atomic nft apply failed"}
    state, payload, detail = table_json()
    verified, reasons = verify_table(payload if state == "present" else None)
    if state != "present" or not verified:
        restored, rollback_detail = rollback(previous_state, previous_text, previous_json)
        return {
            "schema_version": 1, "operation": "apply", "success": False, "changed": False,
            "rollback": "verified" if restored else "failed", "rollback_detail": rollback_detail,
            "error": detail or ",".join(reasons) or "post-apply verification failed",
        }
    return {"schema_version": 1, "operation": "apply", "success": True, "changed": True, "rollback": "not-needed", "status": live_status_payload()}


def remove_policy() -> dict[str, Any]:
    before, _, detail = table_json()
    if before == "visibility-error":
        return {"schema_version": 1, "operation": "remove", "success": False, "changed": False, "error": detail}
    invalidate_receipt()
    result = nft(["-f", "-"], input_text=f"destroy table {TABLE_FAMILY} {TABLE_NAME}\n")
    if result.returncode != 0:
        return {"schema_version": 1, "operation": "remove", "success": False, "changed": False, "error": result.stderr.strip() or "atomic nft removal failed"}
    after, _, after_detail = table_json()
    if after != "absent":
        return {"schema_version": 1, "operation": "remove", "success": False, "changed": False, "error": after_detail or f"post-remove state is {after}"}
    return {"schema_version": 1, "operation": "remove", "success": True, "changed": before == "present", "status": live_status_payload()}


def main() -> int:
    parser = argparse.ArgumentParser(prog="maho-firewall", description="Manage only MahoOS table inet maho_host")
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.add_argument("--receipt", type=Path, default=receipt_path())
    status.add_argument("--max-age-seconds", type=int, default=45)
    live = sub.add_parser("live-status")
    live.add_argument("--json", action="store_true")
    remove = sub.add_parser("remove")
    remove.add_argument("--json", action="store_true")
    apply = sub.add_parser("apply")
    apply.add_argument("--policy", type=Path, default=root_dir() / "config/platform/maho-host-firewall.nft")
    apply.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "status" and args.max_age_seconds < 1:
        parser.error("--max-age-seconds must be positive")
    try:
        if args.command == "status":
            from maho_firewall_receipt import verify
            payload = verify(
                args.receipt.expanduser(),
                root=root_dir(),
                max_age_seconds=args.max_age_seconds,
            )
        elif args.command == "live-status":
            payload = live_status_payload()
        elif args.command == "apply":
            payload = apply_policy(args.policy.expanduser().resolve())
        else:
            payload = remove_policy()
    except (OSError, ValueError, RuntimeError) as exc:
        payload = {"schema_version": 1, "operation": args.command, "success": False, "changed": False, "error": str(exc)}
    emit(payload, bool(getattr(args, "json", False)))
    readable = args.command in {"status", "live-status"} and payload.get("decision_usable") is True
    return 0 if payload.get("success") is True or readable else 1


if __name__ == "__main__":
    raise SystemExit(main())
