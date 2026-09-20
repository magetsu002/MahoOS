#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))

from maho_update_discovery import CommandResult
from maho_update_effects import repository_provenance
from maho_update_normal import NormalPreparationEvidence, execute_normal_update, prepare_normal_transaction
from maho_update_staging import IsolatedPacmanStaging, stage_transaction
from maho_update_state import create_transaction

NOW=datetime(2026,9,20,7,30,tzinfo=timezone.utc)

def check(name, condition):
    if not condition: raise AssertionError(name)
    print('PASS',name)

class FakeStage:
    def __init__(self, cache:Path, *, boot=False):
        self.cache=cache; self.boot=boot
    def __call__(self, command):
        if '--print' in command:
            return CommandResult(0,'extra\tdemo-service\t2\n')
        if '--downloadonly' in command:
            self.cache.mkdir(parents=True,exist_ok=True)
            (self.cache/'demo-service-2-any.pkg.tar.zst').write_bytes(b'demo-v2')
            return CommandResult(0,'')
        if '--file' in command and '--info' in command:
            return CommandResult(0,'Name : demo-service\nVersion : 2\n')
        if '--file' in command and '--list' in command:
            path='/usr/lib/modules/7.2/extra/demo.ko.zst' if self.boot else '/usr/lib/systemd/system/demo.service'
            return CommandResult(0,f'demo-service {path}\ndemo-service /usr/bin/demo\n')
        raise AssertionError(command)

class FixtureOps:
    fixture_safe=True
    def __init__(self): self.calls=[]
    def install_candidate(self,plan): self.calls.append('install'); return {'ok':True,'offline_candidate':True}
    def guardian_admit(self,plan): self.calls.append('admit'); return {'ok':True,'graph':'normal-fixture'}
    def activate(self,plan): self.calls.append('activate'); return {'ok':True,'requirements':list(plan.activation_requirements)}
    def verify(self,plan): self.calls.append('verify'); return {'ok':True,'package_generation_id':plan.package_generation_id}

def tx(*, independent=True):
    selection={
        'kind':'independent-normal' if independent else 'full',
        'deferred_boot_packages':['linux-cachyos'] if independent else [],
        'solver_proof':(
            {
                'kind':'isolated-pacman-independent-generation',
                'deferred_boot_packages':['linux-cachyos'],
                'selected_versions_match_full':True,
                'selected_repositories_match_full':True,
                'production_ignore_execution':False,
            } if independent else {'kind':'full-system-solver'}
        ),
    }
    return create_transaction(
        transaction_id='upd-20260920T073000Z-123456abcdef',
        source_revision='d'*40,
        packages=[{'name':'demo-service','installed_version':'1','candidate_version':'2','repository':'extra','download_size':8,'installed_size':16,'roles':[]}],
        activation_requirements=[],
        recovery_generation_id=None,
        provenance_by_package={'demo-service':repository_provenance('extra')},
        selection=selection,
        now=NOW,
    )

def evidence(environment='fixture'):
    return NormalPreparationEvidence(
        discovery_generation_current=True,
        coherent_independent_generation=True,
        required_disk_bytes=32,
        available_disk_bytes=1024,
        power_status_known=True,
        power_policy_satisfied=True,
        concurrent_package_or_build_operation=False,
        candidate_root_available=True,
        guardian_admission_available=True,
        execution_environment=environment,
    )

def stage(root:Path, *, boot=False, independent=True):
    db=root/'db'; db.mkdir(parents=True)
    cache=root/'cache'
    backend=IsolatedPacmanStaging(db,cache,runner=FakeStage(cache,boot=boot))
    result=stage_transaction(tx(independent=independent),backend,available_bytes=1024**3,now=NOW)
    return result,cache

def main():
    with tempfile.TemporaryDirectory(prefix='maho-normal-') as temporary:
        staged,cache=stage(Path(temporary))
        check('normal exact artifact reaches STAGED',staged.transaction['state']=='STAGED')
        check('service effect derives activation independently of origin',staged.transaction['activation']['requirements']==['affected-system-service-restart'])
        prepared=prepare_normal_transaction(staged.transaction,staged.manifest,cache,evidence(),now=NOW)
        check('independent normal generation reaches PREPARED without M4B',prepared.transaction['state']=='PREPARED' and not prepared.blockers)
        check('normal plan binds source provenance generation',prepared.plan.source_provenance_id==staged.transaction['source_provenance']['id'])
        check('normal plan retains solver selection kind',prepared.plan.selection_kind=='independent-normal')
        ops=FixtureOps()
        executed=execute_normal_update(prepared.transaction,prepared.plan,ops,now=NOW)
        check('fixture normal update completes HEALTHY lifecycle',executed.transaction['state']=='HEALTHY')
        check('fixture lifecycle requires Guardian Admission',ops.calls==['install','admit','activate','verify'])

    with tempfile.TemporaryDirectory(prefix='maho-normal-prod-') as temporary:
        staged,cache=stage(Path(temporary))
        prepared=prepare_normal_transaction(staged.transaction,staged.manifest,cache,evidence('production'),now=NOW)
        ops=FixtureOps()
        executed=execute_normal_update(prepared.transaction,prepared.plan,ops,now=NOW)
        check('production normal mutation remains fail-closed pending hardware certification',executed.transaction['state']=='BLOCKED' and executed.transaction['blockers']==['normal_update_execution_uncertified'])
        check('production certification gate blocks before mutation',ops.calls==[] and executed.mutation_started is False)

    with tempfile.TemporaryDirectory(prefix='maho-normal-elevate-') as temporary:
        staged,cache=stage(Path(temporary),boot=True)
        check('exact payload can elevate preliminary normal package to boot-critical',staged.manifest['effects']['classification']=='boot-critical')
        prepared=prepare_normal_transaction(staged.transaction,staged.manifest,cache,evidence(),now=NOW)
        check('boot effect is routed out of normal lane',prepared.transaction['state']=='BLOCKED' and 'boot_critical_effects_detected' in prepared.transaction['blockers'])

    with tempfile.TemporaryDirectory(prefix='maho-normal-full-') as temporary:
        staged,cache=stage(Path(temporary),independent=False)
        prepared=prepare_normal_transaction(staged.transaction,staged.manifest,cache,evidence(),now=NOW)
        check('full solver generation with no boot effects is valid normal lane',prepared.transaction['state']=='PREPARED' and prepared.plan.selection_kind=='full')

    print('ALL MAHO NORMAL UPDATE CONTRACTS PASS')

if __name__=='__main__': main()
