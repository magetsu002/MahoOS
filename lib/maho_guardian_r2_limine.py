#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BEGIN = "# MAHO-GUARDIAN-R2-BEGIN"
END = "# MAHO-GUARDIAN-R2-END"
TITLE = "/Guardian Recovery R2"


def _is_top_level_entry(line: str) -> bool:
    return line.startswith("/") and not line.startswith("//")


def sanitize_text(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    in_marked = False
    in_stale = False
    for line in lines:
        if line == BEGIN:
            in_marked = True
            in_stale = False
            continue
        if line == END:
            in_marked = False
            in_stale = False
            continue
        if in_marked:
            continue
        if line == TITLE:
            in_stale = True
            continue
        if in_stale:
            if _is_top_level_entry(line):
                in_stale = False
                out.append(line)
            continue
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def sanitize_file(src: Path, dst: Path) -> None:
    dst.write_text(sanitize_text(src.read_text()), encoding="utf-8")

def expected_cmdline(manifest: dict, manifest_sha: str) -> str:
    root = manifest["root"]
    esp = manifest["esp"]
    campaign = manifest["campaign_id"]
    fsroot = str(root["fsroot"]).lstrip("/")
    return (
        f"kernel_cmdline: root=UUID={root['uuid']} ro "
        f"rootflags=subvol={fsroot},ro "
        "maho.guardian_recovery=r2 "
        f"maho.guardian_manifest_sha256={manifest_sha} "
        f"maho.guardian_esp_partuuid={esp['partuuid']} "
        f"maho.guardian_campaign={campaign}"
    )


def verify_entry_binding(entry: Path, manifest_path: Path) -> None:
    raw = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(raw).hexdigest()
    manifest = json.loads(raw)
    lines = entry.read_text().splitlines()
    if lines.count(TITLE) != 1:
        raise ValueError("entry must contain exactly one R2 title")
    cmdline = expected_cmdline(manifest, manifest_sha)
    if lines.count(cmdline) != 1:
        raise ValueError("entry is not bound to exact staged manifest")


def verify_config(config: Path, entry: Path, manifest: Path) -> None:
    verify_entry_binding(entry, manifest)
    lines = config.read_text().splitlines()
    if lines.count(BEGIN) != 1 or lines.count(END) != 1:
        raise ValueError("config must contain exactly one R2 marker pair")
    if lines.count(TITLE) != 1:
        raise ValueError("config must contain exactly one R2 entry")
    begin = lines.index(BEGIN)
    end = lines.index(END)
    if begin >= end:
        raise ValueError("R2 markers are out of order")
    expected = [BEGIN, *entry.read_text().splitlines(), END]
    actual = lines[begin : end + 1]
    if actual != expected:
        raise ValueError("R2 config block differs from exact staged entry")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: maho_guardian_r2_limine.py {sanitize|verify} ...")
    action = argv[1]
    if action == "sanitize" and len(argv) == 4:
        sanitize_file(Path(argv[2]), Path(argv[3]))
        return 0
    if action == "verify" and len(argv) == 5:
        verify_config(Path(argv[2]), Path(argv[3]), Path(argv[4]))
        return 0
    raise SystemExit("invalid arguments")


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"maho-guardian-r2-limine: {exc}", file=sys.stderr)
        raise SystemExit(1)
