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
        "schema_version": 2,
        "preferences": {"focus.quiet_notifications": False, "future.preference": {"x": 1}},
        "future_top_level": True,
    })
    check("unknown fields are tolerated and reported", parsed.unknown_keys == ("future.preference",))
    check("known preference is parsed", parsed.enabled("focus.quiet_notifications") is False)
    legacy = parse_preferences({
        "schema_version": 1,
        "preferences": {"focus.pause_maintenance_heavy_work": False},
    })
    check(
        "v1 heavy-work choice migrates to granular v2 intentions",
        not legacy.enabled("focus.pause_maintenance_interactive")
        and not legacy.enabled("focus.pause_maintenance_builds")
        and not legacy.enabled("focus.pause_maintenance_rendering"),
    )
    invalid = parse_preferences({
        "schema_version": 1,
        "preferences": {"focus.quiet_notifications": "no"},
    })
    check("invalid known values fall back safely", invalid.enabled("focus.quiet_notifications") is True and invalid.issues)

    convenience = proposal(
        "gaming.foreground", "foreground-task-continuity",
        [Effect("maintenance", "suspended"), Effect("notifications", "quiet"), Effect("background_work", "reduced")],
    )
    build = proposal("compile.sustained", "foreground-task-continuity", [Effect("maintenance", "suspended")])
    render = proposal("render.sustained", "foreground-task-continuity", [Effect("maintenance", "suspended")])
    interactive = proposal("workload.interactive", "foreground-task-continuity", [Effect("maintenance", "suspended")])
    safety = proposal("guardian.reliability-state", "hardware-data-safety", [Effect("maintenance", "suspended")])
    preferences = BehaviorPreferences({
        **defaults().values,
        "focus.quiet_notifications": False,
        "focus.pause_maintenance_gaming": False,
        "focus.pause_maintenance_builds": False,
    })
    filtered = apply_preferences((convenience, build, render, interactive, safety), preferences)
    game = next(item for item in filtered if item.source_policy == "gaming.foreground")
    guardian = next(item for item in filtered if item.source_policy == "guardian.reliability-state")
    sources = {item.source_policy for item in filtered}
    check("build maintenance can be disabled independently", "compile.sustained" not in sources)
    check("render maintenance remains enabled independently", "render.sustained" in sources)
    check("interactive maintenance remains enabled independently", "workload.interactive" in sources)
    check("disabled convenience effects cannot reach execution", game.requested_effects == (Effect("background_work", "reduced"),))
    check("safety and recovery coordination bypass convenience toggles", guardian.requested_effects == (Effect("maintenance", "suspended"),))
    check("restricted proposal gets a new bound identity", game.proposal_id != convenience.proposal_id)

    with tempfile.TemporaryDirectory(prefix="maho-behavior-") as temporary:
        path = Path(temporary) / "maho" / "behavior.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "schema_version": 2,
            "preferences": {"future.preference": False},
            "future_top_level": {"keep": True},
        }))
        saved = write_preference("focus.quiet_notifications", False, path)
        on_disk = json.loads(path.read_text())
        check("preference write is user-private", path.stat().st_mode & 0o777 == 0o600)
        check("preference write preserves unknown fields", on_disk["future_top_level"] == {"keep": True} and on_disk["preferences"]["future.preference"] is False)
        check("written preference round-trips", saved.enabled("focus.quiet_notifications") is False and load_preferences(path).enabled("focus.quiet_notifications") is False)

    with tempfile.TemporaryDirectory(prefix="maho-behavior-v1-") as temporary:
        path = Path(temporary) / "behavior.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "preferences": {"focus.pause_maintenance_heavy_work": False},
        }))
        write_preference("focus.quiet_notifications", False, path)
        migrated = json.loads(path.read_text())
        loaded = load_preferences(path)
        check("preference writes migrate v1 files to v2", migrated["schema_version"] == 2)
        check(
            "v1 write migration preserves old heavy-work intent",
            not loaded.enabled("focus.pause_maintenance_interactive")
            and not loaded.enabled("focus.pause_maintenance_builds")
            and not loaded.enabled("focus.pause_maintenance_rendering"),
        )

    print("ALL BEHAVIOR PREFERENCE TESTS PASS")


if __name__ == "__main__":
    main()
