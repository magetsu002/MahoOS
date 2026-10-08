#!/usr/bin/env python3
"""Real Pacman solver, disposable databases, no refresh/install/network."""
from pathlib import Path
import hashlib,io,json,sys,tarfile,tempfile
from datetime import datetime,timezone
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
import maho_update_coordinator as coordinator
from maho_update_discovery import IsolatedPacmanDiscovery,discover_coherent_subset_updates,_solver_plan_digest,parse_solver_plan

def desc(name,version,depends=()):
    fields={'FILENAME':name+'-'+version+'-any.pkg.tar.zst','NAME':name,'BASE':name,'VERSION':version,
        'DESC':'Disposable solver fixture','ARCH':'any','CSIZE':'1','ISIZE':'1','SIZE':'1','BUILDDATE':'1','INSTALLDATE':'1','REASON':'0','VALIDATION':'none'}
    if depends:fields['DEPENDS']='\n'.join(depends)
    return ''.join('%'+key+'%\n'+value+'\n\n' for key,value in fields.items()).encode()

def main():
    if not Path('/usr/bin/pacman').is_file():
        print('SKIP real Pacman is unavailable');return
    with tempfile.TemporaryDirectory(prefix='maho-frozen-solver-') as raw:
        root=Path(raw);installed=root/'installed';installed.mkdir()
        (installed/'ALPM_DB_VERSION').write_text('9\n')
        names=('docs','manuals','consumer','libfoo','linux')
        for name in names:
            package=installed/(name+'-1-1');package.mkdir()
            (package/'desc').write_bytes(desc(name,'1-1',('libfoo>=1',) if name=='consumer' else ()))
            (package/'files').write_text('%FILES%\nusr/share/doc/'+name+'\n')
        config=root/'pacman.conf';config.write_text('[options]\nArchitecture = auto\nSigLevel = Never\n[fixture]\nServer = file:///nonexistent-solver-fixture\n')
        backend=IsolatedPacmanDiscovery(root/'isolated',installed_db=installed,config_path=config,required_repositories=('fixture',))
        backend.prepare();sync=backend.db/'sync';sync.mkdir(exist_ok=True)
        database=sync/'fixture.db'
        with tarfile.open(database,'w:gz') as archive:
            for name in names:
                content=desc(name,'2-1',('libfoo>=2',) if name=='consumer' else ())
                info=tarfile.TarInfo(name+'-2-1/desc');info.size=len(content);archive.addfile(info,io.BytesIO(content))
        result=backend.run(backend.transaction_command)
        assert result.returncode==0,result.stderr
        versions,repositories=parse_solver_plan(result.stdout)
        full_digest=_solver_plan_digest(versions,repositories);hashes=backend.sync_database_hashes()
        selected=discover_coherent_subset_updates(backend,target_packages=['docs'],source_revision='a'*40,
            expected_full_plan_sha256=full_digest,expected_repository_hashes=hashes,refresh_repositories=False)
        assert [p['name'] for p in selected.transaction['package_generation']['packages']]==['docs']
        assert selected.deferred_boot_packages==('linux',)
        print('PASS real Pacman proves exact independent document subset with boot debt retained')
        try:
            discover_coherent_subset_updates(backend,target_packages=['consumer'],source_revision='a'*40,
                expected_full_plan_sha256=full_digest,expected_repository_hashes=hashes,refresh_repositories=False)
        except RuntimeError as exc:
            print('PASS real dependency solver rejects consumer whose required library is deferred:',str(exc).split(':')[0])
        else:raise AssertionError('incoherent consumer subset accepted')
        full_normal=discover_coherent_subset_updates(backend,target_packages=['docs','manuals','consumer','libfoo'],source_revision='a'*40,
            expected_full_plan_sha256=full_digest,expected_repository_hashes=hashes,refresh_repositories=False)
        with patch.object(coordinator,'NormalProductionOps') as inspected:
            inspected.return_value.inspect_subset_profile.return_value={'profile_compatible_packages':['consumer','docs','manuals']}
            report=coordinator._plan_normal_subset(full_normal.transaction,{},root,backend,hashes,datetime.now(timezone.utc))
        assert report['status']=='coherent-awaiting-recovery-certification',report
        assert [p['name'] for p in report['transaction']['package_generation']['packages']]==['docs','manuals']
        assert report['transaction']['selection']['deferred_boot_packages']==['linux']
        assert not report['execution_authorized']
        assert 'consumer' in report['solver_deferred']
        print('PASS coordinator partitions failed pool and independently solves exact union of compatible groups')
        assert not any('--refresh'  in c or '--upgrade' in c or '--downloadonly' in c for c in backend.commands)
        assert all('--dbpath' in c and str(backend.db) in c for c in backend.commands)
        print('PASS no live database, refresh, network download, or install command used')
    print('ALL FROZEN SUBSET SOLVER INTEGRATION TESTS PASS')

if __name__=='__main__':main()
