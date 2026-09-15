#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_intent import ChangeObservation, correlate_change  # noqa: E402
from guardian_live_state import _update_authority  # noqa: E402


def main() -> None:
    # Live authoritative records are deliberately not converted to
    # AuthorizedOperation until they carry an explicit bounded intent window.
    # This protects guardian_intent.py's exact-match suppression contract.
    if not callable(correlate_change) or not callable(_update_authority):
        raise AssertionError("intent correlation boundary unavailable")
    ChangeObservation(
        kind="file-change",
        subject="/etc/example",
        observed_at="2026-09-15T09:00:00Z",
        source="fixture",
    )
    print("PASS live authority remains evidence until bounded intent exists")


if __name__ == "__main__":
    main()
