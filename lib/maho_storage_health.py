#!/usr/bin/env python3
"""Read-only storage-health evidence with explicit coverage and uncertainty."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
from typing import Any


def run(command: list[str]) -> tuple[str, str, int]:
    try:
        value = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "", str(exc), 127
    return value.stdout, value.stderr, value.returncode


def collect(root: str) -> dict[str, Any]:
    btrfs_out, btrfs_err, btrfs_rc = run(["btrfs", "device", "stats", "-c", root])
    scrub_out, scrub_err, scrub_rc = run([
        "systemctl", "show", "maho-btrfs-scrub-root.service",
        "--property=Result,ExecMainStatus,InactiveExitTimestamp",
    ])
    nvme_out, nvme_err, nvme_rc = run(["nvme", "list", "-o", "json"])
    try:
        nvme = json.loads(nvme_out) if nvme_rc == 0 else None
    except json.JSONDecodeError:
        nvme = None
    counters = [line.strip() for line in btrfs_out.splitlines() if line.strip()]
    scrub = dict(
        line.split("=", 1) for line in scrub_out.splitlines()
        if "=" in line
    ) if scrub_rc == 0 else {}
    coverage = {
        "btrfs_device_stats": "complete" if btrfs_rc == 0 else "unavailable",
        "scheduled_scrub_result": "complete" if scrub_rc == 0 else "unavailable",
        "nvme_inventory": "complete" if nvme is not None else "unavailable",
        "smart_interpretation": "diagnostic-only",
    }
    return {
        "schema_version": 1,
        "kind": "maho-storage-health-observation",
        "read_only": True,
        "root": root,
        "coverage": coverage,
        "btrfs": {"exit_status": btrfs_rc, "device_stats": counters, "error": btrfs_err.strip()[:500] or None},
        "scrub": {"exit_status": scrub_rc, "service": scrub, "error": scrub_err.strip()[:500] or None},
        "nvme": {"exit_status": nvme_rc, "inventory": nvme, "error": nvme_err.strip()[:500] or None},
        "assessment": "observed" if all(value != "unavailable" for value in coverage.values()) else "partial",
        "trust_note": "Raw device and SMART evidence is diagnostic; no vendor attribute is treated as a categorical failure.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="maho-storage-health")
    parser.add_argument("--root", default="/")
    args = parser.parse_args()
    print(json.dumps(collect(args.root), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
