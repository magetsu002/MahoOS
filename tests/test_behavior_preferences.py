#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_adaptive_proposal import Effect, ExpiryCondition, create_proposal  # noqa: E402
from maho_behavior_preferences import (  # noqa: E402
    BehaviorPreferences, apply_preferences, defaults, load_preferences,
    parse_preferences, write_preference,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
SNAPSHOT = "sit-" + "1" * 20


def proposal(source: str, priority: str, effects: list[Effect]):
    return create_proposal(
        source_policy=source, policy_version="1.0", situation_snapshot_id=SNAPSHOT,
        priority_domain=priority, disruption_class="A", confidence=.99,
        reason="test proposal", supporting_evidence=["fixture"], requested_effects=effects,
        expiry_condition=ExpiryCondition("condition-clears", "fixture"), created_at=NOW,
    )


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def main() -> None:
    check("safe defaults enable implemented convenience behavior", all(defaults().values.values()))
    parsed = parse_preferences({
        "schema_version": 1,
        "preferences": {"focus.quiet_notifications": False, "future.preference": {"x": 1}},
        "future_top_level": True,
    })
    check("unknown fields are tolerated and reported", parsed.unknown_keys == ("future.preference",))
    check("known preference is parsed", parsed.enabled("focus.quiet_notifications") is False)
    invalid = parse_preferences({
        "schema_version": 1,
        "preferences": {"focus.quiet_notifications": "no"},
    })
    check("invalid known values fall back safely", invalid.enabled("focus.quiet_notifications") is True and invalid.issues)

    convenience = proposal(
        "gaming.foreground", "foreground-task-continuity",
        [Effect("maintenance", "suspended"), Effect("notifications", "quiet"), Effect("background_work", "reduced")],
    )
    safety = proposal("guardian.reliability-state", "hardware-data-safety", [Effect("maintenance", "suspended")])
    preferences = BehaviorPreferences({
        **defaults().values,
        "focus.quiet_notifications": False,
        "focus.pause_maintenance_gaming": False,
    })
    filtered = apply_preferences((convenience, safety), preferences)
    game = next(item for item in filtered if item.source_policy == "gaming.foreground")
    guardian = next(item for item in filtered if item.source_policy == "guardian.reliability-state")
    check("disabled convenience effects cannot reach execution", game.requested_effects == (Effect("background_work", "reduced"),))
    check("safety and recovery coordination bypass convenience toggles", guardian.requested_effects == (Effect("maintenance", "suspended"),))
    check("restricted proposal gets a new bound identity", game.proposal_id != convenience.proposal_id)

    with tempfile.TemporaryDirectory(prefix="maho-behavior-") as temporary:
        path = Path(temporary) / "maho" / "behavior.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "schema_version": 1,
            "preferences": {"future.preference": False},
            "future_top_level": {"keep": True},
        }))
        saved = write_preference("focus.quiet_notifications", False, path)
        on_disk = json.loads(path.read_text())
        check("preference write is user-private", path.stat().st_mode & 0o777 == 0o600)
        check("preference write preserves unknown fields", on_disk["future_top_level"] == {"keep": True} and on_disk["preferences"]["future.preference"] is False)
        check("written preference round-trips", saved.enabled("focus.quiet_notifications") is False and load_preferences(path).enabled("focus.quiet_notifications") is False)

    print("ALL BEHAVIOR PREFERENCE TESTS PASS")


if __name__ == "__main__":
    main()
