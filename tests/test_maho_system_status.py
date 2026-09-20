#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_behavior_preferences import defaults  # noqa: E402
from maho_system_status import build_system_model  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def guardian_fixture(*, reliability: str = "healthy", trust: str = "UNKNOWN", self_health: str = "HEALTHY", incident_level: int = 0):
    incidents = [] if incident_level == 0 else [{"incident_id": "inc-test", "status": "active"}]
    return {
        "system": {"maho_runtime": {"verified": True, "source_revision": "a" * 40}},
        "reliability": {"state": reliability, "counts": {"healthy": 3, "degraded": 0, "unknown": 0}},
        "world_state": {"guardian": {
            "self_health": {"state": self_health, "missing_providers": [], "stale_providers": []},
            "severity": {"level": incident_level, "label": "minor" if incident_level else "none"},
            "trust": {"state": trust, "reasons": ["fixture trust reason"]},
        }},
        "active_incidents": incidents,
        "boot": {"signed_boot_authority": "UNKNOWN", "trust_reason": "proof missing"},
        "evidence_freshness": {"boot.authority": {"freshness": "missing", "health": "healthy"}},
        "recent_activity": [],
        "runtime_recovery": {"state": "none"},
    }


def build(**overrides):
    values = {
        "guardian": guardian_fixture(),
        "update": {"status": "Healthy", "attention_required": False, "blockers": [], "normal_execution_certified": True, "normal_authority_state": "current"},
        "behavior": {"captured_at": "2026-01-01T00:00:00Z", "snapshot_id": "sit-test", "active_executable_posture": {}, "blocked": None},
        "adaptive_doctor": {"healthy": True, "lease_state": "ok", "maintenance_projection_state": "absent"},
        "recovery": {"recovery_modes": ["RUNTIME"], "last_verified_runtime_recovery": {"valid": True, "campaign_id": "runtime-test", "reason": "verified"}, "invalid_unified_history_records": 0},
        "preferences": defaults(),
    }
    values.update(overrides)
    return build_system_model(**values)


def main() -> None:
    model = build()
    check("operational health and trust remain independent", model.summary.operational_health == "HEALTHY" and model.summary.trust == "UNRESOLVED")
    check("Guardian health remains distinct", model.summary.guardian_health == "HEALTHY")
    check("recovery history does not promote current trust", model.summary.recovery == "AVAILABLE" and model.summary.trust == "UNRESOLVED")
    check("missing boot trust receives review attention", model.summary.attention == "REVIEW")
    check("doctor records use the bounded schema", all(set(item.__dict__) == {"id", "subsystem", "state", "summary", "reason", "evidence_refs", "recommended_action", "attention"} for item in model.diagnostics))
    check("doctor record identities are unique", len({item.id for item in model.diagnostics}) == len(model.diagnostics))
    check("system model is stable JSON", json.loads(json.dumps(model.as_dict()))["schema_version"] == 1)

    degraded = build(guardian=guardian_fixture(reliability="degraded", trust="VERIFIED", incident_level=2))
    check("degraded operation can retain verified trust", degraded.summary.operational_health == "DEGRADED" and degraded.summary.trust == "VERIFIED")
    check("serious incidents request action", degraded.summary.attention == "ACTION REQUIRED" and degraded.summary.severity.startswith("L2"))

    blocked = build(update={
        "status": "Attention required", "attention_required": True,
        "blockers": ["admission_denied"], "normal_execution_certified": False,
        "normal_authority_state": "stale-or-invalid",
    })
    update_record = next(item for item in blocked.diagnostics if item.id == "updates.transaction")
    check("update blockers are not flattened into generic failure", update_record.state == "BLOCKED" and update_record.reason == "admission_denied")

    unknown_guardian = build(guardian=guardian_fixture(self_health="UNKNOWN"))
    record = next(item for item in unknown_guardian.diagnostics if item.id == "guardian.self-health")
    check("missing Guardian certainty remains UNKNOWN", record.state == "UNKNOWN")
    print("ALL MAHO SYSTEM STATUS TESTS PASS")


if __name__ == "__main__":
    main()
