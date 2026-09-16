#!/usr/bin/env python3
"""Capture read-only effective nftables evidence across named network contexts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
from typing import Any, Mapping

CONTEXTS = ("normal-wifi", "mullvad-disconnected", "mullvad-connected", "zerotier-active")


def inspect_ruleset(payload: Mapping[str, Any], context: str) -> dict[str, Any]:
    entries = payload.get("nftables")
    if not isinstance(entries, list):
        raise ValueError("nft JSON has no nftables array")
    chains: list[dict[str, Any]] = []
    families: set[str] = set()
    for entry in entries:
        chain = entry.get("chain") if isinstance(entry, Mapping) else None
        if not isinstance(chain, Mapping) or chain.get("hook") != "input":
            continue
        family = chain.get("family")
        if family not in {"inet", "ip", "ip6"}:
            continue
        families.add(str(family))
        chains.append({key: chain.get(key) for key in ("family", "table", "name", "hook", "priority", "policy")})
    ipv4 = "observed" if families.intersection({"inet", "ip"}) else "unavailable"
    ipv6 = "observed" if families.intersection({"inet", "ip6"}) else "unavailable"
    return {
        "schema_version": 1,
        "kind": "maho-firewall-posture-evidence",
        "context": context,
        "read_only": True,
        "coverage": {"ipv4_input": ipv4, "ipv6_input": ipv6, "ruleset_semantics": "raw-evidence"},
        "input_base_chains": chains,
        "result": "observed" if chains else "insufficient-visibility",
        "trust_note": "Base-chain policy is evidence, not a proof that every interface or overlay path is protected.",
    }


def read_ruleset(path: Path | None) -> Mapping[str, Any]:
    if path is not None:
        raw = json.loads(path.read_text())
    else:
        try:
            result = subprocess.run(["nft", "-j", "list", "ruleset"], capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"nft ruleset unavailable: {exc}") from exc
        if result.returncode != 0:
            raise RuntimeError(f"nft ruleset unavailable: {result.stderr.strip()[:300]}")
        raw = json.loads(result.stdout)
    if not isinstance(raw, Mapping):
        raise ValueError("nft ruleset must be an object")
    return raw


def atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try: os.unlink(name)
        except FileNotFoundError: pass


def status(root: Path) -> dict[str, Any]:
    contexts: dict[str, Any] = {}
    for context in CONTEXTS:
        files = sorted((root / context).glob("*.json")) if (root / context).is_dir() else []
        if not files:
            contexts[context] = {"state": "missing"}
            continue
        try:
            value = json.loads(files[-1].read_text())
            coverage = value.get("coverage", {})
            complete = coverage.get("ipv4_input") == coverage.get("ipv6_input") == "observed"
            contexts[context] = {"state": "captured" if complete else "partial", "path": str(files[-1])}
        except (OSError, json.JSONDecodeError):
            contexts[context] = {"state": "invalid", "path": str(files[-1])}
    complete = all(row["state"] == "captured" for row in contexts.values())
    return {"schema_version": 1, "kind": "maho-firewall-certification-status", "complete": complete, "contexts": contexts}


def main() -> int:
    parser = argparse.ArgumentParser(prog="maho-firewall-certify")
    parser.add_argument("command", choices=("inspect", "capture", "status"))
    parser.add_argument("context", nargs="?", choices=CONTEXTS)
    parser.add_argument("--nft-json", type=Path)
    parser.add_argument("--state-root", type=Path, default=Path.home() / ".local/state/maho/firewall-certification")
    args = parser.parse_args()
    if args.command == "status":
        print(json.dumps(status(args.state_root), sort_keys=True)); return 0
    if args.context is None:
        raise SystemExit("inspect/capture requires a named network context")
    try:
        evidence = inspect_ruleset(read_ruleset(args.nft_json), args.context)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        evidence = {"schema_version": 1, "kind": "maho-firewall-posture-evidence", "context": args.context,
                    "read_only": True, "result": "insufficient-visibility", "coverage": {"ipv4_input": "unavailable", "ipv6_input": "unavailable"}, "error": str(exc)}
    if args.command == "capture":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = args.state_root / args.context / f"{stamp}-{uuid.uuid4().hex[:8]}.json"
        atomic_write(target, evidence)
        evidence = {**evidence, "saved": str(target)}
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
