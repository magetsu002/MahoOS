#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

VERSION = 1
MAX_BYTES = 2 * 1024 * 1024

RULES = [
    ("download-pipe-shell", 60, "critical", r"(?:curl|wget)[^\n|]*\|\s*(?:ba)?sh\b", "downloaded content is piped directly to a shell"),
    ("privilege-tool", 48, "high", r"\b(?:sudo|doas|pkexec)\b", "build script invokes a privilege-escalation tool"),
    ("sudoers-change", 55, "critical", r"/etc/sudoers(?:\.d/|\b)", "build script references sudo policy persistence"),
    ("polkit-change", 52, "critical", r"/etc/polkit-1/|/usr/share/polkit-1/", "build script references polkit policy"),
    ("system-service-change", 45, "high", r"/etc/systemd/system/|\bsystemctl\s+(?:enable|preset|reenable|link)\b", "build script can establish system service persistence"),
    ("pacman-hook-change", 42, "high", r"/etc/pacman\.d/hooks/|/usr/share/libalpm/hooks/", "build script references pacman transaction hooks"),
    ("boot-chain-change", 58, "critical", r"/boot/|\b(?:mkinitcpio|grub-install|bootctl)\b", "build script references the boot or initramfs trust chain"),
    ("kernel-module-change", 45, "high", r"\b(?:modprobe|insmod|rmmod|dkms)\b|/etc/modules-load\.d/|/etc/modprobe\.d/", "build script references kernel-module authority"),
    ("file-capability-change", 40, "high", r"\bsetcap\b|\bsetfattr\b[^\n]*security\.capability", "build script can grant executable capabilities"),
    ("setuid-change", 42, "high", r"\bchmod\b[^\n]*(?:u\+s|[0-7]4[0-7]{2})", "build script may grant setuid authority"),
    ("secret-access", 50, "critical", r"(?:\$HOME|~)/(?:\.ssh|\.gnupg|\.aws|\.kube|\.config/gcloud)(?:/|\b)", "build script references high-value user secrets"),
    ("dynamic-eval", 22, "medium", r"\beval\b", "build script uses dynamic shell evaluation"),
    ("shell-indirection", 16, "low", r"\b(?:bash|sh)\s+-c\b", "build script launches an indirect shell command"),
    ("network-fetch", 14, "low", r"\b(?:curl|wget|git\s+clone)\b", "build script performs an explicit network fetch"),
]


def atomic_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def risk_for_score(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 35:
        return "medium"
    if score >= 15:
        return "low"
    return "info"


def analyze_pkgbuild(path: Path, state_root: Path | None) -> dict:
    if not path.is_file():
        raise SystemExit(f"PKGBUILD does not exist: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise SystemExit("PKGBUILD is too large for bounded static preflight")
    text = raw.decode(errors="replace")
    digest = hashlib.sha256(raw).hexdigest()

    findings = []
    strongest: dict[str, dict] = {}
    for rule_id, weight, severity, pattern, explanation in RULES:
        regex = re.compile(pattern, re.IGNORECASE)
        occurrences = []
        for match in regex.finditer(text):
            if len(occurrences) >= 8:
                break
            line = line_for_offset(text, match.start())
            snippet = text.splitlines()[line - 1].strip()[:240] if text.splitlines() else ""
            occurrences.append({"line": line, "snippet": snippet})
        if occurrences:
            strongest[rule_id] = {
                "id": rule_id,
                "weight": weight,
                "severity": severity,
                "explanation": explanation,
                "occurrences": occurrences,
            }

    findings = [strongest[k] for k in sorted(strongest)]
    base = sum(item["weight"] for item in findings)
    diversity_bonus = min(18, max(0, len(findings) - 1) * 3)
    score = min(100, base + diversity_bonus)
    risk = risk_for_score(score)

    if score >= 60:
        decision = "isolated-build-review-required"
    else:
        decision = "isolated-build"

    result = {
        "version": VERSION,
        "kind": "pkgbuild-preflight",
        "path": str(path.resolve()),
        "sha256": digest,
        "static_only": True,
        "pkgbuild_executed": False,
        "risk": risk,
        "score": score,
        "signals": findings,
        "recommended_action": decision,
        "network_during_build": "deny-by-default",
        "host_secret_access": "deny",
        "host_home_access": "deny",
        "automatic_install": False,
        "trust_note": "Static preflight never sources or executes the PKGBUILD. It is evidence for an isolated build decision, not proof of safety.",
    }

    if state_root is not None:
        out = state_root / "preflight" / f"pkgbuild-{digest}.json"
        atomic_private(out, (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
        result["record_path"] = str(out)

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="security_preflight.py")
    sub = parser.add_subparsers(dest="command", required=True)

    pkg = sub.add_parser("pkgbuild")
    pkg.add_argument("path")
    pkg.add_argument("--state-root")

    sub.add_parser("doctor")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "pkgbuild":
        result = analyze_pkgbuild(Path(args.path).expanduser(), Path(args.state_root) if args.state_root else None)
    elif args.command == "doctor":
        result = {
            "version": VERSION,
            "kind": "security-preflight-engine",
            "status": "ok",
            "pkgbuild_execution": "never",
            "default_build_policy": "isolated",
            "automatic_install": False,
        }
    else:
        raise SystemExit("unknown command")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
