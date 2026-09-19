#!/usr/bin/env python3
"""Read-only host-firewall evidence and conservative posture classification."""
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
RESULTS = {
    "protected", "unprotected", "partial", "insufficient-visibility",
    "provider-conflict", "unsupported", "stale",
}
DEFAULT_MAX_AGE_SECONDS = 3600
OWNER_PROVIDERS = {"maho", "mullvad", "firewalld", "ufw"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def boot_id() -> str | None:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None

def network_context(context: str) -> dict[str, str]:
    mullvad = "unspecified"
    zerotier = "unspecified"
    wifi = "active" if context == "normal-wifi" else "unspecified"
    if context == "mullvad-disconnected":
        mullvad = "disconnected"
    elif context == "mullvad-connected":
        mullvad = "connected"
    elif context == "zerotier-active":
        zerotier = "active"
    return {"name": context, "wifi": wifi, "mullvad": mullvad, "zerotier": zerotier}


def provider_hint(family: str, table: str, chain: str) -> str:
    text = f"{family} {table} {chain}".lower()
    if "maho" in text:
        return "maho"
    if "mullvad" in text or "talpid" in text:
        return "mullvad"
    if "firewalld" in text or "filter_in_" in text or "filter_out_" in text:
        return "firewalld"
    if "ufw" in text:
        return "ufw"
    if "docker" in text:
        return "docker"
    if "libvirt" in text:
        return "libvirt"
    return "unattributed"


def normalize_chain(chain: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "family": chain.get("family"), "table": chain.get("table"),
        "name": chain.get("name"), "hook": chain.get("hook"),
        "priority": chain.get("priority", chain.get("prio")),
        "policy": chain.get("policy"),
        "provider": provider_hint(str(chain.get("family", "")), str(chain.get("table", "")), str(chain.get("name", ""))),
    }

def chain_key(chain: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(chain.get("family", "")), str(chain.get("table", "")), str(chain.get("name", "")))


def family_posture(
    family: str,
    chains: list[dict[str, Any]],
    rule_counts: Mapping[tuple[str, str, str], int],
) -> str:
    accepted = {"inet", "ip"} if family == "ipv4" else {"inet", "ip6"}
    relevant = [chain for chain in chains if chain.get("family") in accepted]
    if not relevant:
        # Successful ruleset visibility plus no input base chain means no
        # observed host-input filter for this family, not a visibility error.
        return "unprotected"
    if any(str(chain.get("policy") or "accept").lower() == "drop" for chain in relevant):
        return "protected"
    if any(rule_counts.get(chain_key(chain), 0) > 0 for chain in relevant):
        # A default-accept chain may implement a terminal rules-based deny.
        # Do not guess at arbitrary nft control flow.
        return "unsupported"
    return "unprotected"


def overall_result(ipv4: str, ipv6: str, owners: set[str]) -> str:
    if len(owners) > 1:
        return "provider-conflict"
    if ipv4 == ipv6 == "protected":
        return "protected"
    if ipv4 == ipv6 == "unprotected":
        return "unprotected"
    if ipv4 == ipv6 == "unsupported":
        return "unsupported"
    return "partial"

def inspect_ruleset(
    payload: Mapping[str, Any],
    context: str,
    *,
    observed_at: datetime | None = None,
    privilege_level: str = "provided-evidence",
    source: str = "provided-nft-json",
) -> dict[str, Any]:
    entries = payload.get("nftables")
    if not isinstance(entries, list):
        raise ValueError("nft JSON has no nftables array")

    tables: list[dict[str, Any]] = []
    table_seen: set[tuple[str, str]] = set()
    chains: list[dict[str, Any]] = []
    rule_counts: dict[tuple[str, str, str], int] = {}

    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        table = entry.get("table")
        if isinstance(table, Mapping):
            key = (str(table.get("family", "")), str(table.get("name", "")))
            if key not in table_seen:
                table_seen.add(key)
                tables.append({"family": table.get("family"), "name": table.get("name")})
        chain = entry.get("chain")
        if isinstance(chain, Mapping) and chain.get("hook") == "input" and chain.get("family") in {"inet", "ip", "ip6"}:
            normalized = normalize_chain(chain)
            chains.append(normalized)
            key = (str(normalized.get("family", "")), str(normalized.get("table", "")))
            if key not in table_seen:
                table_seen.add(key)
                tables.append({"family": normalized.get("family"), "name": normalized.get("table")})
        rule = entry.get("rule")
        if isinstance(rule, Mapping):
            key = (str(rule.get("family", "")), str(rule.get("table", "")), str(rule.get("chain", "")))
            rule_counts[key] = rule_counts.get(key, 0) + 1

    providers = sorted({str(chain["provider"]) for chain in chains if chain.get("provider")})
    owners = {provider for provider in providers if provider in OWNER_PROVIDERS}
    ipv4 = family_posture("ipv4", chains, rule_counts)
    ipv6 = family_posture("ipv6", chains, rule_counts)
    result = overall_result(ipv4, ipv6, owners)

    if result == "provider-conflict":
        owner, authority_state = "multiple", "ambiguous-multiple-owners"
    elif result == "protected":
        owner, authority_state = next(iter(owners), "unattributed-nftables"), "observed-default-deny"
    elif result == "unprotected":
        owner, authority_state = "none", "no-observed-input-filter"
    elif result == "unsupported":
        owner = next(iter(owners), "unattributed-nftables") if chains else "none"
        authority_state = "ruleset-semantics-unsupported"
    else:
        owner = next(iter(owners), "unattributed-nftables") if chains else "none"
        authority_state = "partial-or-mixed"

    observed = observed_at or utc_now()
    return {
        "schema_version": 2,
        "kind": "maho-firewall-posture-evidence",
        "context": context,
        "network_context": network_context(context),
        "read_only": True,
        "observed_at": iso_utc(observed),
        "boot_id": boot_id(),
        "source": source,
        "privilege_level": privilege_level,
        "ruleset_visibility": "complete",
        "tables_inspected": tables,
        "input_base_chains": chains,
        "providers": providers,
        "authority": {
            "owner": owner,
            "state": authority_state,
            "basis": "nftables-input-base-chain-default-policy",
        },
        "coverage": {
            "ipv4_input": ipv4,
            "ipv6_input": ipv6,
            "ruleset_semantics": "conservative-default-policy",
        },
        "result": result,
        "decision_usable": result == "protected",
        "trust_note": (
            "Default-deny input coverage proves a host filtering baseline only. "
            "It does not prove that every accepted service, interface, overlay path, or provider policy is safe."
        ),
    }


def read_ruleset(path: Path | None) -> tuple[Mapping[str, Any], str, str]:
    if path is not None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        source = f"file:{path}"
        privilege = "provided-evidence"
    else:
        try:
            result = subprocess.run(
                ["nft", "-j", "list", "ruleset"], capture_output=True,
                text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"nft ruleset unavailable: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip()[:300] or f"exit={result.returncode}"
            raise RuntimeError(f"nft ruleset unavailable: {detail}")
        raw = json.loads(result.stdout)
        source = "live:nft-netlink"
        privilege = "root" if os.geteuid() == 0 else "netlink-authorized-nonroot"
    if not isinstance(raw, Mapping):
        raise ValueError("nft ruleset must be an object")
    return raw, source, privilege


def visibility_failure(context: str, exc: Exception) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "kind": "maho-firewall-posture-evidence",
        "context": context,
        "network_context": network_context(context),
        "read_only": True,
        "observed_at": iso_utc(utc_now()),
        "boot_id": boot_id(),
        "source": "live:nft-netlink",
        "privilege_level": "root" if os.geteuid() == 0 else "unprivileged",
        "ruleset_visibility": "insufficient",
        "tables_inspected": [],
        "input_base_chains": [],
        "providers": [],
        "authority": {"owner": "unknown", "state": "unobservable", "basis": "none"},
        "result": "insufficient-visibility",
        "decision_usable": False,
        "coverage": {
            "ipv4_input": "unavailable",
            "ipv6_input": "unavailable",
            "ruleset_semantics": "unavailable",
        },
        "error": str(exc),
    }


def atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def status(
    root: Path,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or utc_now()
    contexts: dict[str, Any] = {}
    for context in CONTEXTS:
        directory = root / context
        files = sorted(directory.glob("*.json")) if directory.is_dir() else []
        if not files:
            contexts[context] = {"state": "missing", "decision_usable": False}
            continue
        path = files[-1]
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            contexts[context] = {
                "state": "unsupported", "decision_usable": False,
                "path": str(path),
            }
            continue
        observed = parse_timestamp(value.get("observed_at")) if isinstance(value, Mapping) else None
        if observed is None:
            contexts[context] = {
                "state": "stale", "decision_usable": False,
                "path": str(path), "reason": "missing-observation-time",
            }
            continue
        age = max(0.0, (current - observed).total_seconds())
        result = str(value.get("result", "unsupported"))
        if age > max_age_seconds:
            state, usable = "stale", False
        elif result in RESULTS - {"stale"}:
            state = result
            usable = result == "protected" and bool(value.get("decision_usable"))
        else:
            state, usable = "unsupported", False
        contexts[context] = {
            "state": state,
            "result": result,
            "decision_usable": usable,
            "age_seconds": round(age, 3),
            "path": str(path),
            "authority": value.get("authority"),
            "coverage": value.get("coverage"),
        }
    complete = all(
        row.get("state") == "protected" and row.get("decision_usable") is True
        for row in contexts.values()
    )
    return {
        "schema_version": 2,
        "kind": "maho-firewall-certification-status",
        "complete": complete,
        "max_age_seconds": max_age_seconds,
        "contexts": contexts,
    }

def main() -> int:
    parser = argparse.ArgumentParser(prog="maho-firewall-certify")
    parser.add_argument("command", choices=("inspect", "capture", "status"))
    parser.add_argument("context", nargs="?", choices=CONTEXTS)
    parser.add_argument("--nft-json", type=Path)
    parser.add_argument(
        "--state-root", type=Path,
        default=Path.home() / ".local/state/maho/firewall-certification",
    )
    parser.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS)
    args = parser.parse_args()

    if args.max_age_seconds < 1:
        raise SystemExit("--max-age-seconds must be positive")
    if args.command == "status":
        print(json.dumps(status(args.state_root, max_age_seconds=args.max_age_seconds), sort_keys=True))
        return 0
    if args.context is None:
        raise SystemExit("inspect/capture requires a named network context")

    try:
        payload, source, privilege = read_ruleset(args.nft_json)
        evidence = inspect_ruleset(
            payload, args.context, privilege_level=privilege, source=source,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        evidence = visibility_failure(args.context, exc)
        if args.nft_json is not None:
            evidence["source"] = f"file:{args.nft_json}"
            evidence["privilege_level"] = "provided-evidence"

    if args.command == "capture":
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        target = args.state_root / args.context / f"{stamp}-{uuid.uuid4().hex[:8]}.json"
        atomic_write(target, evidence)
        evidence = {**evidence, "saved": str(target)}
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
