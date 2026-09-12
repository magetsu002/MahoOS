#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from maho_adaptive_battery import assess_battery,battery_proposals
from maho_adaptive_situation import build_situation

NOW=datetime(2026,9,12,0,0,tzinfo=timezone.utc)
FRESH="2026-09-11T23:59:30Z"
def env(d,at=FRESH): return {"observed_at":at,"data":d}
def snap(percent=30,ac=False,*,game=False,performance=False,at=FRESH,opt=()):
    return build_situation({
      "power":env({"percentage":percent,"battery_present":True,"ac_online":ac,"charging_state":"charging" if ac else "discharging","drain_trend":"falling" if not ac else "stable","ac_stable_seconds":60 if ac else 600},at),
      "workload":env({"probable_gaming":game,"interactive":game,"confidence":.95}),
      "user_intent":env({"power_mode":"performance" if performance else "balanced","foreground_performance":performance,"adaptation_opt_outs":list(opt)}),
    },captured_at=NOW)
def effects(ps): return {(e.key,e.value) for p in ps for e in p.requested_effects}

def main():
    assert assess_battery(snap(80)).band=="NORMAL"
    low=battery_proposals(snap(30),created_at=NOW)
    assert ("maintenance","suspended") in effects(low) and ("background_work","reduced") in effects(low)
    assert all(p.disruption_class in {"A","B"} for p in low)
    conserving=battery_proposals(snap(15),created_at=NOW)
    assert ("power_survival","conserve") in effects(conserving)
    game=battery_proposals(snap(15,game=True,performance=True),created_at=NOW)
    assert ("foreground_performance","preserve") in effects(game)
    assert ("maintenance","suspended") in effects(game)
    critical=battery_proposals(snap(5),created_at=NOW)
    assert any(p.disruption_class=="D" for p in critical)
    review=next(p for p in critical if p.disruption_class=="D")
    assert not review.automatic_execution_eligible and review.requires_human_review
    assert ("power_action","suspend-review") in effects(critical)
    plugged=battery_proposals(snap(5,ac=True),created_at=NOW)
    assert plugged==()
    flapping=build_situation({"power":env({"percentage":5,"battery_present":True,"ac_online":True,"charging_state":"charging","ac_stable_seconds":2})},captured_at=NOW)
    assert assess_battery(flapping).band=="UNKNOWN" and battery_proposals(flapping,created_at=NOW)==()
    stale=battery_proposals(snap(5,at="2026-09-11T23:40:00Z"),created_at=NOW)
    assert stale==()
    assert assess_battery(snap(5,at="2026-09-11T23:40:00Z")).band=="UNKNOWN"
    assert battery_proposals(snap(10,opt=("battery",)),created_at=NOW)==()
    print("ALL ADAPTIVE BATTERY TESTS PASS")
if __name__=="__main__": main()
