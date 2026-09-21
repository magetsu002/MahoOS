#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_prevention import prevention_status  # noqa: E402

NOW = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def event(*, effect: int = 8, inode: int = 40) -> dict:
    return {
        "schema_version": 1, "kind": "guardian-prevention-event",
        "observed_at": "2026-09-21T17:59:59.000000000Z", "boot_id": "boot-fixture",
        "subject": {"pid": 42, "uid": 0, "start_time_ticks": 100, "executable_device": 8, "executable_inode": 20},
        "target": {"device": 8, "inode": inode, "scope_device": 8, "scope_inode": 30},
        "effect_mask": effect, "operation_mask": 4,
        "policy_reason": "exact_mutation_authority_missing_or_invalid",
        "authority_state": "not-current", "result": "prevented",
        "host_mutation_performed": False, "compromise_evidence": False,
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="guardian-prevention-") as temporary:
        root = Path(temporary)
        initial = prevention_status(root, now=NOW)
        check("no evidence is not an incident", initial["prevented_count"] == 0 and initial["correlation"]["suspicious"] is False)
        (root / "events.jsonl").write_text(json.dumps(event()) + "\n", encoding="utf-8")
        single = prevention_status(root, now=NOW)
        check("single prevention is durable bounded evidence", single["state"] == "recording" and single["prevented_count"] == 1)
        check("prevented mutation performed no host mutation", single["recent"][0]["host_mutation_performed"] is False)
        check("prevention is not compromise evidence", single["recent"][0]["compromise_evidence"] is False and single["trust_effect"] == "none")
        rows = [event(effect=8, inode=40), event(effect=16, inode=41), event(effect=8, inode=42)]
        (root / "events.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        correlated = prevention_status(root, now=NOW)
        check("repeated cross-boundary attempts become correlation input", correlated["correlation"]["suspicious"] is True and correlated["incident_effect"] == "correlation-input-only")
        malformed = event() | {"host_mutation_performed": True}
        (root / "events.jsonl").write_text(json.dumps(malformed) + "\n", encoding="utf-8")
        invalid = prevention_status(root, now=NOW)
        check("claims of performed mutation cannot masquerade as prevention", invalid["prevented_count"] == 0 and invalid["invalid_records"] == 1)
    print("ALL GUARDIAN PREVENTION TESTS PASS")


if __name__ == "__main__":
    main()
