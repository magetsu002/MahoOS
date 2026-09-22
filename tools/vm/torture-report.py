#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

OUTCOMES=("PREVENTED","RECOVERED_AUTOMATICALLY","RECOVERED_WITH_AUTHORITY","DETECTED_ONLY","NOT_COVERED","BUG")

def command(*argv: str) -> str:
    return subprocess.run(argv,check=False,capture_output=True,text=True).stdout.strip()

def digest_tree(path: Path) -> str:
    h=hashlib.sha256()
    if not path.exists(): return "absent"
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        try: data=item.read_bytes()
        except OSError: continue
        h.update(str(item.relative_to(path)).encode()+b"\0"+hashlib.sha256(data).digest())
    return h.hexdigest()

def snapshot(repo: Path, output: Path) -> None:
    services={}
    raw=command("systemctl","list-units","--type=service","--all","--no-legend","--plain")
    for line in raw.splitlines():
        unit=line.split(maxsplit=1)[0] if line.split() else ""
        if unit.startswith("maho-"):
            services[unit]={"active":command("systemctl","is-active",unit),"invocation_id":command("systemctl","show",unit,"-p","InvocationID","--value")}
    payload={"schema_version":1,"captured_at":datetime.now(timezone.utc).isoformat(),"host_boot_id":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"host_root_source":command("findmnt","-n","-o","SOURCE","/"),"source_revision":command("git","-C",str(repo),"rev-parse","HEAD"),"source_status":command("git","-C",str(repo),"status","--porcelain","--untracked-files=normal"),"prevention_state_sha256":digest_tree(Path("/var/lib/maho/prevention")),"maho_system_services":services}
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")

def load_rows(campaign: Path) -> list[dict]:
    rows=[]
    for path in sorted((campaign/"profiles").glob("*/scenarios/*/iteration-*/summary.json")):
        try: row=json.loads(path.read_text())
        except Exception: continue
        if isinstance(row,dict): rows.append(row)
    return rows

def report(repo: Path, campaign: Path, revision: str) -> int:
    rows=load_rows(campaign); counts=Counter(str(r.get("actual_outcome")) for r in rows)
    before=json.loads((campaign/"host-before.json").read_text()); after=json.loads((campaign/"host-after.json").read_text())
    host_checks={"boot_id_unchanged":before["host_boot_id"]==after["host_boot_id"],"root_source_unchanged":before["host_root_source"]==after["host_root_source"],"source_revision_unchanged":before["source_revision"]==after["source_revision"]==revision,"source_clean_after_campaign":after["source_status"]=="","prevention_state_unchanged":before["prevention_state_sha256"]==after["prevention_state_sha256"],"maho_services_unchanged":before["maho_system_services"]==after["maho_system_services"]}
    passed=bool(rows) and all(bool(r.get("pass")) for r in rows) and all(host_checks.values())
    payload={"schema_version":1,"kind":"maho-v1-full-system-torture-report","generated_at":datetime.now(timezone.utc).isoformat(),"starting_sha":revision,"ending_sha":command("git","-C",str(repo),"rev-parse","HEAD"),"campaign_path":str(campaign),"total_scenarios":len(rows),"total_iterations":len(rows),"total_destructive_injections":sum(1 for r in rows if r.get("actual_outcome") not in {"NOT_COVERED"}),"outcomes":{name:counts.get(name,0) for name in OUTCOMES},"host_safety":host_checks,"passed":passed,"scenarios":rows}
    date=datetime.now(timezone.utc).date().isoformat(); reports=repo/"docs"/"reports"; reports.mkdir(parents=True,exist_ok=True)
    json_path=reports/f"v1-full-system-torture-{date}.json"; md_path=reports/f"v1-full-system-torture-{date}.md"
    json_path.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    lines=["# MahoOS V1 full-system torture report","",f"- Source: `{revision}`",f"- Campaign evidence: `{campaign}`",f"- Verdict: **{'PASS' if passed else 'INCOMPLETE / FAIL'}**",f"- Scenarios/iterations: {len(rows)}",""]
    lines += ["## Outcomes",""]+[f"- {name}: {counts.get(name,0)}" for name in OUTCOMES]
    lines += ["","## Scenario matrix","","| Scenario | Iteration | Expected | Actual | Pass |","|---|---:|---|---|---|"]
    for r in rows: lines.append(f"| {r.get('scenario')} | {r.get('iteration')} | {r.get('expected_outcome')} | {r.get('actual_outcome')} | {r.get('pass')} |")
    lines += ["","## Host safety",""]+[f"- {key}: {value}" for key,value in host_checks.items()]
    lines += ["","## Brutally clear V1 boundary",""]
    for outcome,title in (("PREVENTED","PREVENT"),("RECOVERED_AUTOMATICALLY","RECOVER AUTOMATICALLY"),("RECOVERED_WITH_AUTHORITY","RECOVER WITH AUTHORITY"),("DETECTED_ONLY","DETECT BUT NOT RECOVER"),("NOT_COVERED","OUTSIDE V1"),("BUG","BUG")):
        names=sorted({str(r.get("scenario")) for r in rows if r.get("actual_outcome")==outcome})
        lines += [f"### {title}",""]+([f"- {name}" for name in names] or ["- None demonstrated."])+[""]
    lines += ["This report deliberately makes no claim for a scenario absent from the matrix. A command exit code was never accepted as recovery without the scenario's independent postcondition checks.",""]
    md_path.write_text("\n".join(lines))
    print(json.dumps({"passed":passed,"json":str(json_path),"markdown":str(md_path),"scenarios":len(rows)},sort_keys=True))
    return 0 if passed else 1

def main() -> int:
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="command",required=True)
    snap=sub.add_parser("snapshot"); snap.add_argument("--repo",type=Path,required=True); snap.add_argument("--output",type=Path,required=True)
    rep=sub.add_parser("report"); rep.add_argument("--repo",type=Path,required=True); rep.add_argument("--campaign",type=Path,required=True); rep.add_argument("--revision",required=True)
    args=parser.parse_args()
    if args.command=="snapshot": snapshot(args.repo,args.output); return 0
    return report(args.repo,args.campaign,args.revision)

if __name__=="__main__": raise SystemExit(main())
