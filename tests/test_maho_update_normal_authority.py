#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import copy, stat, sys, tempfile, hashlib, json
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
    def rehash(value):
        data=dict(value); data.pop('authority_id',None)
        data['authority_id']='normal-'+hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        return data
    rejected('rehashing metadata cannot certify a service effect under ordinary profile',
             lambda:verify_normal_execution_authority(rehash(tampered),source_revision=REV))
    for effect in ('shared-library','user-service','privilege-authority','trust-store','package-hook'):
        changed=copy.deepcopy(authority); changed['certified_effects']=['ordinary-files',effect]
        rejected('rehashing cannot invent certified '+effect,
                 lambda changed=changed:verify_normal_execution_authority(rehash(changed),source_revision=REV))
    changed=copy.deepcopy(authority); changed['certified_activation_requirements']=['affected-process-restart']
    rejected('rehashing cannot invent in-place activation authority',
             lambda:verify_normal_execution_authority(rehash(changed),source_revision=REV))
    multi=issue_normal_execution_authority(
        source_revision=REV,
        transaction_id='upd-20260920T091000Z-123456abcdef',
        package_generation_id='pkg-'+'e'*64,
        graph_id='art-'+'f'*64,
        packages=[
            {'name':'vulkan-headers','installed_version':'1','candidate_version':'2','sha256':'1'*64},
            {'name':'hwdata','installed_version':'4','candidate_version':'5','sha256':'2'*64},
        ],
        effects=['ordinary-files'], activation_requirements=[],
        verification={'ok':True,'package_paths_checked':20,'mismatches':[]},
        candidate_root_identity='candidate-root', base_root_identity='base-root',
    )
    check('multi-package ordinary authority preserves exact per-artifact evidence',
          [x['name'] for x in verify_normal_execution_authority(multi,source_revision=REV)['packages']]
          == ['hwdata','vulkan-headers'])
    check('multi-package ordinary authority authorizes only the certified effects',
          authorize_normal_plan(multi,source_revision=REV,effects=['ordinary-files'],activation_requirements=[])['authority_id']
          == multi['authority_id'])
    rejected('multi-package evidence tampering invalidates host authority',
             lambda:verify_normal_execution_authority(
                 dict(multi,packages=[dict(multi['packages'][0],sha256='3'*64),multi['packages'][1]]),
                 source_revision=REV))
    rejected('multi-package authority cannot certify service restart without proof',
             lambda:authorize_normal_plan(multi,source_revision=REV,effects=['system-service'],
                                          activation_requirements=['affected-system-service-restart']))
    wrong_profile=copy.deepcopy(authority); wrong_profile['certified_profile']='ordinary-files-vague'
    rejected('authority cannot broaden certified execution profile',lambda:verify_normal_execution_authority(wrong_profile,source_revision=REV))
    with tempfile.TemporaryDirectory(prefix='maho-normal-authority-') as temporary:
        path=Path(temporary)/'state'/'normal-execution-authority.json'
        publish_normal_execution_authority(authority,path)
        check('durable authority is root-write/user-read compatible',stat.S_IMODE(path.stat().st_mode)==0o644 and stat.S_IMODE(path.parent.stat().st_mode)==0o755)
    check('certification token binds exact source revision',certification_confirmation(REV)=='CERTIFY-NORMAL:'+REV)
    print('ALL MAHO NORMAL UPDATE AUTHORITY CONTRACTS PASS')

if __name__=='__main__': main()
