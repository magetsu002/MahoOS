#!/usr/bin/env python3
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from guardian_journal_stream import CursorProbe,StreamContinuity,begin_stream,mark_dropped,mark_event,mark_failed
from guardian_service_watcher import _classify_cursor_probe

def check(name,condition):
    if not condition: raise AssertionError(name)
    print('PASS',name)

NOW=datetime(2026,9,15,8,0,tzinfo=timezone.utc)
BOOT='a'*32
first=begin_stream(None,cursor='cursor-a',probe=CursorProbe.VALID,boot_id=BOOT,now=NOW)
check('valid startup cursor establishes continuity',first.continuity is StreamContinuity.CONTINUOUS and first.continuity_verified_at is not None)
resumed=begin_stream(first,cursor='cursor-a',probe=CursorProbe.VALID,boot_id=BOOT,now=NOW+timedelta(minutes=1))
check('watcher restart with continuous cursor is proven',resumed.continuity is StreamContinuity.CONTINUOUS and resumed.restart_count==1 and resumed.previous_cursor=='cursor-a')
missing=begin_stream(first,cursor=None,probe=CursorProbe.MISSING,boot_id=BOOT,now=NOW+timedelta(minutes=1))
check('watcher restart with missing cursor loses continuity',missing.continuity is StreamContinuity.LOST and missing.reason=='cursor_missing_after_previous_stream')
invalid=begin_stream(first,cursor='cursor-a',probe=CursorProbe.INVALID,boot_id=BOOT,now=NOW+timedelta(minutes=1))
check('invalid cursor loses continuity',invalid.continuity is StreamContinuity.LOST and invalid.reason=='cursor_invalid_or_expired')
failed=begin_stream(first,cursor='cursor-a',probe=CursorProbe.SOURCE_FAILED,boot_id=BOOT,now=NOW+timedelta(minutes=1))
check('journal source failure is explicit',failed.continuity is StreamContinuity.FAILED)
lost=mark_dropped(resumed,count=2,reason='journal_records_unparseable')
check('lost event accounting destroys continuity',lost.continuity is StreamContinuity.LOST and lost.dropped_events==2)
missing_event=mark_event(resumed,cursor=None,now=NOW+timedelta(minutes=2))
check('event without cursor is counted as potentially missed',missing_event.continuity is StreamContinuity.LOST and missing_event.dropped_events==1)
check('probe classifier accepts valid resume',_classify_cursor_probe('cursor-a',returncode=0) is CursorProbe.VALID)
check('probe classifier treats cursor seek error as invalid',_classify_cursor_probe('cursor-a',returncode=1,stderr='Failed to seek to cursor') is CursorProbe.INVALID)
check('probe classifier treats source execution error as source failure',_classify_cursor_probe('cursor-a',source_error=True) is CursorProbe.SOURCE_FAILED)
check('explicit stream failure remains failed',mark_failed(resumed,reason='event_source_eof').continuity is StreamContinuity.FAILED)
print('ALL GUARDIAN JOURNAL STREAM TESTS PASS')
