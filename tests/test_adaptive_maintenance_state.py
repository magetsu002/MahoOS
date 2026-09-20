#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_adaptive_maintenance_state import (  # noqa: E402
    MaintenanceVetoError, adapter_main, maintenance_gate_for_user, read_state,
    state_for_lease,
)

T0 = datetime(2026, 9, 20, 12, 30, tzinfo=timezone.utc)
LEASE = "lease-" + "1" * 20
PROPOSAL = "prop-" + "2" * 20


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def state(now: datetime = T0, source: str = "gaming.foreground") -> dict:
    return state_for_lease(
        lease_id=LEASE, source_policy=source, source_proposal_id=PROPOSAL,
        captured_at="2026-09-20T12:29:00.000Z", now=now,
    )


def desired(value: dict) -> str:
    return json.dumps({
        "operation": "set-adaptive-maintenance-veto", "active": True, "state": value,
    }, sort_keys=True, separators=(",", ":"))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-adaptive-veto-") as temporary:
        path = Path(temporary) / "state/maintenance-veto.json"
        old = os.environ.get("MAHO_ADAPTIVE_MAINTENANCE_VETO_PATH")
        os.environ["MAHO_ADAPTIVE_MAINTENANCE_VETO_PATH"] = str(path)
        try:
            current = state()
            check("maintenance adapter applies exact closed-schema veto", adapter_main(("apply", desired(current))) == 0)
            check("maintenance veto is private user state", stat.S_IMODE(path.stat().st_mode) == 0o600)
            check("maintenance adapter verifies exact active state", adapter_main(("verify", desired(current))) == 0)
            gate = maintenance_gate_for_user("fixture", path=path, now=T0 + timedelta(seconds=30))
            check("M4 gate consumes active certified veto", gate["veto_active"] is True and gate["source_policy"] == "gaming.foreground")

            restarted = subprocess.run(
                [sys.executable, "-c", (
                    "from pathlib import Path; import sys; "
                    f"sys.path.insert(0,{str(ROOT / 'lib')!r}); "
                    "from maho_adaptive_maintenance_state import read_state; "
                    f"assert read_state(Path({str(path)!r}), require_fresh=False)['lease_id']=={LEASE!r}"
                )],
                text=True, capture_output=True, check=False,
            )
            check("durable veto is revalidated after producer exit and restart", restarted.returncode == 0)

            captured = subprocess.run(
                [sys.executable, str(ROOT / "lib/maho_adaptive_maintenance_state.py"), "capture"],
                text=True, capture_output=True, check=False, env=dict(os.environ),
            )
            before = json.loads(captured.stdout)
            check("maintenance adapter captures rollback state", captured.returncode == 0 and before["state"] == current)

            inactive = json.dumps({"operation": "set-adaptive-maintenance-veto", "active": False})
            check("lease expiry removes Adaptive authority", adapter_main(("apply", inactive)) == 0 and not path.exists())
            check("absence restores native M4 eligibility logic", maintenance_gate_for_user("fixture", path=path, now=T0)["adaptive_maintenance"] == "unchanged")
            check("restoration absence is verified", adapter_main(("verify", inactive)) == 0)
            check("rollback can restore captured veto after failed transaction", adapter_main(("rollback", json.dumps(before))) == 0 and path.exists())
            check("rollback restoration is exactly verified", adapter_main(("verify-rollback", json.dumps(before))) == 0)

            try:
                maintenance_gate_for_user("fixture", path=path, now=T0 + timedelta(minutes=3))
            except MaintenanceVetoError as exc:
                check("stale veto loses executable authority and fails closed", "stale" in str(exc))
            else:
                raise AssertionError("stale veto remained authoritative")

            path.write_text("{broken", encoding="utf-8")
            path.chmod(0o600)
            try:
                maintenance_gate_for_user("fixture", path=path, now=T0)
            except MaintenanceVetoError:
                check("malformed Adaptive state never makes M4 eligible", True)
            else:
                raise AssertionError("malformed veto was treated as eligibility")

            path.unlink()
            path.symlink_to(Path(temporary) / "elsewhere")
            try:
                read_state(path, now=T0)
            except MaintenanceVetoError:
                check("symlinked veto state fails closed", True)
            else:
                raise AssertionError("symlinked veto state accepted")
        finally:
            if old is None:
                os.environ.pop("MAHO_ADAPTIVE_MAINTENANCE_VETO_PATH", None)
            else:
                os.environ["MAHO_ADAPTIVE_MAINTENANCE_VETO_PATH"] = old

    try:
        state(source="maintenance.eligible")
    except MaintenanceVetoError:
        check("maintenance eligible cannot become executable veto authority", True)
    else:
        raise AssertionError("maintenance eligible entered veto state")

    campaign = (ROOT / "lib/maho_update_campaign.py").read_text(encoding="utf-8")
    gate_index = campaign.index("maintenance_gate_for_user(str(journal[\"user\"]))")
    ready_index = campaign.index("ready = transition_transaction", gate_index)
    mutation_index = campaign.index("candidate = btrfs.create_candidate()", ready_index)
    check("real M4 caller consumes veto before readiness and mutation", gate_index < ready_index < mutation_index)
    check("M4 veto integration contains no process manipulation", not any(token in campaign[gate_index:ready_index] for token in ("kill(", "renice", "systemctl", "pkill")))

    print("ALL ADAPTIVE MAINTENANCE STATE CONTRACTS PASS")


if __name__ == "__main__":
    main()
