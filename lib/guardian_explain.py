#!/usr/bin/env python3
"""Human explanation surface for active Guardian incidents."""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
from collections import Counter
from typing import Any, Mapping


def read_json(path: pathlib.Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return data if isinstance(data, dict) else None


def severity(row: Mapping[str, Any]) -> int:
    decision = row.get("decision") or {}
    sev = decision.get("severity") or {}
    value = sev.get("level", 0)
    return int(value) if isinstance(value, int) else 0


def timestamp(row: Mapping[str, Any]) -> str:
    return str(row.get("updated_at") or row.get("opened_at") or "")


def active_guardian_rows(state_root: pathlib.Path) -> list[dict[str, Any]]:
    root = state_root / "guardian" / "active"
    rows: list[dict[str, Any]] = []
    if not root.is_dir():
        return rows
    for path in root.glob("inc-*.json"):
        row = read_json(path)
        if row and row.get("status") == "active":
            rows.append(row)
    return sorted(rows, key=lambda r: (severity(r), timestamp(r)), reverse=True)


def find_guardian_row(state_root: pathlib.Path, incident_id: str) -> dict[str, Any] | None:
    active = read_json(state_root / "guardian" / "active" / f"{incident_id}.json")
    if active:
        return active
    archive = state_root / "guardian" / "archive"
    if archive.is_dir():
        candidates = sorted(archive.glob(f"{incident_id}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in candidates:
            row = read_json(path)
            if row:
                return row
    return None


def security_row(state_root: pathlib.Path, incident_id: str) -> dict[str, Any] | None:
    path = state_root / "incidents" / "active" / f"{incident_id}.json"
    row = read_json(path)
    if row:
        return row
    archive = state_root / "incidents" / "archive"
    if archive.is_dir():
        for candidate in sorted(archive.glob(f"{incident_id}*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            row = read_json(candidate)
            if row:
                return row
    return None


def package_owner(path: str) -> str | None:
    if not path.startswith("/"):
        return None
    candidates = [path]
    try:
        resolved = str(pathlib.Path(path).resolve(strict=True))
    except OSError:
        resolved = path
    if resolved != path:
        candidates.append(resolved)
    for candidate in candidates:
        try:
            proc = subprocess.run(
                ("pacman", "-Qo", candidate), text=True, capture_output=True, check=False, timeout=2
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            continue
        text = proc.stdout.strip()
        marker = " is owned by "
        if marker not in text:
            continue
        owned = text.split(marker, 1)[1].strip().split()
        if owned:
            return owned[0]
    return None


def persistence_evidence(signals: list[Mapping[str, Any]]) -> tuple[list[tuple[str, str]], Counter[str]]:
    evidence: list[tuple[str, str]] = []
    owners: Counter[str] = Counter()
    for signal in signals:
        if signal.get("kind") != "persistence-drift":
            continue
        details = signal.get("details") or {}
        for key in ("added", "changed", "removed"):
            for item in details.get(key) or []:
                if not isinstance(item, Mapping):
                    continue
                path = item.get("path")
                if not isinstance(path, str) or not path:
                    continue
                evidence.append((key, path))
                owner = package_owner(path)
                if owner:
                    owners[owner] += 1
    return evidence, owners


def signal_kinds(signals: list[Mapping[str, Any]]) -> list[str]:
    result: list[str] = []
    for signal in signals:
        kind = str(signal.get("kind") or "signal")
        if kind not in result:
            result.append(kind)
    return result


def describe_security(row: Mapping[str, Any]) -> dict[str, Any]:
    signals = [s for s in (row.get("signals") or []) if isinstance(s, Mapping)]
    kinds = signal_kinds(signals)
    evidence, owners = persistence_evidence(signals)
    happened: list[str] = []
    why: list[str] = []
    details: list[str] = []

    if "persistence-drift" in kinds:
        added = sum(1 for k, _ in evidence if k == "added")
        changed = sum(1 for k, _ in evidence if k == "changed")
        removed = sum(1 for k, _ in evidence if k == "removed")
        parts = []
        if added:
            parts.append(f"{added} startup entr{'y' if added == 1 else 'ies'} appeared")
        if changed:
            parts.append(f"{changed} changed")
        if removed:
            parts.append(f"{removed} disappeared")
        happened.append("; ".join(parts) + " since the trusted persistence baseline.")
        why.append("New startup persistence may be an expected install change, so Guardian records it until the new state is explicitly trusted.")
        if owners:
            owner, count = owners.most_common(1)[0]
            if count == len(evidence):
                details.append(f"Likely source: installed package {owner} owns all {count} changed startup paths.")
            else:
                details.append(f"Package ownership: {owner} owns {count}/{len(evidence)} changed startup paths.")
        for kind, path in evidence[:6]:
            details.append(f"{kind}: {path}")
        if len(evidence) > 6:
            details.append(f"… {len(evidence) - 6} more persistence changes")

    for signal in signals:
        kind = signal.get("kind")
        info = signal.get("details") or {}
        if kind == "integrity-drift":
            count = info.get("count") or len(info.get("items") or [])
            happened.append(f"{count} installed package file(s) differ from the package manifest.")
            why.append("Guardian treats unexplained package-file drift as a reliability and integrity signal.")
        elif kind in {"confirmed-finding", "high-confidence-finding"}:
            summary = info.get("summary") or "A security finding applies to an installed package."
            happened.append(str(summary))
            version = info.get("installed_version")
            if version:
                details.append(f"Affected installed version: {version}")
            why.append("The finding is correlated with the package version actually installed on this machine.")
        elif kind == "privilege-boundary":
            added = len(info.get("added") or [])
            changed = len(info.get("changed") or [])
            removed = len(info.get("removed") or [])
            happened.append(f"Privilege boundaries changed ({added} added, {changed} changed, {removed} removed).")
            why.append("Changes to privileged execution paths deserve review even when they are legitimate administration.")
        elif kind == "runtime-executable":
            observations = info.get("observations") or []
            happened.append(f"Guardian observed {len(observations)} unusual runtime executable observation(s).")
            for item in observations[:3]:
                if isinstance(item, Mapping):
                    exe = item.get("exe")
                    pid = item.get("pid")
                    if exe:
                        details.append(f"process: pid={pid or '?'} {exe}")
            why.append("Runtime behavior is used as supporting evidence; it does not trigger host mutation by itself.")
        elif kind == "network-exposure":
            listeners = info.get("listeners") or []
            happened.append(f"The same subject also has {len(listeners)} externally exposed listener(s).")
            why.append("Network exposure raises the importance of another correlated signal; Guardian does not treat it as a standalone incident.")

    if not happened:
        happened.append("Guardian correlated one or more host security signals that do not yet have a specialized explanation.")
    return {"happened": happened, "why": why, "details": details, "kinds": kinds}


def describe_service(row: Mapping[str, Any]) -> dict[str, Any]:
    svc = row.get("service_recovery") or {}
    unit = svc.get("unit") or (row.get("subject") or {}).get("id") or "Maho service"
    failure = svc.get("failure_result") or "unknown"
    lifecycle = svc.get("lifecycle") or "detected"
    happened = [f"{unit} stopped unexpectedly (result={failure})."]
    why = ["This is a Maho-owned service, so Guardian tracks whether the delegated systemd recovery actually returns it to a stable healthy state."]
    details: list[str] = []
    observed = (svc.get("postcondition") or {}).get("observed") or {}
    if observed:
        active = observed.get("active_state") or "?"
        sub = observed.get("sub_state") or "?"
        result = observed.get("result") or "?"
        details.append(f"Observed replacement: {active}/{sub}, result={result}")
        if observed.get("health_ok") is not None:
            details.append(f"Health check: {'passed' if observed.get('health_ok') else 'not yet passed'}")
    replacement = svc.get("replacement_invocation_id")
    if replacement:
        details.append(f"Replacement invocation: {replacement}")
    return {"happened": happened, "why": why, "details": details, "state": lifecycle}


def describe_runtime(row: Mapping[str, Any]) -> dict[str, Any]:
    rr = row.get("runtime_recovery") or {}
    failed = rr.get("failed_runtime") or {}
    replacement = rr.get("replacement_runtime") or {}
    reasons = failed.get("reasons") or []
    happened = ["A newly activated Maho runtime failed immutable-runtime verification."]
    why = ["Guardian treats a failed runtime verification as a component failure because continuing on an unverified runtime can make later recovery less trustworthy."]
    details: list[str] = []
    if reasons:
        details.append("Verification failures: " + ", ".join(str(x) for x in reasons))
    if failed.get("source_revision"):
        details.append(f"Failed revision: {failed['source_revision']}")
    if replacement.get("source_revision"):
        details.append(f"Previous verified revision: {replacement['source_revision']}")
    if rr.get("transaction_id"):
        details.append(f"Recovery transaction: {rr['transaction_id']}")
    return {"happened": happened, "why": why, "details": details, "state": rr.get("lifecycle") or "detected"}


def recovery_text(row: Mapping[str, Any]) -> tuple[str, str]:
    decision = row.get("decision") or {}
    recovery = decision.get("recovery") or {}
    action = str(recovery.get("action") or "none")
    requires = bool(recovery.get("requires_confirmation"))
    automatic = bool(recovery.get("automatic_allowed"))
    provider = recovery.get("provider")

    if action == "diagnose-only":
        doing = "Observing and explaining only. Guardian has no certified mutating recovery for this failure domain."
    elif action == "observe-service-recovery":
        doing = "Leaving restart ownership to systemd and independently verifying that the replacement service becomes healthy and stable."
    elif action == "rollback-previous":
        doing = "Using the bounded previous-runtime recovery path." if automatic else "A bounded previous-runtime rollback exists, but Guardian is not allowed to execute it automatically."
    else:
        mode = "automatic" if automatic else "confirmation-gated" if requires else "non-automatic"
        doing = f"Selected recovery action '{action}' ({mode}{', provider='+str(provider) if provider else ''})."

    if bool(decision.get("mutating_recovery_allowed")):
        mutation = "Host mutation is authorized only inside the selected bounded recovery contract."
    else:
        mutation = "No direct host mutation is authorized for this assessment."
    return doing, mutation


def recommendation(row: Mapping[str, Any], source: Mapping[str, Any] | None, desc: Mapping[str, Any]) -> str:
    kinds = set(desc.get("kinds") or [])
    level = severity(row)
    recovery = (row.get("decision") or {}).get("recovery") or {}
    if source and "persistence-drift" in kinds:
        evidence, owners = persistence_evidence([s for s in (source.get("signals") or []) if isinstance(s, Mapping)])
        if owners and evidence:
            owner, count = owners.most_common(1)[0]
            if count == len(evidence):
                return f"If you intentionally installed or enabled {owner}, this incident is expected; verify that package, then explicitly refresh the trusted persistence baseline. If not, inspect these startup entries before trusting them."
        return "If these startup changes were intentional, verify them before refreshing the trusted persistence baseline. If they were not intentional, investigate the listed paths first."
    if row.get("service_recovery"):
        lifecycle = str((row.get("service_recovery") or {}).get("lifecycle") or "")
        if lifecycle in {"detected", "recovering", "verifying"}:
            return "No immediate action is needed while delegated recovery is progressing. If this remains active, inspect the service journal and the failed invocation."
        return "The service recovery state is recorded; investigate only if the service is still unhealthy or the incident reopens."
    if row.get("runtime_recovery"):
        if recovery.get("requires_confirmation"):
            return "Review the failed and previous verified runtime identities, then confirm rollback only if you want Maho to perform it."
        return "No manual action is needed while the bounded runtime recovery is being verified."
    if source and kinds & {"confirmed-finding", "high-confidence-finding"}:
        return "Review the affected package and vendor fix path. Guardian will not install, remove, or contain anything without the required authority."
    if level >= 3:
        return "Treat this as high priority. Read the evidence below before approving any recovery or containment action."
    return "No immediate action is required. Investigate further if this change was unexpected or if the incident remains active."


def describe(row: Mapping[str, Any], source: Mapping[str, Any] | None) -> dict[str, Any]:
    if row.get("service_recovery"):
        return describe_service(row)
    if row.get("runtime_recovery"):
        return describe_runtime(row)
    if source:
        return describe_security(source)
    explanation = row.get("explanation") or {}
    text = explanation.get("incident") or "Guardian has an active assessment without a specialized explainer yet."
    return {
        "happened": [str(text)],
        "why": [str(explanation.get("severity") or "Guardian is keeping this incident visible until its evidence clears or recovery is verified.")],
        "details": [],
        "kinds": [],
    }


def print_block(label: str, lines: list[str]) -> None:
    if not lines:
        return
    print(label)
    for line in lines:
        print(f"  {line}")


def render_incident(index: int, total: int, row: Mapping[str, Any], source: Mapping[str, Any] | None) -> None:
    decision = row.get("decision") or {}
    sev = decision.get("severity") or {}
    subject = row.get("subject") or {}
    iid = str(row.get("incident_id") or "unknown")
    label = str(sev.get("label") or "normal")
    desc = describe(row, source)
    doing, mutation = recovery_text(row)

    print(f"[{index}/{total}] L{severity(row)} {label}  {subject.get('type','unknown')}:{subject.get('id','unknown')}")
    print_block("What happened", [str(x) for x in desc.get("happened") or []])
    print_block("Why Guardian cares", [str(x) for x in desc.get("why") or []])
    print_block("Evidence", [str(x) for x in desc.get("details") or []])
    print_block("What Maho is doing", [doing, mutation])
    print_block("What you should do", [recommendation(row, source, desc)])
    confidence = ((row.get("normalized") or {}).get("incident") or {}).get("evidence_confidence")
    if source and source.get("confidence"):
        confidence = source.get("confidence")
    print(f"State      {row.get('status','unknown')}  confidence={confidence or 'unknown'}  opened={row.get('opened_at','unknown')}")
    print(f"Incident   {iid}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Explain active Maho Guardian incidents in human terms")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--incident")
    args = parser.parse_args()
    state_root = pathlib.Path(args.state_root)

    if args.incident:
        row = find_guardian_row(state_root, args.incident)
        if not row:
            print(f"Maho Guardian\n─────────────\nIncident {args.incident} was not found.")
            return 1
        rows = [row]
    else:
        rows = active_guardian_rows(state_root)

    print("Maho Guardian")
    print("─────────────")
    if not rows:
        print("Guardian is quiet. No active assessment is driving the wheel.")
        return 0

    highest = max(severity(row) for row in rows)
    noun = "incident" if len(rows) == 1 else "incidents"
    verb = "needs" if len(rows) == 1 else "need"
    print(f"The wheel is active because {len(rows)} {noun} {verb} attention. Highest severity: L{highest}.")
    print()
    for index, row in enumerate(rows, 1):
        source = security_row(state_root, str(row.get("incident_id") or ""))
        render_incident(index, len(rows), row, source)
        if index != len(rows):
            print("\n" + "─" * 72 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
