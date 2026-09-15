#!/usr/bin/env python3
from datetime import datetime, timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from guardian_evidence import EvidenceConfidence,EvidenceEnvelope,EvidenceFreshness,FreshnessPolicy,ProviderHealth,missing_evidence

def check(name, cond):
    if not cond: raise AssertionError(name)
    print('PASS',name)
NOW=datetime(2026,9,15,8,0,tzinfo=timezone.utc)
def env(at,health=ProviderHealth.HEALTHY,**kw):
    return EvidenceEnvelope('security.integrity','security',1,at,'pacman-mtree',FreshnessPolicy(600),health,{'result':'clean'},EvidenceConfidence.HIGH,(), 'read-only-observer', **kw)
fresh=env('2026-09-15T07:55:00Z')
check('fresh evidence is current',fresh.freshness(now=NOW) is EvidenceFreshness.CURRENT)
check('current healthy evidence is decision usable',fresh.decision_usable(now=NOW))
stale=env('2026-09-15T06:00:00Z')
check('expired evidence is stale',stale.freshness(now=NOW) is EvidenceFreshness.STALE)
check('stale clean evidence cannot be used as current health',not stale.decision_usable(now=NOW))
failed=env('2026-09-15T07:59:00Z',ProviderHealth.FAILED)
check('failed provider is distinct from stale evidence',failed.freshness(now=NOW) is EvidenceFreshness.FAILED)
unsupported=env(None,supported=False)
check('unsupported capability remains explicit',unsupported.freshness(now=NOW) is EvidenceFreshness.UNSUPPORTED)
na=env(None,applicable=False)
check('not-applicable capability remains explicit',na.freshness(now=NOW) is EvidenceFreshness.NOT_APPLICABLE)
missing=missing_evidence('security.runtime','security',source='procfs',max_age_seconds=60,authority_boundary='read-only-observer')
check('missing evidence never means healthy',missing.freshness(now=NOW) is EvidenceFreshness.MISSING)
check('missing evidence is not decision usable',not missing.decision_usable(now=NOW))
try:
    EvidenceEnvelope('BAD ID','security',1,None,'x',FreshnessPolicy(1),ProviderHealth.UNKNOWN,{},EvidenceConfidence.NONE,(),'x')
    raise AssertionError('bad provider accepted')
except ValueError:
    check('provider identity is validated',True)
print('ALL GUARDIAN EVIDENCE TESTS PASS')
