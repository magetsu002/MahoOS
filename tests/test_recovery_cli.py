#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_recovery_cli import render_human  # noqa: E402
from maho_recovery_generation import RecoveryGenerationReport, report_json  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def main() -> None:
    report = RecoveryGenerationReport(
        schema_version=1,
        current_platform={
            "root_fstype": "btrfs",
            "root_fsroot": "/@",
            "home_scope": "excluded",
            "snapper_config_available": True,
            "primary_kernel_present": False,
            "lts_kernel_present": False,
            "limine_present": False,
            "limine_snapper_sync_present": False,
        },
        generations=(),
        selected_generation_id=None,
        certified_system_restore_plannable=False,
        planning_facts={"recovery": {"automatic_allowed": False, "native_restore_enabled": False}},
        native_restore_enabled=False,
    )
    human = render_human(report)
    check("human CLI exposes root and home recovery scope", "btrfs /@" in human and "home rollback scope       excluded" in human)
    check("human CLI never implies live restore", "native restore           disabled" in human)
    parsed = json.loads(report_json(report))
    check("JSON CLI is machine-readable", parsed["schema_version"] == 1 and parsed["native_restore_enabled"] is False)
    print("ALL G3 RECOVERY CLI CONTRACTS PASS")


if __name__ == "__main__":
    main()
