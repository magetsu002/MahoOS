#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))

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

class ScriptletReject(NormalProductionOps):
    @staticmethod
    def _run(command):
        text='Name : demo\nVersion : 2\nInstall Script : Yes\n'
        return subprocess.CompletedProcess(command,0,text,'')

def main():
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

    ok,_=ScriptletProbe._payload_scriptlet_free(object.__new__(ScriptletProbe),'/tmp/demo.pkg.tar.zst')
    check('scriptlet-free package is allowed into certified profile',ok)
    ok,reason=ScriptletReject._payload_scriptlet_free(object.__new__(ScriptletReject),'/tmp/demo.pkg.tar.zst')
    check('install-script package is rejected from certified profile',not ok and 'install script' in reason)

    print('ALL MAHO NORMAL HOST CONTRACTS PASS')

if __name__=='__main__':
    main()
