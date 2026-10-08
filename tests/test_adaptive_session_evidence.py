#!/usr/bin/env python3
"""Session evidence comes from logind and never spans an observation gap."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import maho_adaptive_observers as observers
import maho_adaptive_shadow as shadow
from test_adaptive_shadow import T0, fixture
from maho_adaptive_situation import build_situation


class SessionEvidenceContracts(unittest.TestCase):
    def properties(self, **changes):
        return {'User':str(os.getuid()), 'Class':'user', 'Type':'wayland',
                'Active':'yes', 'Remote':'no', 'LockedHint':'yes',
                'IdleHint':'yes', 'IdleSinceHintMonotonic':'100000000', **changes}

    def query(self, sessions):
        def run(command, **kwargs):
            if command[1] == 'show-user':
                data = {'Sessions':' '.join(sessions)}
            else:
                data = sessions[command[2]]
            return subprocess.CompletedProcess(command, 0, '\n'.join(f'{k}={v}' for k,v in data.items()))
        return run

    def test_user_service_resolves_its_real_graphical_session_without_env(self):
        sessions = {'1':self.properties(Class='manager', Type='unspecified'), '3':self.properties()}
        with patch.dict(os.environ, {}, clear=True), patch.object(observers.subprocess, 'run', side_effect=self.query(sessions)):
            self.assertEqual(observers._loginctl_properties(), self.properties())

    def test_ambiguous_remote_inactive_wrong_uid_and_failed_queries_stay_unknown(self):
        cases = [
            {'3':self.properties(), '4':self.properties()},
            {'3':self.properties(Remote='yes')},
            {'3':self.properties(Active='no')},
            {'3':self.properties(User='999999')},
            {'1':self.properties(Class='manager', Type='unspecified')},
        ]
        for sessions in cases:
            with self.subTest(sessions=sessions), patch.object(observers.subprocess,'run',side_effect=self.query(sessions)):
                self.assertEqual(observers._loginctl_properties(), {})
        with patch.object(observers.subprocess,'run',side_effect=subprocess.TimeoutExpired('loginctl',1)):
            self.assertEqual(observers._loginctl_properties(), {})

    def test_idle_hint_must_agree_with_valid_monotonic_timestamp(self):
        for hint, since, expected in [('yes','100000000',100.0), ('no','100000000',0.0),
                                      ('yes','300000000','unknown'), ('yes','0','unknown'),
                                      ('unknown','100000000','unknown')]:
            with self.subTest(hint=hint,since=since), patch.object(observers,'_loginctl_properties',return_value=self.properties(IdleHint=hint,IdleSinceHintMonotonic=since)), patch.object(observers.time,'monotonic',return_value=200.0):
                evidence,_ = observers.collect_session()
                self.assertEqual(evidence.idle_seconds,expected)

    def test_lock_observation_gap_resets_monotonic_and_persisted_dwell(self):
        with patch.object(observers,'_loginctl_properties',return_value={}):
            evidence,start=observers.collect_session(previous_lock_started_monotonic=1.0)
            self.assertEqual(evidence.locked,'unknown')
            self.assertIsNone(start)
        tracker={}
        shadow.apply_dwell(fixture(locked=True),tracker,T0)
        unknown=fixture(locked=True); unknown['session']['data']['locked']='unknown'
        shadow.apply_dwell(unknown,tracker,T0+timedelta(minutes=30))
        resumed=fixture(locked=True)
        shadow.apply_dwell(resumed,tracker,T0+timedelta(minutes=40))
        self.assertEqual(resumed['session']['data']['lock_dwell_seconds'],0)

    def test_wayland_idle_and_secure_lock_use_real_protocol_acknowledgement(self):
        def evidence(component, function):
            if component == 'maho-lock':
                return {"secure":True,"locked":True}
            return {"observed":True,"idle":True,"idle_seconds":1201,"respects_inhibitors":True}
        with patch.object(observers,'_loginctl_properties',return_value=self.properties(LockedHint='no',IdleHint='no')), patch.object(observers,'_wayland_session_evidence',side_effect=evidence):
            observed,_=observers.collect_session()
            self.assertTrue(observed.locked)
            self.assertEqual(observed.idle_seconds,1201)
        with patch.object(observers,'_loginctl_properties',return_value=self.properties(LockedHint='no',IdleHint='no')), patch.object(observers,'_wayland_session_evidence',return_value={"secure":False,"locked":True,"observed":False,"idle_seconds":99999}):
            observed,_=observers.collect_session()
            self.assertFalse(observed.locked)
            self.assertEqual(observed.idle_seconds,0)
        with patch.object(observers,'_loginctl_properties',return_value={}), patch.object(observers,'_wayland_session_evidence',side_effect=evidence):
            observed,_=observers.collect_session()
            self.assertEqual(observed.locked,'unknown')
            self.assertEqual(observed.idle_seconds,'unknown')

    def test_compositor_inhibition_blocks_even_when_user_is_idle(self):
        data={"observed":True,"idle":True,"idle_seconds":1500,"respects_inhibitors":True,"idle_inhibited":True}
        with patch.object(observers,'_loginctl_properties',return_value=self.properties()), patch.object(observers,'_wayland_session_evidence',return_value=data), patch.object(observers,'_session_inhibitors',return_value=()):
            observed,_=observers.collect_session()
            self.assertEqual(observed.idle_seconds,1500)
            self.assertEqual(observed.inhibitors,('wayland-idle-inhibitor',))

    def test_inhibitors_are_observed_and_missing_evidence_blocks(self):
        rows = [["sleep","UPower","polling","delay",0,10],
                ["idle","player","playback","block",1000,11],
                ["shutdown","backup","writing","block",1000,12]]
        with patch.object(observers,'_run_json',return_value={"type":"a(ssssuu)","data":[rows]}):
            self.assertEqual(len(observers._session_inhibitors()),2)
        with patch.object(observers,'_run_json',return_value={}):
            self.assertEqual(observers._session_inhibitors(),('logind-inhibitors-unknown',))

    def test_summary_preserves_canonical_reliability_for_coordinator(self):
        summary=shadow.situation_summary(build_situation(fixture(),captured_at=T0))
        self.assertIs(summary['guardian']['unresolved_reliability'],False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
