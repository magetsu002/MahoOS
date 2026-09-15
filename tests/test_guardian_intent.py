#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from guardian_intent import AuthorizedOperation,ChangeExpectation,ChangeObservation,CorrelationStatus,OperationKind,OperationState,correlate_change

def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print('PASS',name)

def op(identity='upd-1',authority='update-authority',verified=True,start='2026-09-15T08:00:00Z',end='2026-09-15T08:10:00Z',subject=None):
    bounded = subject if subject is not None else '/usr/lib/maho/' + chr(42)
    return AuthorizedOperation(identity,OperationKind.MAHO_UPDATE,OperationState.ACTIVE,authority,verified,start,end,(ChangeExpectation('file-change',bounded),),'update-journal')

change=ChangeObservation('file-change','/usr/lib/maho/x','2026-09-15T08:05:00Z','integrity')
r=correlate_change(change,[op()])
check('exact bounded verified intent correlates',r.status is CorrelationStatus.AUTHORIZED_EXPECTED and r.suppress_escalation)
check('only exact verified intent suppresses escalation',r.suppress_escalation)
unrelated=ChangeObservation('file-change','/etc/passwd','2026-09-15T08:05:00Z','integrity')
check('unrelated drift is never hidden by maintenance',not correlate_change(unrelated,[op()]).suppress_escalation)
outside=ChangeObservation('file-change','/usr/lib/maho/x','2026-09-15T09:00:00Z','integrity')
check('expected shape outside authority window remains visible',correlate_change(outside,[op()]).status is CorrelationStatus.OUTSIDE_WINDOW)
check('self-declared intent cannot suppress',correlate_change(change,[op(verified=False)]).status is CorrelationStatus.UNVERIFIED_AUTHORITY)
amb=correlate_change(change,[op('a','authority-a'),op('b','authority-b')])
check('competing verified authorities fail closed',amb.status is CorrelationStatus.AMBIGUOUS and not amb.suppress_escalation)
try:
    ChangeExpectation('file-change',chr(42))
    raise AssertionError('unbounded wildcard accepted')
except ValueError:
    check('unbounded wildcard expectations are refused',True)
print('ALL GUARDIAN INTENT TESTS PASS')
