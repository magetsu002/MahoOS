#!/usr/bin/env python3
"""Command-line boundary for read-only retention status and authorized GC."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from maho_generation_gc import (
    GCExecutor, InventoryError, RetentionPlan, inventory_from_generation_store,
    inventory_status, plan_retention, read_inventory,
)


DEFAULT_GENERATION_ROOT = Path("/var/lib/maho/generations")
DEFAULT_INVENTORY = Path("/var/lib/maho/gc/inventory.json")
DEFAULT_STATE_ROOT = Path("/var/lib/maho/gc")
DEFAULT_SAFE_RESERVE = 2 * 1024 * 1024 * 1024


def _load(args: argparse.Namespace):
    if args.inventory.is_file():
        return read_inventory(args.inventory), "durable-inventory"
    return inventory_from_generation_store(args.generation_root), "generation-store-adapter"


def _emit(value) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maho-generation-gc")
    parser.add_argument("--generation-root", type=Path, default=DEFAULT_GENERATION_ROOT)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--safe-reserve-bytes", type=int, default=DEFAULT_SAFE_RESERVE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--output", type=Path, required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--plan", type=Path, required=True)
    apply_parser.add_argument("--confirm", required=True)
    subparsers.add_parser("resume")
    args = parser.parse_args(argv)

    try:
        if args.command in {"status", "plan"}:
            inventory, authority = _load(args)
            free = shutil.disk_usage(args.generation_root).free
            if args.command == "status":
                value = inventory_status(
                    inventory, free_bytes=free,
                    safe_reserve_bytes=args.safe_reserve_bytes,
                )
                value["authority"] = authority
                value["mutation_supported"] = authority == "durable-inventory"
                value["update_mutation_allowed"] = (
                    value["update_mutation_allowed"]
                    and (authority == "durable-inventory" or not value["gc_eligible_object_ids"])
                )
                _emit(value)
                return 0
            plan = plan_retention(
                inventory, free_bytes=free,
                safe_reserve_bytes=args.safe_reserve_bytes,
            )
            args.output.write_text(json.dumps(plan.as_dict(), sort_keys=True) + "\n", encoding="utf-8")
            os.chmod(args.output, 0o600)
            _emit({
                "plan_path": str(args.output), "plan_sha256": plan.plan_sha256,
                "confirmation": f"GC:{plan.plan_sha256}",
                "removal_object_ids": list(plan.removal_object_ids),
                "reserve_restored": plan.reserve_restored,
            })
            return 0

        if os.geteuid() != 0:
            raise PermissionError("GC mutation requires the bounded privileged boundary")
        executor = GCExecutor(
            inventory_path=args.inventory,
            data_root=args.generation_root,
            state_root=args.state_root,
        )
        if args.command == "resume":
            _emit(executor.resume())
            return 0
        value = json.loads(args.plan.read_text(encoding="utf-8"))
        plan = RetentionPlan.parse(value)
        if args.confirm != f"GC:{plan.plan_sha256}":
            raise PermissionError("exact GC plan confirmation is required")
        _emit(executor.execute(plan))
        return 0
    except (InventoryError, OSError, PermissionError, RuntimeError, ValueError) as exc:
        _emit({
            "schema_version": 1, "kind": "maho-generation-gc-error",
            "error": type(exc).__name__, "message": str(exc),
        })
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
