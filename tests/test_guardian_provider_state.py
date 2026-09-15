#!/usr/bin/env python3
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from guardian_evidence import ProviderHealth
from guardian_provider_state import load_heartbeat,record_heartbeat

def check(name,condition):
    if not condition: raise AssertionError(name)
    print('PASS',name)

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    t0=datetime(2026,9,15,8,0,tzinfo=timezone.utc)
    first=record_heartbeat(root,provider_id='security.integrity',domain='security',source='pacman-mtree',authority_boundary='read-only-observer',success=True,health=ProviderHealth.HEALTHY,details={'result':'clean'},now=t0)
    check('successful observation records durable success time',first.last_success_at==first.last_attempt_at and first.sequence==1)
    failed=record_heartbeat(root,provider_id='security.integrity',domain='security',source='pacman-mtree',authority_boundary='read-only-observer',success=False,health=ProviderHealth.FAILED,errors=('scan_failed',),now=t0+timedelta(minutes=1))
    check('failed attempt does not fake freshness',failed.last_success_at==first.last_success_at and failed.last_attempt_at!=first.last_attempt_at)
    loaded=load_heartbeat(root,'security.integrity')
    check('heartbeat survives observer restart',loaded is not None and loaded.sequence==2 and loaded.last_success_at==first.last_success_at)
    recovered=record_heartbeat(root,provider_id='security.integrity',domain='security',source='pacman-mtree',authority_boundary='read-only-observer',success=True,health=ProviderHealth.HEALTHY,details={'result':'clean'},now=t0+timedelta(minutes=2))
    check('provider recovery advances successful observation time',recovered.last_success_at==recovered.last_attempt_at and recovered.sequence==3)
    path=root/'guardian/providers/security.integrity.json'
    payload=json.loads(path.read_text()); payload['health']='invented'; path.write_text(json.dumps(payload))
    try:
        load_heartbeat(root,'security.integrity')
        raise AssertionError('malformed heartbeat accepted')
    except ValueError:
        check('malformed provider heartbeat fails closed',True)

print('ALL GUARDIAN PROVIDER STATE TESTS PASS')
