#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from guardian_trust_status import recovery_history, render_status, status_payload

def check(name: str, ok: bool) -> None:
    if not ok: raise AssertionError(name)
    print("PASS", name)

def proof(campaign: str, kernel: str = "6.18.42-1-cachyos-lts") -> dict:
    return {
        "schema_version": 1, "outcome": "PASS", "phase": "VERIFIED",
        "campaign_id": campaign, "reason": "native_kernel_recovery_postboot_verified",
        "target_kernel_generation_id": "kgen-" + "1"*64,
        "target_system_generation_id": "gen-" + "2"*64,
        "running_kernel_release": kernel, "root_uuid": "root-uuid",
        "home_subvolume_uuid": "home-uuid", "normal_root_active": True,
        "boot_artifacts_verified": True, "firmware_mutated": False,
        "default_entry": "MahoOS/Fallback (LTS)",
    }

def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        a=root/'r3-20260913T193612Z-aaaaaaaa'; a.mkdir(); (a/'postboot.json').write_text(json.dumps(proof(a.name)))
        b=root/'r3-20260913T190000Z-bbbbbbbb'; b.mkdir(); (b/'postboot.json').write_text('{bad')
        hist=recovery_history(root)
        check("history retains valid and malformed durable records", len(hist)==2 and any(x.valid for x in hist) and any(not x.valid for x in hist))
        payload=status_payload(root, current_kernel_release="6.18.42-1-cachyos-lts")
        check("matching recovered kernel is visible", payload["current_kernel_matches_last_verified_recovery"] is True)
        check("historical recovery never promotes current trust", payload["current_generation_trust"]=="UNRESOLVED")
        check("invalid evidence remains visible", payload["invalid_history_records"]==1)
        text=render_status(payload)
        check("human status names exact recovery campaign", a.name in text)
        check("human status warns trust remains unresolved", "UNRESOLVED" in text)
    with tempfile.TemporaryDirectory() as td:
        payload=status_payload(td, current_kernel_release="test")
        check("missing recovery evidence stays non-authoritative", payload["last_verified_recovery"] is None and payload["current_generation_trust"]=="UNRESOLVED")
    print("ALL GUARDIAN TRUST STATUS TESTS PASS")
    return 0

if __name__ == "__main__": raise SystemExit(main())
