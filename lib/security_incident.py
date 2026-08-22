#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

from security_probe import atomic_private, normalized_package_paths, package_records, stable_hash

VERSION = 1
INCIDENT_RE = re.compile(r"^inc-[a-z0-9._-]+-[0-9a-f]{16}$")
RISK_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

WEIGHTS = {
    "confirmed-finding": 60,
    "high-confidence-finding": 48,
    "integrity-drift": 38,
    "privilege-boundary": 48,
    "persistence-drift": 34,
    "runtime-executable": 18,
}

SENSITIVE_PERSISTENCE_PREFIXES = (
    "/etc/sudoers",
    "/etc/polkit-1/",
    "/etc/systemd/system/",
    "/etc/modules-load.d/",
    "/etc/modprobe.d/",
    "/etc/pacman.d/hooks/",
    "/etc/mkinitcpio",
    "/boot/",
)


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def incident_id(subject_type: str, subject_id: str) -> str:
    digest = hashlib.sha256(f"{subject_type}:{subject_id}".encode()).hexdigest()[:16]
    safe = re.sub(r"[^a-z0-9._-]+", "-", subject_type.lower()).strip("-") or "subject"
    return f"inc-{safe}-{digest}"


def installed_versions(db_root: Path) -> dict[str, str]:
    return {record["name"]: record["version"] for record in package_records(db_root)}


def path_package_index(db_root: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    for record in package_records(db_root):
        for path in normalized_package_paths(record):
            index.setdefault(path, record["name"])
    return index


def signal(kind: str, source: str, weight: int, details: dict, confidence: str = "heuristic") -> dict:
    return {
        "kind": kind,
        "source": source,
        "weight": int(weight),
        "confidence": confidence,
        "details": details,
    }


def add_signal(groups: dict[tuple[str, str], list[dict]], subject_type: str, subject_id: str, value: dict) -> None:
    groups.setdefault((subject_type, subject_id), []).append(value)


def risk_for_score(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 40:
        return "medium"
    if score >= 20:
        return "low"
    return "info"


def confidence_for(signals: list[dict], score: int) -> str:
    if any(s.get("confidence") == "confirmed" for s in signals):
        return "confirmed"
    sources = {s.get("source") for s in signals if s.get("source")}
    if score >= 70 and len(sources) >= 2:
        return "high"
    if len(sources) >= 2 or score >= 40:
        return "medium"
    return "low"


def unique_signal_set(signals: list[dict]) -> list[dict]:
    # Repeated evidence of the same class must not inflate risk indefinitely.
    # Keep the strongest item per kind and retain a bounded sample of details.
    by_kind: dict[str, dict] = {}
    for item in signals:
        kind = item["kind"]
        existing = by_kind.get(kind)
        if existing is None or item["weight"] > existing["weight"]:
            by_kind[kind] = dict(item)
        elif existing is not None:
            samples = existing.setdefault("correlated", [])
            if len(samples) < 8:
                samples.append(item.get("details", {}))
    return [by_kind[k] for k in sorted(by_kind)]


def build_incident(
    subject_type: str,
    subject_id: str,
    raw_signals: list[dict],
    prevention_mode: str,
    autonomy_level: str,
    provenance_baseline: bool,
    persistence_baseline: bool,
) -> dict:
    signals = unique_signal_set(raw_signals)
    base = sum(int(s.get("weight", 0)) for s in signals)
    source_count = len({s.get("source") for s in signals if s.get("source")})
    diversity_bonus = min(20, max(0, source_count - 1) * 10)
    score = min(100, base + diversity_bonus)
    risk = risk_for_score(score)
    confidence = confidence_for(signals, score)

    confirmed_finding = any(s["kind"] == "confirmed-finding" for s in signals)
    runtime_pids: list[int] = []
    for s in signals:
        if s["kind"] != "runtime-executable":
            continue
        for pid in s.get("details", {}).get("pids", []):
            if isinstance(pid, int) and pid not in runtime_pids:
                runtime_pids.append(pid)
    runtime_pids.sort()

    containment_eligible = subject_type == "package" and confirmed_finding and bool(runtime_pids)
    response_reversible = containment_eligible

    if score < 35:
        recommended = "observe"
    elif score < 60:
        recommended = "investigate"
    elif containment_eligible:
        recommended = "contain-processes"
    else:
        recommended = "restrict-and-investigate"

    if score >= 80 and containment_eligible and provenance_baseline:
        recommended = "contain-and-prepare-recovery"

    if prevention_mode == "off":
        shadow_action = "none"
    else:
        shadow_action = recommended

    # V1 prevention remains shadow-only. No incident assessment mutates system
    # state. The separate containment command still requires explicit user
    # confirmation and re-validates the target at execution time.
    enforced_action = "none"

    attention = "silent"
    if risk == "critical" and confidence == "confirmed":
        attention = "notification"

    core = {
        "version": VERSION,
        "kind": "security-incident",
        "incident_id": incident_id(subject_type, subject_id),
        "status": "active",
        "subject": {"type": subject_type, "id": subject_id},
        "risk": risk,
        "score": score,
        "confidence": confidence,
        "source_diversity": source_count,
        "signals": signals,
        "recommended_action": recommended,
        "shadow_action": shadow_action,
        "enforced_action": enforced_action,
        "containment_eligible": containment_eligible,
        "response_reversible": response_reversible,
        "runtime_pids": runtime_pids,
        "attention": attention,
        "policy": {
            "prevention_mode": prevention_mode,
            "autonomy_level": autonomy_level,
            "automatic_system_mutation": False,
            "user_confirmation_required_for_containment": True,
        },
        "trust": {
            "package_provenance_baseline": provenance_baseline,
            "persistence_baseline": persistence_baseline,
        },
    }
    core["assessment_sha256"] = stable_hash(core)
    return core


def collect_groups(security_state: Path, db_root: Path) -> dict[tuple[str, str], list[dict]]:
    monitor = security_state / "monitor-v2"
    groups: dict[tuple[str, str], list[dict]] = {}
    path_index = path_package_index(db_root)
    versions = installed_versions(db_root)

    persistence = read_json(monitor / "persistence.json", {}) or {}
    if persistence.get("result") == "changed":
        changed_rows = []
        changed_rows.extend(persistence.get("added") or [])
        for row in persistence.get("changed") or []:
            if isinstance(row, dict):
                changed_rows.append(row.get("after") or row)
        sensitive = []
        ordinary = []
        for row in changed_rows:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "")
            if any(path == p.rstrip("/") or path.startswith(p) for p in SENSITIVE_PERSISTENCE_PREFIXES):
                sensitive.append(row)
            else:
                ordinary.append(row)
        if sensitive:
            add_signal(groups, "host", "local", signal(
                "privilege-boundary",
                "persistence-baseline",
                WEIGHTS["privilege-boundary"],
                {"items": sensitive[:20], "count": len(sensitive)},
                "corroborated",
            ))
        if ordinary or not changed_rows:
            add_signal(groups, "host", "local", signal(
                "persistence-drift",
                "persistence-baseline",
                WEIGHTS["persistence-drift"],
                {"added": persistence.get("added", [])[:20], "changed": persistence.get("changed", [])[:20]},
                "corroborated",
            ))

    integrity = read_json(monitor / "integrity.json", {}) or {}
    if integrity.get("result") == "changed":
        by_package: dict[str, list[dict]] = {}
        for key in ("modified", "missing", "type_changed"):
            for row in integrity.get(key) or []:
                if not isinstance(row, dict):
                    continue
                package = row.get("package")
                if package:
                    by_package.setdefault(str(package), []).append({"class": key, **row})
        for package, rows in by_package.items():
            add_signal(groups, "package", package, signal(
                "integrity-drift",
                "pacman-mtree",
                WEIGHTS["integrity-drift"],
                {"items": rows[:20], "count": len(rows)},
                "corroborated",
            ))
        if not by_package:
            add_signal(groups, "host", "local", signal(
                "integrity-drift",
                "pacman-mtree",
                WEIGHTS["integrity-drift"],
                {"result": "changed"},
                "corroborated",
            ))

    runtime = read_json(monitor / "runtime.json", {}) or {}
    if runtime.get("result") == "observed":
        mapped: dict[str, list[dict]] = {}
        unmapped: list[dict] = []
        for row in runtime.get("observations") or []:
            if not isinstance(row, dict):
                continue
            rel = str(row.get("relative_exe") or "")
            package = path_index.get(rel)
            item = {
                "pid": row.get("pid"),
                "exe": row.get("exe"),
                "signals": row.get("signals") or [],
            }
            if package:
                mapped.setdefault(package, []).append(item)
            else:
                unmapped.append(item)
        for package, rows in mapped.items():
            add_signal(groups, "package", package, signal(
                "runtime-executable",
                "procfs",
                WEIGHTS["runtime-executable"],
                {"pids": sorted({int(r["pid"]) for r in rows if isinstance(r.get("pid"), int)}), "observations": rows[:20]},
                "heuristic",
            ))
        if unmapped:
            add_signal(groups, "host", "local", signal(
                "runtime-executable",
                "procfs",
                WEIGHTS["runtime-executable"],
                {"pids": sorted({int(r["pid"]) for r in unmapped if isinstance(r.get("pid"), int)}), "observations": unmapped[:20]},
                "heuristic",
            ))

    findings_dir = security_state / "findings"
    if findings_dir.is_dir():
        for path in sorted(findings_dir.glob("*.json")):
            finding = read_json(path, {}) or {}
            package = (finding.get("package") or {}).get("name")
            affected = set((finding.get("package") or {}).get("versions") or [])
            if not package or versions.get(package) not in affected:
                continue
            confidence = finding.get("confidence")
            if confidence == "confirmed":
                kind = "confirmed-finding"
                weight = WEIGHTS[kind]
            else:
                kind = "high-confidence-finding"
                base = WEIGHTS[kind]
                weight = base if confidence == "high" else max(20, base - 15)
            add_signal(groups, "package", str(package), signal(
                kind,
                f"finding:{finding.get('source') or 'unknown'}",
                weight,
                {
                    "finding_id": finding.get("id"),
                    "severity": finding.get("severity"),
                    "installed_version": versions.get(package),
                    "summary": finding.get("summary"),
                },
                "confirmed" if confidence == "confirmed" else "corroborated",
            ))

    return groups


def reconcile(args) -> dict:
    security_state = Path(args.state_root)
    db_root = Path(args.db_root)
    active_dir = security_state / "incidents" / "active"
    archive_dir = security_state / "incidents" / "archive"
    active_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(active_dir, 0o700)
    os.chmod(archive_dir, 0o700)

    groups = collect_groups(security_state, db_root)
    provenance_baseline = (security_state / "provenance" / "baseline.json").is_file()
    persistence_baseline = (security_state / "persistence" / "baseline.json").is_file()

    current: dict[str, dict] = {}
    for (subject_type, subject_id), signals in groups.items():
        incident = build_incident(
            subject_type,
            subject_id,
            signals,
            args.prevention_mode,
            args.autonomy_level,
            provenance_baseline,
            persistence_baseline,
        )
        current[incident["incident_id"]] = incident

    previous: dict[str, dict] = {}
    for path in active_dir.glob("inc-*.json"):
        data = read_json(path)
        if isinstance(data, dict) and INCIDENT_RE.fullmatch(str(data.get("incident_id", ""))):
            previous[data["incident_id"]] = data

    created = []
    updated = []
    unchanged = []
    resolved = []
    now = now_utc()

    for iid, incident in sorted(current.items()):
        old = previous.get(iid)
        if old is None:
            incident["opened_at"] = now
            incident["updated_at"] = now
            created.append(incident)
        elif old.get("assessment_sha256") != incident.get("assessment_sha256"):
            incident["opened_at"] = old.get("opened_at") or now
            incident["updated_at"] = now
            updated.append(incident)
        else:
            incident["opened_at"] = old.get("opened_at") or now
            incident["updated_at"] = old.get("updated_at") or incident["opened_at"]
            unchanged.append(incident)
        atomic_private(active_dir / f"{iid}.json", (json.dumps(incident, indent=2, sort_keys=True) + "\n").encode())

    for iid, old in sorted(previous.items()):
        if iid in current:
            continue
        old = dict(old)
        old["status"] = "resolved"
        old["resolved_at"] = now
        old["updated_at"] = now
        atomic_private(archive_dir / f"{iid}-{now.replace(':', '').replace('.', '')}.json", (json.dumps(old, indent=2, sort_keys=True) + "\n").encode())
        try:
            (active_dir / f"{iid}.json").unlink()
        except FileNotFoundError:
            pass
        resolved.append(old)

    highest = "info"
    for incident in current.values():
        if RISK_ORDER[incident["risk"]] > RISK_ORDER[highest]:
            highest = incident["risk"]

    return {
        "version": VERSION,
        "kind": "security-incident-reconcile",
        "prevention_mode": args.prevention_mode,
        "autonomy_level": args.autonomy_level,
        "automatic_system_mutation": False,
        "highest_risk": highest,
        "active": len(current),
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "resolved": resolved,
    }


def list_incidents(args) -> list[dict]:
    active_dir = Path(args.state_root) / "incidents" / "active"
    rows = []
    if active_dir.is_dir():
        for path in sorted(active_dir.glob("inc-*.json")):
            data = read_json(path)
            if isinstance(data, dict):
                rows.append(data)
    rows.sort(key=lambda x: (-RISK_ORDER.get(x.get("risk", "info"), 0), -int(x.get("score", 0)), x.get("incident_id", "")))
    return rows


def show_incident(args) -> dict:
    if not INCIDENT_RE.fullmatch(args.incident_id):
        raise SystemExit("invalid incident id")
    path = Path(args.state_root) / "incidents" / "active" / f"{args.incident_id}.json"
    if not path.is_file():
        raise SystemExit(f"active incident does not exist: {args.incident_id}")
    data = read_json(path)
    if not isinstance(data, dict):
        raise SystemExit("invalid incident state")
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="security_incident.py")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("reconcile")
    rec.add_argument("--state-root", required=True)
    rec.add_argument("--db-root", required=True)
    rec.add_argument("--prevention-mode", choices=("off", "shadow"), default="shadow")
    rec.add_argument("--autonomy-level", choices=("observe", "guard", "contain", "recover"), default="guard")

    ls = sub.add_parser("list")
    ls.add_argument("--state-root", required=True)

    show = sub.add_parser("show")
    show.add_argument("incident_id")
    show.add_argument("--state-root", required=True)

    sub.add_parser("doctor")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "reconcile":
        result = reconcile(args)
    elif args.command == "list":
        result = list_incidents(args)
    elif args.command == "show":
        result = show_incident(args)
    elif args.command == "doctor":
        result = {
            "version": VERSION,
            "kind": "security-incident-engine",
            "status": "ok",
            "automatic_system_mutation": False,
            "unit_of_reasoning": "incident",
            "risk_inputs": ["finding", "integrity", "persistence", "runtime", "source-diversity"],
        }
    else:
        raise SystemExit("unknown command")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
