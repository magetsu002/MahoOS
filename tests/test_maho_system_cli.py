#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]

def run(*args: str, input_text: str | None = None):
    return subprocess.run(["bash", str(ROOT / "bin" / "maho"), *args], cwd=ROOT, text=True, input=input_text, capture_output=True, check=False)

def check(name: str, ok: bool):
    if not ok: raise AssertionError(name)
    print("PASS", name)

def main():
    status=run("status")
    check("plain status is automation-safe", status.returncode == 0 and "System health:" in status.stdout and "\x1b[" not in status.stdout)
    doctor=run("doctor")
    check(
        "plain doctor is attention-focused",
        doctor.returncode == 0
        and "Overall trust:" in doctor.stdout
        and "Signed Boot evidence:" in doctor.stdout
        and "Provider guardian.watch:" not in doctor.stdout
        and "Normal update execution authority:" not in doctor.stdout
        and "Showing checks that need review." in doctor.stdout,
    )
    generation_line=next(line for line in doctor.stdout.splitlines() if "Overall trust:" in line)
    signed_boot_line=next(line for line in doctor.stdout.splitlines() if "Signed Boot evidence:" in line)
    semantic_states=("PASS", "WARN", "FAIL", "Unresolved", "Not established", "Awaiting certification", "Verified", "Untrusted", "Unknown", "N/A", "None yet")
    check(
        "plain doctor translates known trust reasons",
        generation_line.startswith(semantic_states)
        and signed_boot_line.startswith("Awaiting certification")
        and signed_boot_line.startswith(semantic_states),
    )
    check("plain doctor does not leak explained UNKNOWN", "UNKNOWN Trust" not in doctor.stdout and "UNKNOWN Guardian" not in doctor.stdout)
    doctor_all=run("doctor", "--all")
    check(
        "doctor --all preserves full diagnostics",
        doctor_all.returncode == 0
        and "Immutable Maho runtime:" in doctor_all.stdout
        and "Provider guardian.watch:" in doctor_all.stdout
        and "Normal update execution authority:" in doctor_all.stdout,
    )
    invalid_all=run("status", "--all")
    check("--all is Doctor-only", invalid_all.returncode == 2)
    structured=run("status", "--json")
    payload=json.loads(structured.stdout)
    check("json status is stable structured output", structured.returncode == 0 and payload["schema_version"] == 1 and payload["view"] == "Overview")
    evidence=run("trust", "--json", "--evidence")
    check("json evidence is explicit opt-in", "evidence" in json.loads(evidence.stdout))
    tui=run("tui")
    check("non-tty never receives terminal takeover", tui.returncode == 2 and "requires a terminal" in tui.stderr and "\x1b[" not in tui.stdout)
    print("ALL MAHO SYSTEM CLI TESTS PASS")
if __name__ == "__main__": main()
