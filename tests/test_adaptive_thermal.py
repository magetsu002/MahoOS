#!/usr/bin/env python3
from datetime import datetime,timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'lib'))
from maho_adaptive_situation import build_situation
from maho_adaptive_thermal import thermal_proposals
NOW=datetime(2026,9,12,tzinfo=timezone.utc); FRESH="2026-09-11T23:59:30Z"
def snap(temp,dwell,trend="stable",at=FRESH):
 return build_situation({"thermal":{"observed_at":at,"data":{"max_millidegree_c":temp,"sustained_seconds":dwell,"trend":trend}},"user_intent":{"observed_at":FRESH,"data":{"adaptation_opt_outs":[]}}},captured_at=NOW)
def fx(ps): return {(e.key,e.value) for p in ps for e in p.requested_effects}
def main():
 assert thermal_proposals(snap(70000,999),created_at=NOW)==()
 assert thermal_proposals(snap(86000,10),created_at=NOW)==()
 hot=thermal_proposals(snap(86000,61,"rising"),created_at=NOW)
 assert len(hot)==1 and ("maintenance","suspended") in fx(hot) and ("background_work","reduced") in fx(hot)
 # Oscillation near the hot entry boundary does not produce a proposal until dwell is satisfied.
 for temp,dwell in [(84900,100),(85100,3),(84800,200),(85200,59)]:
  assert thermal_proposals(snap(temp,dwell),created_at=NOW)==()
 critical_short=thermal_proposals(snap(96000,5),created_at=NOW); assert critical_short==()
 critical=thermal_proposals(snap(96000,30,"rising"),created_at=NOW)
 assert ("background_work","suspended") in fx(critical)
 assert any(p.disruption_class=="C" and p.requires_human_review for p in critical)
 assert all(not p.automatic_execution_eligible for p in critical)
 assert thermal_proposals(snap(96000,100,at="2026-09-11T23:40:00Z"),created_at=NOW)==()
 print("ALL ADAPTIVE THERMAL TESTS PASS")
if __name__=="__main__": main()
