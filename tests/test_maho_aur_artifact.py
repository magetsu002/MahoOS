#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import json, os, stat, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from maho_aur_artifact import record_build, source_tree_sha256

def check(name, condition):
    if not condition: raise AssertionError(name)
    print('PASS',name)

def make_pacman(root:Path)->Path:
    script=root/'pacman'
    mode_file=root/'mode'
    script.write_text(f'''#!/usr/bin/env bash
set -u
mode="$(cat "{mode_file}" 2>/dev/null || echo normal)"
if [[ " $* " == *" --query --file --info "* ]]; then
  printf 'Name : demo-aur\\nVersion : 2-1\\n'; exit 0
fi
if [[ " $* " == *" --query --file --list "* ]]; then
  if [ "$mode" = boot ]; then
    printf 'demo-aur /usr/lib/modules/7.2/extra/demo.ko.zst\\n'
  else
    printf 'demo-aur /usr/bin/demo-aur\\ndemo-aur /usr/lib/systemd/user/demo-aur.service\\n'
  fi
  exit 0
fi
if [[ " $* " == *" --query -- "* ]]; then
  printf 'demo-aur 1-1\n'; exit 0
fi
if [[ " $* " == *" --sync --info "* ]]; then
  [ "$mode" = repo-owned ] && {{ printf 'Repository : extra\\nName : demo-aur\\n'; exit 0; }}
  exit 1
fi
exit 2
''')
    script.chmod(0o755); return script

def fixture(root:Path):
    stage=root/'stage'; stage.mkdir(); (stage/'PKGBUILD').write_text('pkgname=demo-aur\npkgver=2\npkgrel=1\n')
    (stage/'source.txt').write_text('exact source\n')
    pkg=stage/'demo-aur-2-1-x86_64.pkg.tar.zst'; pkg.write_bytes(b'exact-package')
    config=root/'pacman.conf'; config.write_text('[core]\nInclude=/etc/pacman.d/mirrorlist\n')
    return stage,pkg,config

def main():
    with tempfile.TemporaryDirectory(prefix='maho-aur-artifact-') as temporary:
        root=Path(temporary); stage,pkg,config=fixture(root); pacman=make_pacman(root); mode=root/'mode'; mode.write_text('normal')
        before=source_tree_sha256(stage); pkg.write_bytes(b'changed-output'); after=source_tree_sha256(stage)
        check('source identity excludes produced package payloads',before==after)
        pkg.write_bytes(b'exact-package')
        pre={'sha256':'a'*64,'risk':'info','score':0}
        payload,rc=record_build(state_root=root/'state',stage=stage,preflight=pre,status='verified',phase='complete',pacman_config=config,pacman=str(pacman))
        check('verified AUR output becomes exact Maho artifact',rc==0 and payload['status']=='verified' and len(payload['packages'])==1)
        artifact=payload['packages'][0]
        check('artifact binds exact name version digest and source',artifact['name']=='demo-aur' and artifact['version']=='2-1' and len(artifact['sha256'])==64 and artifact['provenance']['source_sha256']==payload['source_tree_sha256'])
        check('artifact has stable Maho identity',artifact['artifact_id'].startswith('aurpkg-') and len(artifact['artifact_id'])==71)
        check('normal AUR artifact derives user-session effect',artifact['route']=='normal' and 'affected-user-session-restart' in artifact['effects']['activation_requirements'])
        receipt=Path(payload['receipt_path'])
        check('AUR receipt is private and never installation authority',stat.S_IMODE(receipt.stat().st_mode)==0o600 and payload['automatic_install'] is False and payload['installation_authority']=='maho-update-only')
        mode.write_text('boot')
        boot,rc=record_build(state_root=root/'state2',stage=stage,preflight=pre,status='verified',phase='complete',pacman_config=config,pacman=str(pacman))
        check('exact AUR kernel-module output routes to boot-critical',rc==0 and boot['packages'][0]['route']=='boot-critical')
        mode.write_text('repo-owned')
        rejected,rc=record_build(state_root=root/'state3',stage=stage,preflight=pre,status='verified',phase='complete',pacman_config=config,pacman=str(pacman))
        check('repo-owned output is rejected after build',rc==4 and rejected['status']=='rejected' and 'repository-owned package' in rejected['rejection'] and rejected['packages']==[])
        mode.write_text('normal')
        metadata={
            'schema_version':1,'kind':'maho-aur-source','name':'demo-aur','version':'9-9',
            'package_base':'demo-base','aur_git_commit':'1'*40,
            'repository_config':str(config),'repository_config_sha256':'b'*64,
            'fetched_at':'2026-09-20T08:45:00Z',
        }
        (stage/'.maho-aur-metadata.json').write_text(json.dumps(metadata))
        mismatched,rc=record_build(state_root=root/'state4',stage=stage,preflight=pre,status='verified',phase='complete',pacman_config=config,pacman=str(pacman))
        check('fetched candidate metadata rejects build-version substitution',rc==4 and mismatched['status']=='rejected' and 'exact fetched AUR candidate' in mismatched['rejection'])
        metadata['version']='2-1'; (stage/'.maho-aur-metadata.json').write_text(json.dumps(metadata))
        matched,rc=record_build(state_root=root/'state5',stage=stage,preflight=pre,status='verified',phase='complete',pacman_config=config,pacman=str(pacman))
        check('matching fetched candidate binds package-base provenance',rc==0 and matched['packages'][0]['provenance']['package_base']=='demo-base' and matched['aur_metadata']['aur_git_commit']=='1'*40)
        escaping=stage/'escape'; escaping.symlink_to('/etc/passwd')
        try: source_tree_sha256(stage)
        except ValueError: check('source identity rejects absolute symlink escape',True)
        else: check('source identity rejects absolute symlink escape',False)
    print('ALL MAHO AUR ARTIFACT CONTRACTS PASS')
if __name__=='__main__': main()
