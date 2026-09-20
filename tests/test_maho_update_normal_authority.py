#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import copy, stat, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))

from maho_update_normal_authority import (
    authorize_normal_plan, certification_confirmation,
    issue_normal_execution_authority, publish_normal_execution_authority,
    verify_normal_execution_authority,
)

REV='a'*40

def check(name, condition):
    if not condition: raise AssertionError(name)
    print('PASS', name)

def rejected(name, fn):
    try: fn()
    except ValueError:
        print('PASS', name); return
    raise AssertionError(name)

def main():
    authority=issue_normal_execution_authority(
        source_revision=REV,
        transaction_id='upd-20260920T090000Z-123456abcdef',
        package_generation_id='pkg-'+'b'*64,
        graph_id='art-'+'c'*64,
        packages=[{
            'name':'demo','installed_version':'1','candidate_version':'2','sha256':'d'*64,
        }],
        effects=['ordinary-files'],
        activation_requirements=[],
        verification={'ok':True,'package_paths_checked':10,'mismatches':[]},
        candidate_root_identity='candidate-root',
        base_root_identity='base-root',
    )
    check('normal authority identity is durable and source-bound', verify_normal_execution_authority(authority,source_revision=REV)['authority_id']==authority['authority_id'])
    check('ordinary-files plan is authorized by exact proven scope', authorize_normal_plan(authority,source_revision=REV,effects=['ordinary-files'],activation_requirements=[])['authority_id']==authority['authority_id'])
    rejected('source revision drift invalidates host authority',lambda:verify_normal_execution_authority(authority,source_revision='e'*40))
    rejected('service effect exceeds first certification scope',lambda:authorize_normal_plan(authority,source_revision=REV,effects=['system-service'],activation_requirements=['affected-system-service-restart']))
    rejected('activation requirement cannot be invented',lambda:authorize_normal_plan(authority,source_revision=REV,effects=['ordinary-files'],activation_requirements=['affected-process-restart']))
    tampered=copy.deepcopy(authority); tampered['certified_effects']=['ordinary-files','system-service']
    rejected('tampered certification scope breaks authority identity',lambda:verify_normal_execution_authority(tampered,source_revision=REV))
    wrong_profile=copy.deepcopy(authority); wrong_profile['certified_profile']='ordinary-files-vague'
    rejected('authority cannot broaden certified execution profile',lambda:verify_normal_execution_authority(wrong_profile,source_revision=REV))
    with tempfile.TemporaryDirectory(prefix='maho-normal-authority-') as temporary:
        path=Path(temporary)/'state'/'normal-execution-authority.json'
        publish_normal_execution_authority(authority,path)
        check('durable authority is root-write/user-read compatible',stat.S_IMODE(path.stat().st_mode)==0o644 and stat.S_IMODE(path.parent.stat().st_mode)==0o755)
    check('certification token binds exact source revision',certification_confirmation(REV)=='CERTIFY-NORMAL:'+REV)
    print('ALL MAHO NORMAL UPDATE AUTHORITY CONTRACTS PASS')

if __name__=='__main__': main()
