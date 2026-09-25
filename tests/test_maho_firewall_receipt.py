#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_firewall_receipt import (  # noqa: E402
    AUTHORITY,
    RECEIPT_KIND,
    current_boot_id,
    policy_path,
    sha256_file,
    verify,
)


def check(name: str, value: bool) -> None:
    if not value:
        raise AssertionError(name)
    print(f"PASS {name}")


def base_receipt(observed_at: str) -> dict:
    live = {
        "schema_version": 1,
        "authority": "table inet maho_host only",
        "state": "present",
        "table_present": True,
        "decision_usable": True,
        "verified": True,
        "result": "protected",
        "reasons": [],
    }
    import hashlib
    raw = json.dumps(live, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": 1,
        "kind": RECEIPT_KIND,
        "observed_at": observed_at,
        "boot_id": current_boot_id(),
        "authority": AUTHORITY,
        "scope": {
            "family": "inet",
            "table": "maho_host",
            "hooks": ["input"],
            "provider_global_authority": False,
            "provider_coexistence": "not-observed-outside-owned-table",
        },
        "policy_sha256": sha256_file(policy_path(ROOT)),
        "policy_path": str(policy_path(ROOT)),
        "live_status": live,
        "live_status_sha256": hashlib.sha256(raw).hexdigest(),
    }


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o755)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    path.chmod(0o644)


def main() -> None:
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        receipt = root / "firewall" / "status.json"
        payload = base_receipt(now.isoformat().replace("+00:00", "Z"))
        write(receipt, payload)

        injected = verify(receipt, root=ROOT, now=now)
        check(
            "user-owned receipt cannot impersonate root observer",
            injected["decision_usable"] is False and injected["receipt_valid"] is False,
        )

        good = verify(
            receipt, root=ROOT, now=now,
            require_root_owner=False,
        )
        check("fresh boot-bound receipt is decision usable", good["decision_usable"] is True)
        check("receipt preserves protected result", good["result"] == "protected")
        check("receipt refuses provider-global authority", good["provider_global_authority"] is False)

        stale_payload = base_receipt((now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
        write(receipt, stale_payload)
        stale = verify(
            receipt, root=ROOT, now=now, max_age_seconds=45,
            require_root_owner=False,
        )
        check("stale receipt fails closed", stale["decision_usable"] is False and stale["result"] == "unknown")
        wrong_boot = base_receipt(now.isoformat().replace("+00:00", "Z"))
        wrong_boot["boot_id"] = "00000000-0000-0000-0000-000000000000"
        write(receipt, wrong_boot)
        boot = verify(receipt, root=ROOT, now=now, require_root_owner=False)
        check("wrong-boot receipt fails closed", boot["decision_usable"] is False)

        wrong_policy = base_receipt(now.isoformat().replace("+00:00", "Z"))
        wrong_policy["policy_sha256"] = "0" * 64
        write(receipt, wrong_policy)
        policy = verify(receipt, root=ROOT, now=now, require_root_owner=False)
        check("policy drift fails closed", policy["decision_usable"] is False)

        tampered = base_receipt(now.isoformat().replace("+00:00", "Z"))
        tampered["live_status"]["verified"] = False
        write(receipt, tampered)
        digest = verify(receipt, root=ROOT, now=now, require_root_owner=False)
        check("tampered live payload digest fails closed", digest["decision_usable"] is False)

        target = root / "target.json"
        write(target, base_receipt(now.isoformat().replace("+00:00", "Z")))
        receipt.unlink()
        receipt.symlink_to(target)
        symlinked = verify(receipt, root=ROOT, now=now, require_root_owner=False)
        check("symlinked receipt fails closed", symlinked["decision_usable"] is False)

    print("ALL MAHO FIREWALL RECEIPT CONTRACTS PASS")


if __name__ == "__main__":
    main()
