#!/usr/bin/env python3
from pathlib import Path
import copy,hashlib,json,subprocess,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from maho_update_normal_host import NormalProductionOps
from maho_update_effects import classify_artifact,repository_provenance
from maho_update_state import create_transaction

class Probe(NormalProductionOps):
    def __init__(self,cache,*,fault=None):
        names=['ordinary','library','certificates']
        tx=create_transaction(transaction_id='upd-20261008T150000Z-123456abcdef',source_revision='a'*40,
            packages=[dict(name=n,installed_version='1',candidate_version='2',repository='extra',download_size=1,installed_size=1,roles=[]) for n in names],
            activation_requirements=[],recovery_generation_id=None,
            selection={'kind':'independent-normal','deferred_boot_packages':['linux'],'solver_proof':{'kind':'fixture'}})
        super().__init__(transaction=tx,cache_root=cache,btrfs=None,candidate={})
        self.fault=fault;self.commands=[]
        self.paths={'ordinary':['/usr/share/doc/demo'], 'library':['/usr/lib/libdemo.so'],
            'certificates':['/usr/share/ca-certificates/trust-source/demo.p11-kit']}
        self.manifest={'schema_version':2,'transaction_id':tx['transaction_id'],'package_generation_id':tx['package_generation']['id'],'payloads':[]}
        for n in names:
            path=cache/(n+'.pkg.tar.zst');path.write_bytes(n.encode())
            self.manifest['payloads'].append(dict(name=n,version='2',path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size=path.stat().st_size,
                signature_status='verified-by-pacman',provenance=repository_provenance('extra'),effects=classify_artifact(package_name=n,roles=[],files=self.paths[n])))
    def _run(self,command):
        self.commands.append(tuple(command))
        if '--file' in command:
            n=Path(command[-1]).name.split('.pkg')[0]
            if '--list' in command: out=''.join(n+' '+p+'\n' for p in self.paths[n])
            elif '--info' in command: out='Install Script : '+('Yes' if self.fault=='scriptlet' and n=='ordinary' else 'No')+'\n'
            else: out=n+' '+('3' if self.fault=='artifact-version' and n=='ordinary' else '2')+'\n'
        else:
            n=command[-1]
            if '--list' in command:
                paths=self.paths[n] if self.fault!='inventory' or n!='ordinary' else ['/usr/share/doc/old']
                out=''.join(n+' '+p+'\n' for p in paths)
            else: out=n+' '+('0' if self.fault=='live-version' and n=='ordinary' else '1')+'\n'
        if self.fault=='unknown' and '--list' in command and '--file' not in command and command[-1]=='ordinary':
            return subprocess.CompletedProcess(command,1,'','unavailable')
        return subprocess.CompletedProcess(command,0,out,'')
    def _hook_profile(self,payloads,*,names=None):
        return {'ok': not (self.fault=='hook' and names==('ordinary',))}

class SubsetProfileContracts(unittest.TestCase):
    def test_exact_filtering_keeps_all_debt_and_has_no_execution_authority(self):
        with tempfile.TemporaryDirectory() as raw:
            ops=Probe(Path(raw));before=copy.deepcopy(ops.transaction)
            report=ops.inspect_subset_profile(ops.manifest)
            self.assertEqual(report['profile_compatible_packages'],['ordinary'])
            self.assertEqual(report['deferred_packages'],['certificates','library'])
            self.assertEqual(report['deferred_boot_packages'],['linux'])
            self.assertFalse(report['execution_authorized']);self.assertEqual(before,ops.transaction)
            self.assertTrue(all('--query' in c and '--sync' not in c and '--upgrade' not in c for c in ops.commands))
    def test_every_unknown_or_unsupported_boundary_defers_package(self):
        for fault in ('scriptlet','artifact-version','live-version','inventory','hook','unknown'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as raw:
                ops=Probe(Path(raw),fault=fault);report=ops.inspect_subset_profile(ops.manifest)
                self.assertEqual(report['profile_compatible_packages'],[])
                self.assertIn('ordinary',report['deferred_packages'])
    def test_forged_staged_effects_do_not_hide_trust_mutation(self):
        with tempfile.TemporaryDirectory() as raw:
            ops=Probe(Path(raw));payload=next(p for p in ops.manifest['payloads'] if p['name']=='certificates')
            payload['effects']=classify_artifact(package_name='certificates',roles=[],files=['/usr/share/doc/innocent'])
            report=ops.inspect_subset_profile(ops.manifest)
            row=next(r for r in report['packages'] if r['name']=='certificates')
            self.assertIn('staged_effect_analysis_drift',row['reasons'])
            self.assertEqual(row['effects']['effects'],['trust-store'])
    def test_archive_changes_during_inspection_prevent_report(self):
        with tempfile.TemporaryDirectory() as raw:
            ops=Probe(Path(raw));original=ops._hook_profile
            def change(payloads,**kwargs):
                Path(payloads[0]).write_bytes(b'substituted');return original(payloads,**kwargs)
            with patch.object(ops,'_hook_profile',side_effect=change),self.assertRaises(ValueError):
                ops.inspect_subset_profile(ops.manifest)
    def test_subset_queries_cannot_escape_original_generation(self):
        with tempfile.TemporaryDirectory() as raw:
            ops=Probe(Path(raw))
            for names in ([],['outside']):
                with self.assertRaises(ValueError): ops._live_package_paths_by_name(names=names)

if __name__=='__main__':unittest.main(verbosity=2)
