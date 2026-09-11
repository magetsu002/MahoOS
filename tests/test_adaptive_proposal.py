#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_adaptive_proposal import Effect, ExpiryCondition, create_proposal, proposal_from_dict

NOW = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)
SNAP = "sit-0123456789abcdef0123"


def expect_error(fn, text: str) -> None:
    try:
        fn()
    except ValueError as exc:
        assert text in str(exc), (text, str(exc))
    else:
        raise AssertionError(f"expected ValueError containing {text!r}")


def main() -> None:
    proposal = create_proposal(
        source_policy="battery.low",
        policy_version="1.0",
        situation_snapshot_id=SNAP,
        priority_domain="battery-survival",
        disruption_class="A",
        confidence=0.94,
        reason="Sustained discharge at low battery should reduce optional work",
        supporting_evidence=["battery=19", "ac=false", "discharge=stable"],
        requested_effects=[Effect("maintenance", "suspended"), Effect("background_work", "reduced")],
        prohibited_effects=[Effect("power_action", "suspend-review")],
        minimum_dwell_seconds=30,
        expiry_condition=ExpiryCondition("condition-clears", "battery-low"),
        cooldown_seconds=60,
        minimum_residency_seconds=120,
        created_at=NOW,
    )
    assert proposal.priority == 400
    assert proposal.shadow_eligible is True
    assert proposal.automatic_execution_eligible is False
    assert proposal.requested_effects[0].key == "background_work"
    assert proposal_from_dict(proposal.as_dict()) == proposal
    assert create_proposal(
        source_policy="battery.low", policy_version="1.0", situation_snapshot_id=SNAP,
        priority_domain="battery-survival", disruption_class="A", confidence=0.94,
        reason="Sustained discharge at low battery should reduce optional work",
        supporting_evidence=["battery=19", "ac=false", "discharge=stable"],
        requested_effects=[Effect("maintenance", "suspended"), Effect("background_work", "reduced")],
        prohibited_effects=[Effect("power_action", "suspend-review")], minimum_dwell_seconds=30,
        expiry_condition=ExpiryCondition("condition-clears", "battery-low"), cooldown_seconds=60,
        minimum_residency_seconds=120, created_at=NOW,
    ).proposal_id == proposal.proposal_id

    c = create_proposal(
        source_policy="display.conserve", policy_version="1", situation_snapshot_id=SNAP,
        priority_domain="battery-survival", disruption_class="C", confidence=0.9,
        reason="Visible brightness change requires review", supporting_evidence=["battery=5"],
        requested_effects=[Effect("display_brightness", "lower")], created_at=NOW,
    )
    d = create_proposal(
        source_policy="critical.power", policy_version="1", situation_snapshot_id=SNAP,
        priority_domain="hardware-data-safety", disruption_class="D", confidence=1.0,
        reason="Destructive power behavior remains review-only", supporting_evidence=["critical"],
        requested_effects=[Effect("power_action", "shutdown-review")], created_at=NOW,
    )
    assert c.requires_human_review and d.requires_human_review
    assert not c.shadow_eligible and not d.shadow_eligible

    raw = proposal.as_dict()
    raw["command"] = "killall foo"
    expect_error(lambda: proposal_from_dict(raw), "unknown proposal fields")

    expect_error(lambda: create_proposal(
        source_policy="bad", policy_version="1", situation_snapshot_id=SNAP,
        priority_domain="background-efficiency", disruption_class="A", confidence=0.5,
        reason="bad", supporting_evidence=[], requested_effects=[Effect("command", "killall foo")], created_at=NOW,
    ), "unknown adaptation effect")

    bad_value = proposal.as_dict()
    bad_value["requested_effects"] = [{"key": "maintenance", "value": "rm-rf"}]
    expect_error(lambda: proposal_from_dict(bad_value), "invalid value")

    bad_schema = proposal.as_dict(); bad_schema["schema_version"] = 99
    expect_error(lambda: proposal_from_dict(bad_schema), "unsupported")

    print("ALL ADAPTIVE PROPOSAL TESTS PASS")


if __name__ == "__main__":
    main()
