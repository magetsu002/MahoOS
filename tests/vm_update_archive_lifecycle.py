#!/usr/bin/env python3
"""Real root-owned scratch files/process interruption; disposable VM only."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'lib'), str(ROOT/'tests')]
from test_update_archive_lifecycle import ArchiveLifecycleTests, REV, OLD, ACTIVE, NOW
from maho_update_artifact_lifecycle import UpdateArchiveLifecycle
from maho_generation_gc import SimulatedCrash
from guardian_reliability_provider import storage_facts
from guardian_reliability import assess_observation, ReliabilityObservation
from maho_adaptive_integrations import guardian_proposals
from maho_adaptive_situation import build_situation

if os.environ.get('MAHO_DISPOSABLE_VM_TEST') != '1' or os.getuid() != 0:
    raise SystemExit('This integration requires explicit disposable VM test scope and guest root.')
if not Path('/sys/class/dmi/id/product_name').read_text().strip().startswith(('Standard PC', 'QEMU')):
    raise SystemExit('Refusing non-disposable-machine boundary.')


class RealVMArchiveTests(ArchiveLifecycleTests):
    def test_real_process_death_and_new_executor_resume(self):
        for fault in ('after_prepare', 'after_retire', 'after_unlink', 'after_first_delete'):
            with self.subTest(fault=fault):
                self.setUp()
                plan = self.plan()
                pid = os.fork()
                if pid == 0:
                    try:
                        self.execute(plan, fault_at=fault)
                    except SimulatedCrash:
                        os.kill(os.getpid(), signal.SIGKILL)
                    os._exit(99)
                _, status = os.waitpid(pid, 0)
                self.assertTrue(os.WIFSIGNALED(status))
                self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
                replacement = UpdateArchiveLifecycle(update_root=self.state, generation_root=self.generations,
                    guardian_active=self.guardian, guardian_uid=0, roots={'auto':self.cache})
                result = replacement.executor.resume_files(
                    validate_protections=replacement.validate_protections, now=NOW)
                self.assertEqual(result['phase'], 'COMMITTED')
                self.assertTrue((self.cache/ACTIVE/'staging/demo-2-1-any.pkg.tar.zst').exists())
                self.assertFalse((self.cache/OLD/'staging/demo-2-1-any.pkg.tar.zst').exists())

    def test_real_download_owner_handoff_only_adopts_invalidated_staging(self):
        import pwd
        downloader = pwd.getpwnam('alpm').pw_uid
        retired = self.cache/OLD/'staging'
        active = self.cache/ACTIVE/'staging'
        os.chown(retired, downloader, downloader)
        os.chown(active, downloader, downloader)
        proposal = self.lifecycle.report(source_revision=REV, now=NOW, adoption_uid=downloader)
        self.assertIsNone(proposal["plan"])
        self.assertIs(proposal["proposal"]["execution_authorized"], False)
        self.assertEqual(retired.stat().st_uid, downloader)
        sealed = self.lifecycle.seal_retired(download_uid=downloader)
        self.assertEqual(sealed, ['auto:'+OLD])
        self.assertEqual(retired.stat().st_uid, 0)
        self.assertEqual(active.stat().st_uid, downloader)
        receipt = self.lifecycle.collect(source_revision=REV, now=NOW)
        self.assertEqual(receipt['phase'], 'COMMITTED')
        self.assertTrue((active/'demo-2-1-any.pkg.tar.zst').exists())

    def test_real_low_disk_provider_and_fresh_guardian_veto_convergence(self):
        # Only guest tmpfs, never a physical block device or the host root.
        mount = self.base/'pressure'
        mount.mkdir()
        subprocess.run(['mount','-t','tmpfs','-o','size=64M','tmpfs',str(mount)], check=True)
        try:
            pressure = mount/'pressure.bin'
            with pressure.open('wb') as stream:
                for _ in range(61): stream.write(b'x'*1024**2)
                stream.flush(); os.fsync(stream.fileno())
            full = storage_facts(mount)
            self.assertGreater(full['used_percent'], 90)
            degraded = assess_observation(ReliabilityObservation(
                'reliability.storage','storage',str(mount),'current','healthy',full))
            self.assertEqual(degraded.state.value, 'degraded')
            def proposals(unresolved, freshness=0):
                now = datetime.now(timezone.utc)
                data = {'guardian': {'observed_at': (now-timedelta(seconds=freshness)).isoformat(),
                    'data': {'active_incident':True,'severity_level':1,
                             'recovery_in_progress':False,'unresolved_reliability':unresolved}}}
                return guardian_proposals(build_situation(data,captured_at=now),created_at=now)
            self.assertEqual(proposals(True)[0].source_policy, 'guardian.reliability-state')
            # Existing diagnostic L1 remains, and certified archives can retire
            # without requesting or clearing package-maintenance authority.
            self.assertEqual(self.lifecycle.collect(source_revision=REV, now=NOW)['phase'], 'COMMITTED')
            pressure.unlink()
            os.sync()
            recovered = storage_facts(mount)
            healthy = assess_observation(ReliabilityObservation(
                'reliability.storage','storage',str(mount),'current','healthy',recovered))
            self.assertEqual(healthy.state.value, 'healthy')
            self.assertEqual(proposals(False), ())
            stale = assess_observation(ReliabilityObservation(
                'reliability.storage','storage',str(mount),'stale','healthy',recovered))
            self.assertEqual(stale.state.value, 'unknown')
            self.assertEqual(proposals(False, freshness=600), ())
            self.assertTrue((self.cache/ACTIVE/'staging/demo-2-1-any.pkg.tar.zst').exists())
        finally:
            subprocess.run(['umount',str(mount)], check=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
