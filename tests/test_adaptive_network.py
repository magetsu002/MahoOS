#!/usr/bin/env python3
from datetime import datetime,timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from maho_adaptive_network import network_proposals
from maho_adaptive_situation import build_situation
NOW=datetime(2026,9,12,tzinfo=timezone.utc);F="2026-09-11T23:59:30Z"
def snap(connectivity="online",stability="stable",route=True,reachable=True,at=F):
 return build_situation({"network":{"observed_at":at,"data":{"connectivity":connectivity,"stability":stability,"default_route":route,"reachable":reachable}},"user_intent":{"observed_at":F,"data":{"adaptation_opt_outs":[]}}},captured_at=NOW)
def fx(ps):return {(e.key,e.value) for p in ps for e in p.requested_effects}
def main():
 assert network_proposals(snap(),created_at=NOW)==()
 absent=network_proposals(snap("offline","unstable",False,False),created_at=NOW)
 assert {("network_background","suspended"),("update_downloads","deferred")}<=fx(absent)
 unstable=network_proposals(snap("online","unstable",True,True),created_at=NOW)
 assert {("network_background","reduced"),("update_downloads","deferred"),("foreground_network","preserve")}<=fx(unstable)
 forbidden={"vpn","tor","firewall","reconnect"}
 assert all(e.key not in forbidden for p in absent+unstable for e in p.requested_effects)
 assert network_proposals(snap(at="2026-09-11T23:40:00Z"),created_at=NOW)==()
 print("ALL ADAPTIVE NETWORK TESTS PASS")
if __name__=="__main__":main()
