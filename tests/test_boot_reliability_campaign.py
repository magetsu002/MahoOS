#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/boot-reliability-campaign.py"
SPEC = importlib.util.spec_from_file_location("maho_boot_reliability_campaign", MODULE_PATH)
assert SPEC and SPEC.loader
campaign = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(campaign)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def main() -> None:
    check(
        "graphical target timestamp parser uses monotonic evidence",
        campaign._first_time("[    8.250] host systemd[1]: Reached target Graphical Interface.\n", "Reached target Graphical Interface") == 8.25,
    )
    with tempfile.TemporaryDirectory() as td:
        evidence = Path(td) / "boots.jsonl"
        ids = [f"{number:032x}" for number in range(1, 11)]
        records = [
            {
                "boot_id": boot_id,
                "structural_result": "PASS",
                "visible_confirmation": "yes",
                "display_manager_restarts": 0,
            }
            for boot_id in ids
        ]
        evidence.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
        campaign._boot_ids = lambda: ids
        with contextlib.redirect_stdout(io.StringIO()):
            status = campaign.report(evidence, 10)
        check("ten consecutive structural and human-visible boots pass", status == 0)

        records[-1]["visible_confirmation"] = "not-checked"
        evidence.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            status = campaign.report(evidence, 10)
        check("automation cannot substitute service state for visible confirmation", status == 1)

        records[-1]["visible_confirmation"] = "yes"
        campaign._boot_ids = lambda: ids[:-1] + ["f" * 32]
        evidence.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            status = campaign.report(evidence, 10)
        check("missing a journal-consecutive boot keeps campaign incomplete", status == 1)
    print("ALL BOOT RELIABILITY CAMPAIGN TESTS PASS")


if __name__ == "__main__":
    main()
