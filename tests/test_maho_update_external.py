#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from maho_update_effects import aur_build_provenance, classify_artifact
from maho_update_external import stage_aur_artifacts, transaction_from_aur_receipt
from maho_update_normal import NormalPreparationEvidence, prepare_normal_transaction

NOW=datetime(2026,9,20,8,30,tzinfo=timezone.utc)

def check(name,condition):
    if not condition: raise AssertionError(name)
    print('PASS',name)

def rejected(name,fn):
    try: fn()
    except ValueError:
        print('PASS',name); return
    raise AssertionError(name)

def pacman(root:Path)->Path:
    mode=root/'mode'; mode.write_text('normal')
    script=root/'pacman'
    script.write_text(f'''#!/usr/bin/env bash
mode="$(cat '{mode}')"
if [[ " $* " == *" --upgrade --print "* ]]; then
  artifact="${{@: -1}}"
  if [ "$mode" = dep ]; then
    printf 'extra\tdemo-dep\t3-1\thttps://repo.invalid/demo-dep-3-1.pkg.tar.zst\n'
  fi
  printf 'local\tdemo-aur\t2-1\t%s\n' "$artifact"
  exit 0
fi
if [[ " $* " == *" --query --file --info "* ]]; then printf 'Name : demo-aur\nVersion : 2-1\n'; exit 0; fi
if [[ " $* " == *" --query --file --list "* ]]; then
  if [ "$mode" = boot ]; then printf 'demo-aur /usr/lib/modules/7.2/extra/demo.ko.zst\n';
  else printf 'demo-aur /usr/bin/demo-aur\ndemo-aur /usr/lib/systemd/user/demo.service\n'; fi
  exit 0
fi
exit 2
''')
    script.chmod(0o755); return script

def receipt(root:Path, *, boot=False):
    config=root/'maho-pacman.conf'
    config.write_text('[options]\nArchitecture = auto\n')
    artifact=root/'demo-aur-2-1-x86_64.pkg.tar.zst'; artifact.write_bytes(b'artifact-v2')
    source_sha='a'*64
    provenance=aur_build_provenance(package_base='demo-aur',source_sha256=source_sha,build_receipt=str(root/'receipt.json'))
    files=['/usr/lib/modules/7.2/extra/demo.ko.zst'] if boot else ['/usr/bin/demo-aur','/usr/lib/systemd/user/demo.service']
    effects=classify_artifact(package_name='demo-aur',roles=[],files=files)
    package={
        'name':'demo-aur','installed_version':'1-1','version':'2-1','path':str(artifact),
        'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'size':artifact.stat().st_size,
        'provenance':provenance,'effects':effects,'route':'boot-critical' if boot else 'normal',
        'automatic_install':False,
    }
    identity={k:package[k] for k in ('name','version','sha256','provenance','effects')}
    package['artifact_id']='aurpkg-'+hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {
        'version':2,'kind':'aur-isolated-build','status':'verified','phase':'complete',
        'automatic_install':False,'installation_authority':'maho-update-only',
        'repository_authority':{
            'config':str(config.resolve()),
            'sha256':hashlib.sha256(config.read_bytes()).hexdigest(),
        },
        'packages':[package],
    }

def prep_evidence():
    return NormalPreparationEvidence(
        discovery_generation_current=True,coherent_independent_generation=True,
        required_disk_bytes=1,available_disk_bytes=1024,power_status_known=True,
        power_policy_satisfied=True,concurrent_package_or_build_operation=False,
        candidate_root_available=True,guardian_admission_available=True,execution_environment='fixture')

def main():
    with tempfile.TemporaryDirectory(prefix='maho-external-normal-') as temporary:
        root=Path(temporary); rec=receipt(root); p=pacman(root)
        tx=transaction_from_aur_receipt(rec,source_revision='e'*40,now=NOW,entropy='123456abcdef')
        check('AUR artifact production begins fail-closed before dependency proof',tx['selection']['kind']=='artifact-set' and tx['selection']['solver_proof']['dependencies_proven'] is False)
        check('AUR transaction preserves artifact provenance',tx['source_provenance']['packages'][0]['kind']=='aur-built')
        staged=stage_aur_artifacts(tx,rec,root/'staging',pacman=str(p),now=NOW)
        proof=staged.transaction['selection']['solver_proof']
        check('AUR exact local artifact dependency closure is proven',proof['dependencies_proven'] is True and proof['normal_profile_compatible'] is True)
        check('AUR dependency proof binds exact artifact and repository authority',proof['local_artifacts'][0]['name']=='demo-aur' and proof['repository_dependency_changes']==[] and len(proof['proof_sha256'])==64)
        check('AUR artifact set is copied and reverified into Maho STAGED state',staged.transaction['state']=='STAGED')
        check('normal exact AUR effects route to normal lane',staged.routing_target=='normal' and staged.manifest['effects']['classification']=='normal')
        prepared=prepare_normal_transaction(staged.transaction,staged.manifest,root/'staging',prep_evidence(),now=NOW)
        check('dependency-closed AUR update can enter normal preparation',prepared.transaction['state']=='PREPARED' and not prepared.blockers)

        (root/'mode').write_text('dep')
        staged_dep=stage_aur_artifacts(tx,rec,root/'staging-dep',pacman=str(p),now=NOW)
        dep_proof=staged_dep.transaction['selection']['solver_proof']
        check('AUR solver records exact repository dependency mutation',dep_proof['dependencies_proven'] is True and dep_proof['normal_profile_compatible'] is False and dep_proof['repository_dependency_changes'][0]['name']=='demo-dep')
        blocked=prepare_normal_transaction(staged_dep.transaction,staged_dep.manifest,root/'staging-dep',prep_evidence(),now=NOW)
        check('repository dependency mutation stays outside certified normal profile',blocked.transaction['state']=='BLOCKED' and 'independent_generation_not_proven' in blocked.transaction['blockers'])

        (root/'mode').write_text('normal')
        Path(rec['packages'][0]['path']).write_bytes(b'tampered')
        rejected('artifact mutation after build is rejected before dependency solving or staging',lambda:stage_aur_artifacts(tx,rec,root/'staging2',pacman=str(p),now=NOW))

    with tempfile.TemporaryDirectory(prefix='maho-external-boot-') as temporary:
        root=Path(temporary); rec=receipt(root,boot=True); p=pacman(root); (root/'mode').write_text('boot')
        tx=transaction_from_aur_receipt(rec,source_revision='e'*40,now=NOW,entropy='abcdef123456')
        staged=stage_aur_artifacts(tx,rec,root/'staging',pacman=str(p),now=NOW)
        check('boot-affecting AUR artifact routes automatically to M4B',staged.routing_target=='m4b' and staged.manifest['effects']['classification']=='boot-critical')
        prepared=prepare_normal_transaction(staged.transaction,staged.manifest,root/'staging',prep_evidence(),now=NOW)
        check('boot-affecting AUR artifact can never enter normal activation',prepared.transaction['state']=='BLOCKED' and 'boot_critical_effects_detected' in prepared.transaction['blockers'])
    print('ALL MAHO EXTERNAL ARTIFACT HANDOFF CONTRACTS PASS')
if __name__=='__main__': main()
