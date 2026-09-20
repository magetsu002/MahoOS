#!/usr/bin/env python3
"""Run delegated service recovery watcher with read-only reliability sampling."""
from __future__ import annotations

from pathlib import Path
import sys
import threading

from guardian_live_response import response_loop
from guardian_reliability_provider import reliability_loop, resolve_state_root
from guardian_service_watcher import main as service_watcher_main


def _boot_id() -> str | None:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        root = resolve_state_root(sys.argv[2:])
        threading.Thread(
            target=reliability_loop,
            kwargs={"root": root, "boot_id": _boot_id()},
            name="maho-guardian-reliability",
            daemon=True,
        ).start()
        threading.Thread(
            target=response_loop,
            kwargs={"state_root": root},
            name="maho-guardian-live-response",
            daemon=True,
        ).start()
    return service_watcher_main()


if __name__ == "__main__":
    raise SystemExit(main())
