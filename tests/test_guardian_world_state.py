#!/usr/bin/env python3
from datetime import datetime,timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from guardian_evidence import EvidenceConfidence,EvidenceEnvelope,FreshnessPolicy,ProviderHealth
from guardian_world_state import GuardianSelfFacts,GuardianSelfHealthState,GuardianTrustState,TrustSignal,build_world_state

def check(name,cond):
    if not cond:
        raise AssertionError(name)
    print('PASS',name)

NOW=datetime(2026,9,15,8,0,tzinfo=timezone.utc)
def ev(pid,at='2026-09-15T07:59:30Z',health=ProviderHealth.HEALTHY):
    return EvidenceEnvelope(pid,'security',1,at,pid,FreshnessPolicy(120),health,{'result':'clean'},EvidenceConfidence.HIGH,(),'read-only-observer')

facts=GuardianSelfFacts(True,True,True,True,True,True,True,True,True,True,0)
trust=(TrustSignal('integrity-trust',GuardianTrustState.VERIFIED,'current integrity evidence verified'),)
world=build_world_state([ev('security.integrity')],required_provider_ids=['security.integrity'],self_facts=facts,trust_signals=trust,now=NOW)
check('fresh complete evidence yields healthy Guardian',world.self_health.state is GuardianSelfHealthState.HEALTHY)
check('verified trust remains separate from L0 severity',world.trust.state is GuardianTrustState.VERIFIED and world.severity['level']==0)
boot_missing=build_world_state(
    [ev('security.integrity')],
    required_provider_ids=['security.integrity'],
    self_facts=facts,
    trust_signals=(
        TrustSignal('system.generation',GuardianTrustState.UNKNOWN,'generation authority unavailable'),
        TrustSignal('boot.authority',GuardianTrustState.UNKNOWN,'Signed Boot proof missing'),
        TrustSignal('maho.runtime',GuardianTrustState.VERIFIED,'runtime verified'),
    ),
    now=NOW,
)
check('missing boot proof does not poison Guardian self-health',boot_missing.self_health.state is GuardianSelfHealthState.HEALTHY)
check('missing boot proof keeps machine trust unknown',boot_missing.trust.state is GuardianTrustState.UNKNOWN)
stale=build_world_state([ev('security.integrity','2026-09-15T07:00:00Z')],required_provider_ids=['security.integrity'],self_facts=facts,trust_signals=trust,now=NOW)
check('stale required observer degrades Guardian self-health',stale.self_health.state is GuardianSelfHealthState.DEGRADED)
check('degraded visibility downgrades trust without inventing severity',stale.trust.state is GuardianTrustState.DEGRADED and stale.severity['level']==0)
missing=build_world_state([],required_provider_ids=['security.integrity'],self_facts=facts,trust_signals=trust,now=NOW)
check('missing required observer makes decision visibility unknown',missing.self_health.state is GuardianSelfHealthState.UNKNOWN)
check('missing visibility makes trust unknown',missing.trust.state is GuardianTrustState.UNKNOWN)
unknown=build_world_state([ev('security.integrity',health=ProviderHealth.UNKNOWN)],required_provider_ids=['security.integrity'],self_facts=facts,trust_signals=trust,now=NOW)
check('unknown required provider health is not healthy',unknown.self_health.state is GuardianSelfHealthState.UNKNOWN)
degraded=build_world_state([ev('security.integrity',health=ProviderHealth.DEGRADED)],required_provider_ids=['security.integrity'],self_facts=facts,trust_signals=trust,now=NOW)
check('degraded required provider is represented explicitly',degraded.self_health.state is GuardianSelfHealthState.DEGRADED)
untrusted_facts=GuardianSelfFacts(True,True,True,True,False,True,True,True,True,True,0)
untrusted=build_world_state([ev('security.integrity')],required_provider_ids=['security.integrity'],self_facts=untrusted_facts,trust_signals=trust,now=NOW)
check('failed Guardian runtime identity makes Guardian untrusted',untrusted.self_health.state is GuardianSelfHealthState.UNTRUSTED)
check('untrusted Guardian self-health dominates trust',untrusted.trust.state is GuardianTrustState.UNTRUSTED)
l2=build_world_state([ev('security.integrity')],required_provider_ids=['security.integrity'],self_facts=facts,trust_signals=trust,severity={'level':2,'label':'component'},now=NOW)
check('trusted component failure may be L2 without integrity loss',l2.trust.state is GuardianTrustState.VERIFIED and l2.severity['level']==2)
payload=world.as_dict()
check('world state retains provider provenance',payload['domains']['security'][0]['source']=='security.integrity')
check('world state exposes freshness',payload['domains']['security'][0]['freshness']=='current')
print('ALL GUARDIAN WORLD STATE TESTS PASS')
