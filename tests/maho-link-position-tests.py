#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "config/quickshell/maho-link/position.py"


def run(*arguments: object) -> dict:
    result = subprocess.run(
        ["python3", str(HELPER), *(str(value) for value in arguments)],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout) if result.stdout else {}


def load(path: Path, mode: str, *, width: int = 486, height: int = 560,
         monitor_width: int = 1600, monitor_height: int = 1200,
         legacy: Path | None = None) -> dict:
    arguments: list[object] = [
        "load", "--path", path, "--mode", mode,
        "--monitor", "test-output",
        "--monitor-width", monitor_width, "--monitor-height", monitor_height,
        "--surface-width", width, "--surface-height", height,
        "--margin-x", 24, "--margin-y", 20,
    ]
    if legacy is not None:
        arguments.extend(("--legacy", legacy))
    return run(*arguments)


def save(path: Path, mode: str, x: int, y: int) -> None:
    run(
        "save", "--path", path, "--mode", mode,
        "--x", x, "--y", y, "--monitor", "test-output",
        "--monitor-width", 1600, "--monitor-height", 1200,
    )


with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    state = base / "maho/link-position.json"

    # Each mode owns its own coordinate and neither save changes the other.
    assert load(state, "wifi")["source"] == "missing"
    save(state, "wifi", 123, 456)
    bluetooth = load(state, "bluetooth", width=486, height=652)
    assert bluetooth["source"] == "missing-mode"
    assert bluetooth["valid"] is False

    wifi = load(state, "wifi", width=486, height=430)
    assert (wifi["requested_x"], wifi["requested_y"]) == (123, 456)

    save(state, "bluetooth", 500, 700)
    wifi = load(state, "wifi", width=486, height=430)
    bluetooth = load(state, "bluetooth", width=486, height=652)
    assert (wifi["requested_x"], wifi["requested_y"]) == (123, 456)
    assert (bluetooth["requested_x"], bluetooth["requested_y"]) == (500, 700)

    stored = json.loads(state.read_text(encoding="utf-8"))
    assert stored["version"] == 4
    assert (stored["positions"]["wifi"]["x"], stored["positions"]["wifi"]["y"]) == (123, 456)
    assert (stored["positions"]["bluetooth"]["x"], stored["positions"]["bluetooth"]["y"]) == (500, 700)
    assert stored["positions"]["wifi"]["updated_at"]

    # Clamp only the selected mode's applied coordinate; never mutate its anchor.
    save(state, "wifi", 1400, 1000)
    small = load(state, "wifi", width=120, height=100)
    large = load(state, "bluetooth", width=486, height=652)
    assert (small["requested_x"], small["requested_y"]) == (1400, 1000)
    assert (large["requested_x"], large["requested_y"]) == (500, 700)
    assert (small["x"], small["y"]) == (1400, 1000)
    assert (large["x"], large["y"]) == (500, 528)
    assert large["clamped"] is True
    assert json.loads(state.read_text(encoding="utf-8"))["positions"]["wifi"]["x"] == 1400

    # Missing and corrupted files fail closed and do not fabricate state.
    missing = base / "missing.json"
    assert load(missing, "wifi")["source"] == "missing"
    assert not missing.exists()
    corrupted = base / "corrupted.json"
    corrupted.write_text("{not-json", encoding="utf-8")
    assert load(corrupted, "bluetooth")["source"] == "invalid"
    assert corrupted.read_text(encoding="utf-8") == "{not-json"

    # v1 normalized migration seeds both modes once; they then diverge.
    migrated = base / "migrated.json"
    legacy_v1 = base / "legacy-v1.json"
    legacy_v1.write_text(json.dumps({
        "version": 1, "valid": True,
        "normalizedX": 0.25, "normalizedY": 0.5,
    }), encoding="utf-8")
    first = load(migrated, "wifi", legacy=legacy_v1)
    assert (first["requested_x"], first["requested_y"]) == (412, 600)
    migrated_state = json.loads(migrated.read_text(encoding="utf-8"))
    assert migrated_state["version"] == 4
    assert migrated_state["positions"]["bluetooth"]["x"] == 412

    # A newer legacy file can never override existing v4 positions.
    legacy_v1.write_text(json.dumps({
        "version": 1, "valid": True,
        "normalizedX": 0.9, "normalizedY": 0.9,
    }), encoding="utf-8")
    again = load(migrated, "bluetooth", legacy=legacy_v1)
    assert (again["requested_x"], again["requested_y"]) == (412, 600)
    assert again["source"] == "v4"
    save(migrated, "bluetooth", 800, 200)
    assert (load(migrated, "wifi")["requested_x"], load(migrated, "wifi")["requested_y"]) == (412, 600)
    assert (load(migrated, "bluetooth")["requested_x"], load(migrated, "bluetooth")["requested_y"]) == (800, 200)

    # v2 migration trusts exact pixels, not contradictory normalized values.
    migrated_v2 = base / "migrated-v2.json"
    legacy_v2 = base / "legacy-v2.json"
    legacy_v2.write_text(json.dumps({
        "version": 2, "valid": True,
        "pixelX": 333, "pixelY": 444,
        "normalizedX": 0.01, "normalizedY": 0.02,
    }), encoding="utf-8")
    result_v2 = load(migrated_v2, "bluetooth", legacy=legacy_v2)
    assert (result_v2["requested_x"], result_v2["requested_y"]) == (333, 444)
    assert (load(migrated_v2, "wifi")["requested_x"], load(migrated_v2, "wifi")["requested_y"]) == (333, 444)

    # The immediately previous v3 shared state also seeds both modes once.
    migrated_v3 = base / "migrated-v3.json"
    migrated_v3.write_text(json.dumps({
        "version": 3, "x": 210, "y": 310,
        "monitor_width": 1600, "monitor_height": 1200,
    }), encoding="utf-8")
    assert (load(migrated_v3, "wifi")["requested_x"], load(migrated_v3, "wifi")["requested_y"]) == (210, 310)
    assert (load(migrated_v3, "bluetooth")["requested_x"], load(migrated_v3, "bluetooth")["requested_y"]) == (210, 310)
    save(migrated_v3, "wifi", 111, 222)
    assert (load(migrated_v3, "wifi")["requested_x"], load(migrated_v3, "wifi")["requested_y"]) == (111, 222)
    assert (load(migrated_v3, "bluetooth")["requested_x"], load(migrated_v3, "bluetooth")["requested_y"]) == (210, 310)

print("PASS  independent Wi-Fi/Bluetooth save-load, corruption, migration, clamp, and size tests")
