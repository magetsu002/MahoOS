#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))

from guardian_admission import AdmissionOutcome
from guardian_admission import EffectKind
from maho_update_discovery import CommandResult
from maho_update_native import NativeBtrfsOps
from maho_update_normal_host import NormalProductionOps

TX='upd-20260920T094500Z-123456abcdef'

def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print('PASS',name)

class FakeBtrfs(NativeBtrfsOps):
    def __init__(self, root: Path):
        super().__init__(TX,run_root=root/'run')
        self.offline_root=root/'guest'
        self.offline_root.mkdir(parents=True)
        for name in ('dev','proc','sys','run'):
            (self.offline_root/name).mkdir()
        self.mounted={str(self.offline_root)}
        self.commands=[]
    @staticmethod
    def require_root():
        return None

    def _run(self, command, *, check=False):
        command=tuple(command)
        self.commands.append(command)
        if command[:2]==('mountpoint','-q'):
            rc=0 if command[2] in self.mounted else 1
            return CommandResult(rc,'','')
        if command and command[0]=='mount':
            self.mounted.add(command[-1])
            return CommandResult(0,'','')
        if command and command[0]=='umount':
            self.mounted.discard(command[-1])
            return CommandResult(0,'','')
        return CommandResult(0,'','')

class ScriptletProbe(NormalProductionOps):
    @staticmethod
    def _run(command):
        text='Name : demo\nVersion : 2\nInstall Script : No\n'
        return subprocess.CompletedProcess(command,0,text,'')

class QueryProbe(NormalProductionOps):
    def __init__(self):
        self.expected={'demo':'2'}
        self.commands=[]
    def _run(self, command):
        self.commands.append(tuple(command))
        return subprocess.CompletedProcess(command,0,'demo 2\n','')

class CandidateListProbe(NormalProductionOps):
    def _run(self, command):
        command=tuple(command)
        root=command[command.index('--root')+1]
        return subprocess.CompletedProcess(
            command,0,
            f'demo {root}/usr/\ndemo {root}/usr/bin/\ndemo {root}/usr/bin/demo\n',''
        )

class ScriptletReject(NormalProductionOps):
    @staticmethod
    def _run(command):
        text='Name : demo\nVersion : 2\nInstall Script : Yes\n'
        return subprocess.CompletedProcess(command,0,text,'')

class PathSetProbe(NormalProductionOps):
    def __init__(self, *, drift=False):
        self.expected={'demo':'2'}
        self.drift=drift
    def _run(self, command):
        command=tuple(command)
        rooted='--root' in command
        if '--list' in command:
            prefix=''
            if rooted:
                prefix=command[command.index('--root')+1]
            rows=[
                f'demo {prefix}/usr/bin/demo\n',
                f'demo {prefix}/usr/share/demo.txt\n',
            ]
            if rooted and self.drift:
                rows.append(f'demo {prefix}/usr/share/new.txt\n')
            return subprocess.CompletedProcess(command,0,''.join(rows),'')
        raise AssertionError(command)

class InPlaceProbe(NormalProductionOps):
    def __init__(self, *, artifact_drift=False, missing_live=False):
        self.expected={'demo':'2'}
        self.artifact_drift=artifact_drift
        self.missing_live=missing_live
    def _run(self, command):
        command=tuple(command)
        if command[:3]==(self.PACMAN,'--query','--list'):
            if self.missing_live:
                return subprocess.CompletedProcess(command,1,'','error: package demo was not found\n')
            return subprocess.CompletedProcess(command,0,'demo /usr/bin/demo\ndemo /usr/share/demo.txt\n','')
        if '--file' in command and '--list' not in command:
            return subprocess.CompletedProcess(command,0,'demo 2\n','')
        if '--file' in command and '--list' in command:
            rows='demo /usr/bin/demo\ndemo /usr/share/demo.txt\n'
            if self.artifact_drift:
                rows+='demo /usr/share/new.txt\n'
            return subprocess.CompletedProcess(command,0,rows,'')
        raise AssertionError(command)


class ActivationGateProbe(NormalProductionOps):
    def __init__(self, root: Path):
        self.expected={'demo':'2'}
        self.previous={'demo':'1'}
        self.admission=SimpleNamespace(
            decision=SimpleNamespace(outcome=AdmissionOutcome.ALLOW)
        )
        self.roots=SimpleNamespace(candidate_root=root/'candidate')
        self.candidate={'parent_root_uuid':'root-uuid'}
        self.btrfs=SimpleNamespace(
            run_root=root/'run',
            root_identity=lambda: SimpleNamespace(
                filesystem_uuid='fs-uuid',
                fsroot='/@',
                source='/dev/test',
                device='/dev/test',
                subvolume_uuid='root-uuid',
            ),
        )
        self.live_mutation_started=False
        self.PACMAN_LOCK=root/'no-pacman-lock'
        self.preflight_calls=0

    def _path_set_evidence(self, candidate_root):
        return {'ok':True,'profile':'ordinary-files-static-path-set-v1'}

    def _active_target_processes(self):
        return []

    def _query_versions(self, *, root=None):
        return dict(self.previous if root is None else self.expected)

    def _payloads(self, plan):
        return ('/tmp/demo.pkg.tar.zst',)

    def _payload_scriptlet_free(self, payload):
        return True,None

    def _in_place_upgrade_profile(self, payloads):
        return {'ok':True,'profile':'in-place-static-package-path-set-v1'}

    def _hook_profile(self, payloads):
        return {'ok':True,'profile':'bounded-hooks-static-path-set-v1'}

    def preflight_activation(self, plan):
        self.preflight_calls += 1
        return super().preflight_activation(plan)

    def _run(self, command):
        return subprocess.CompletedProcess(command,0,'','')

def main():
    inspection_error='unexpected_mount_boundary:/var/lib/example'
    fake_result=SimpleNamespace(
        decision=SimpleNamespace(
            outcome=AdmissionOutcome.REJECT,
            reasons=('candidate_inspection_incomplete',),
        ),
        inspection=SimpleNamespace(
            errors=(inspection_error,),
            runtime_complete=True,
            runtime_isolated=True,
            base_root_identity='base-id',
            candidate_root_identity='candidate-id',
            graph=SimpleNamespace(
                graph_id='art-test',
                inspection_complete=False,
                effects=(SimpleNamespace(kind=EffectKind.FILE,operation='CHANGE',declared=True),),
            ),
        ),
        promotion_authority=None,
    )
    guardian_evidence=NormalProductionOps._guardian_evidence(fake_result)
    check('normal Guardian rejection preserves exact inspection errors',guardian_evidence['inspection_errors']==[inspection_error] and guardian_evidence['inspection_errors_total']==1 and guardian_evidence['inspection_errors_truncated'] is False)
    check('normal Guardian evidence preserves inspection and runtime status',guardian_evidence['inspection_complete'] is False and guardian_evidence['runtime_complete'] is True and guardian_evidence['runtime_isolated'] is True)
    check('normal Guardian evidence summarizes bounded candidate effects',guardian_evidence['effects']=={'total':1,'declared':1,'undeclared':0,'by_kind':{'FILE':1},'by_operation':{'CHANGE':1}})
    many_errors=tuple(f'path_unreadable:/tmp/{index}:PermissionError' for index in range(NormalProductionOps.MAX_GUARDIAN_INSPECTION_ERRORS+1))
    fake_result.inspection.errors=many_errors
    bounded=NormalProductionOps._guardian_evidence(fake_result)
    check('normal Guardian error evidence is explicitly bounded and digest-bound',len(bounded['inspection_errors'])==NormalProductionOps.MAX_GUARDIAN_INSPECTION_ERRORS and bounded['inspection_errors_total']==len(many_errors) and bounded['inspection_errors_truncated'] is True and len(bounded['inspection_errors_sha256'])==64)

    with tempfile.TemporaryDirectory(prefix='maho-normal-runtime-') as temporary:
        fake=FakeBtrfs(Path(temporary))
        evidence=fake.mount_normal_candidate_runtime()
        check('candidate runtime reports bounded pseudo-filesystems',evidence['runtime']==['dev-minimal','proc','sys-ro','run-private'])
        joined=[' '.join(cmd) for cmd in fake.commands]
        check('candidate runtime mounts private run tmpfs',any('tmpfs '+str(fake.offline_root/'run') in item for item in joined))
        check('candidate runtime mounts fresh procfs',any('proc '+str(fake.offline_root/'proc') in item for item in joined))
        check('candidate runtime mounts sysfs read-only',any('ro,nosuid,nodev,noexec sysfs '+str(fake.offline_root/'sys') in item for item in joined))
        for node in ('null','zero','random','urandom'):
            check(f'candidate runtime exposes only safe device {node}',any(f'/dev/{node} '+str(fake.offline_root/'dev'/node) in item for item in joined))
        check('candidate runtime does not bind host run',not any('--bind /run ' in item or '--rbind /run ' in item for item in joined))
        fake.unmount_normal_candidate_runtime()
        check('candidate runtime teardown removes nested mounts',fake.mounted=={str(fake.offline_root)})

    with tempfile.TemporaryDirectory(prefix='maho-normal-hooks-') as temporary:
        hookdir=Path(temporary)/'hooks'
        created=NormalProductionOps._create_hook_overrides(hookdir)
        check('normal profile masks exactly host snapshot and boot integration hooks',
              {p.name for p in created}==set(NormalProductionOps.MASKED_HOST_HOOKS))
        check('hook overrides use documented null override',all(p.is_symlink() and os.readlink(p)=='/dev/null' for p in created))
        NormalProductionOps._remove_hook_overrides(created,hookdir)
        check('transient hook override directory is fully removed',not hookdir.exists())

        system=Path(temporary)/'system'; custom=Path(temporary)/'custom'; system.mkdir(); custom.mkdir()
        (system/'desktop.hook').write_text('[Trigger]\nOperation = Upgrade\nType = Path\nTarget = usr/share/applications/*.desktop\n\n[Action]\nWhen = PostTransaction\nExec = /bin/true\n')
        (system/'global.hook').write_text('[Trigger]\nOperation = Upgrade\nType = Package\nTarget = *\n\n[Action]\nWhen = PostTransaction\nExec = /bin/true\n')
        (custom/'global.hook').symlink_to('/dev/null')
        triggered=NormalProductionOps._triggered_hook_names(package_names=('demo',),archive_paths=('usr/share/applications/demo.desktop',),system_dir=system,custom_dir=custom)
        check('hook matcher honors path trigger and higher-priority null override',triggered==('desktop.hook',))
        check('hook target inversion is ordered',NormalProductionOps._target_matches(('usr/*','!usr/share/private/*'),'usr/bin/demo') and not NormalProductionOps._target_matches(('usr/*','!usr/share/private/*'),'usr/share/private/demo'))

    probe=QueryProbe()
    observed=probe._query_versions(root=Path('/candidate'))
    check('candidate package query returns bounded expected version',observed=={'demo':'2'})
    command=probe.commands[-1]
    check('candidate package query uses root-scoped database semantics','--root' in command and '--dbpath' not in command)
    candidate_paths=CandidateListProbe._package_paths(object.__new__(CandidateListProbe),Path('/candidate'),'demo')
    check('candidate Pacman directory paths normalize to live path representation',
          candidate_paths==('/usr','/usr/bin','/usr/bin/demo'))

    stable=PathSetProbe()._path_set_evidence(Path('/candidate'))
    check('static package path set satisfies certified normal profile',stable['ok'] is True and stable['profile']=='ordinary-files-static-path-set-v1')
    drifted=PathSetProbe(drift=True)._path_set_evidence(Path('/candidate'))
    check('added or removed package path is rejected from certified profile',drifted['ok'] is False)

    in_place=InPlaceProbe()._in_place_upgrade_profile(('/tmp/demo.pkg.tar.zst',))
    check('exact artifact with identical installed path set is an in-place upgrade',in_place['ok'] is True and in_place['profile']=='in-place-static-package-path-set-v1')
    changed=InPlaceProbe(artifact_drift=True)._in_place_upgrade_profile(('/tmp/demo.pkg.tar.zst',))
    check('artifact path addition is rejected before candidate mutation',changed['ok'] is False)
    try:
        InPlaceProbe(missing_live=True)._in_place_upgrade_profile(('/tmp/demo.pkg.tar.zst',))
    except RuntimeError as exc:
        check('new dependency without installed path authority fails before candidate mutation','live target package paths' in str(exc))
    else:
        raise AssertionError('new dependency unexpectedly passed in-place profile')

    with tempfile.TemporaryDirectory(prefix='maho-normal-activation-gate-') as temporary:
        gate=ActivationGateProbe(Path(temporary))
        preflight=gate.preflight_activation(object())
        check('activation preflight proves all deterministic gates without live mutation',
              preflight['ok'] is True and gate.live_mutation_started is False and gate.preflight_calls==1)
        activation=gate.activate(object())
        check('live activation consumes the same preflight gate before mutation',
              activation['ok'] is True and gate.live_mutation_started is True and gate.preflight_calls==2)

    with tempfile.TemporaryDirectory(prefix='maho-normal-parity-') as temporary:
        root=Path(temporary); candidate=root/'candidate'; live=root/'live'
        for base in (candidate,live):
            path=base/'usr/bin/demo'; path.parent.mkdir(parents=True); path.write_bytes(b'exact'); path.chmod(0o755)
            os.setxattr(path,'user.maho-proof',b'v1')
            link=base/'usr/bin/demo-link'; link.symlink_to('demo')
        parity=object.__new__(NormalProductionOps)
        check('final parity accepts exact content mode ownership xattrs and symlink target',
              parity._compare_path(candidate,'/usr/bin/demo',live) and parity._compare_path(candidate,'/usr/bin/demo-link',live))
        os.setxattr(live/'usr/bin/demo','user.maho-proof',b'drift')
        check('final parity rejects extended-attribute drift',not parity._compare_path(candidate,'/usr/bin/demo',live))
        os.setxattr(live/'usr/bin/demo','user.maho-proof',b'v1'); (live/'usr/bin/demo').write_bytes(b'different')
        check('final parity rejects regular-file content drift',not parity._compare_path(candidate,'/usr/bin/demo',live))
        (live/'usr/bin/demo').write_bytes(b'exact'); (live/'usr/bin/demo-link').unlink(); (live/'usr/bin/demo-link').symlink_to('other')
        check('final parity rejects symlink-target drift',not parity._compare_path(candidate,'/usr/bin/demo-link',live))

    ok,_=ScriptletProbe._payload_scriptlet_free(object.__new__(ScriptletProbe),'/tmp/demo.pkg.tar.zst')
    check('scriptlet-free package is allowed into certified profile',ok)
    ok,reason=ScriptletReject._payload_scriptlet_free(object.__new__(ScriptletReject),'/tmp/demo.pkg.tar.zst')
    check('install-script package is rejected from certified profile',not ok and 'install script' in reason)

    print('ALL MAHO NORMAL HOST CONTRACTS PASS')

if __name__=='__main__':
    main()
