#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

from guardian_live_state import LivePaths, live_status  # noqa: E402
from guardian_signed_boot_provider import PROOF_FILENAME  # noqa: E402
from test_guardian_signed_boot_provider import BOOT_ID, NOW, proof  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        security = root / "security"
        state = root / "state"
        update = root / "update"
        recovery = root / "recovery"
        runtime = root / "runtime"
        proc = root / "proc"
        signed = root / "signed-boot"
        for path in (security, state, update, recovery, runtime / "releases", proc / "sys/kernel/random", signed):
            path.mkdir(parents=True, exist_ok=True)
        (proc / "sys/kernel/random/boot_id").write_text(BOOT_ID + "\n", encoding="utf-8")
        (signed / PROOF_FILENAME).write_text(json.dumps(proof()), encoding="utf-8")
        paths = LivePaths(security, state, update, recovery, runtime, proc, signed)

        payload = live_status(paths, now=NOW)
        boot = payload["boot"]
        check("canonical live status consumes Signed Boot provider", boot["signed_boot_authority"] == "VERIFIED")
        check("live status surfaces exact BootGeneration identity", str(boot["boot_generation_id"]).startswith("bootgen-"))
        check("live status surfaces exact BootAuthority identity", str(boot["boot_authority_id"]).startswith("bootauth-"))
        check("live status surfaces exact BootEnvironmentIdentity", str(boot["boot_environment_id"]).startswith("bootenv-"))
        check("live status surfaces release sequence and epoch", boot["release_sequence"] == 42 and boot["security_epoch"] == 3)
        check("world-state contains current boot authority evidence", payload["evidence_freshness"]["boot.authority"]["freshness"] == "current")
        boot_domain = payload["world_state"]["domains"]["boot"]
        check("world-state keeps provider health separate", boot_domain[0]["health"] == "healthy" and boot_domain[0]["data"]["trust_state"] == "VERIFIED")
        check("overall trust is not over-promoted past missing system-generation evidence", payload["world_state"]["guardian"]["trust"]["state"] != "VERIFIED")

    print("ALL GUARDIAN LIVE SIGNED BOOT TESTS PASS")


if __name__ == "__main__":
    main()
