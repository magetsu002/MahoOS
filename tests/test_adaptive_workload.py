#!/usr/bin/env python3
from datetime import datetime,timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'lib'))
from maho_adaptive_situation import build_situation
from maho_adaptive_workload import workload_proposals
NOW=datetime(2026,9,12,tzinfo=timezone.utc); F="2026-09-11T23:59:30Z"
def snap(**w):
 base={"confidence":.95,"evidence":["multi-signal"],"probable_gaming":False,"probable_compile":False,"probable_rendering":False,"probable_media":False,"interactive":False,"fullscreen":False}; base.update(w)
 return build_situation({"workload":{"observed_at":F,"data":base},"user_intent":{"observed_at":F,"data":{"adaptation_opt_outs":[]}}},captured_at=NOW)
def fx(ps): return {(e.key,e.value) for p in ps for e in p.requested_effects}
def main():
 game=workload_proposals(snap(probable_gaming=True,interactive=True,fullscreen=True),created_at=NOW)
 assert {("maintenance","suspended"),("notifications","quiet"),("background_work","reduced"),("foreground_performance","preserve")}<=fx(game)
 # Gaming preservation never asks for max CPU/GPU or hardware power limits.
 assert all(e.key not in {"performance_mode","power_action"} for p in game for e in p.requested_effects)
 compile_locked=workload_proposals(snap(probable_compile=True),created_at=NOW)
 assert ("maintenance","suspended") in fx(compile_locked)
 render=workload_proposals(snap(probable_rendering=True),created_at=NOW)
 assert ("maintenance","suspended") in fx(render)
 media=workload_proposals(snap(probable_media=True,fullscreen=True),created_at=NOW)
 assert ("notifications","quiet") in fx(media) and ("foreground_performance","preserve") not in fx(media)
 assert all("gaming" not in p.source_policy for p in media)
 low=workload_proposals(snap(confidence=.4,probable_gaming=True,interactive=True),created_at=NOW); assert low==()
 print("ALL ADAPTIVE WORKLOAD POLICY TESTS PASS")
if __name__=="__main__": main()
