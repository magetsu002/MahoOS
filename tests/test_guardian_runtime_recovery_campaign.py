#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

import guardian_runtime_recovery_campaign as campaign  # noqa: E402
from test_guardian_live_recovery import RotatingRecoveryDriver  # noqa: E402
from test_guardian_runtime_recovery import make_release, make_tree_writable  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def rejected(name: str, function) -> None:
    try:
        function()
    except (RuntimeError, ValueError):
        print("PASS", name)
        return
    raise AssertionError(name)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-runtime-campaign-") as raw:
        base = Path(raw)
        try:
            runtime = base / "runtime"
            releases = runtime / "releases"
            releases.mkdir(parents=True)
            current = make_release(releases, "1" * 40)
            previous = make_release(releases, "2" * 40)
            (runtime / "current").symlink_to(current)
            (runtime / "previous").symlink_to(previous)
            state = base / "state"
            campaigns = base / "campaigns"
            db, proc, fs = base / "db", base / "proc", base / "fs"
            for item in (db, proc, fs):
                item.mkdir()

            prepared = campaign.prepare_campaign(runtime, campaigns)
            campaign_id = prepared["campaign_id"]
            check("physical campaign prepares without runtime mutation", prepared["phase"] == "PREPARED" and (runtime / "current").resolve() == current)
            rejected(
                "runtime corruption requires the exact campaign token",
                lambda: campaign.corrupt_campaign(campaigns, campaign_id, confirm="no", state_root=state, db_root=db, proc_root=proc, fs_root=fs),
            )
            staged = campaign.corrupt_campaign(
                campaigns, campaign_id, confirm=prepared["corruption_confirmation"],
                state_root=state, db_root=db, proc_root=proc, fs_root=fs,
            )
            check("controlled corruption becomes exact Guardian runtime incident", staged["phase"] == "AWAITING_RECOVERY_AUTHORIZATION" and staged["incident_id"].startswith("inc-"))
            check("campaign keeps recovery authorization separate", staged["recovery_confirmation"].startswith("AUTHORIZE-RUNTIME-RECOVERY:recovery-"))
            rejected(
                "runtime recovery requires its separate exact authorization",
                lambda: campaign.recover_campaign(campaigns, campaign_id, confirm="no", state_root=state, db_root=db, proc_root=proc, fs_root=fs),
            )
            driver = RotatingRecoveryDriver({
                "root": runtime, "releases": releases,
                "current": current, "previous": previous,
                "current_link": runtime / "current", "previous_link": runtime / "previous",
            })
            completed = campaign.recover_campaign(
                campaigns, campaign_id, confirm=staged["recovery_confirmation"],
                state_root=state, db_root=db, proc_root=proc, fs_root=fs, driver=driver,
            )
            receipt = completed["receipt"]
            check("physical campaign verifies existing recovery path", completed["phase"] == "VERIFIED" and receipt["verified"] is True)
            check("verified previous becomes current", (runtime / "current").resolve() == previous)
            check("corrupted generation remains preserved as evidence", (runtime / "previous").resolve() == current and receipt["corrupted_generation_retained"] is True)
            check("runtime integrity incident resolves only after verified recovery", receipt["incident_resolved"] is True)
            record = campaign._read_object(campaigns / f"{campaign_id}.json")
            check("durable physical receipt retains exact authority", record["receipt"]["authority_id"].startswith("recovery-auth-"))
        finally:
            make_tree_writable(base)
    print("ALL GUARDIAN RUNTIME RECOVERY CAMPAIGN TESTS PASS")


if __name__ == "__main__":
    main()
