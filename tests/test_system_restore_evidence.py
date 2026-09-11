#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))

from maho_system_restore_evidence import CommandResult, SystemEvidenceProbe, collect_provider_evidence, parse_provider_config  # noqa: E402

POLICY = json.loads((ROOT / 'config' / 'platform.json').read_text())
FSUUID = '11111111-2222-3333-4444-555555555555'


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f'PASS {name}')


class FixtureProbe:
    def __init__(self, *, altered: bool = False):
        self.commands: list[tuple[str, ...]] = []
        self.altered = altered

    def run(self, argv):
        args = tuple(argv)
        self.commands.append(args)
        if args == ('pacman', '-Q', 'limine-snapper-sync'):
            return CommandResult(True, 0, 'limine-snapper-sync 1.31.0-1\n')
        if args == ('pacman', '-Qo', '/usr/bin/limine-snapper-restore'):
            return CommandResult(True, 0, '/usr/bin/limine-snapper-restore is owned by limine-snapper-sync 1.31.0-1\n')
        if args == ('pacman', '-Qkk', 'limine-snapper-sync'):
            count = 1 if self.altered else 0
            return CommandResult(True, 0, f'limine-snapper-sync: 48 total files, {count} altered files\n')
        raise AssertionError(f'unexpected command: {args!r}')

    def stat(self, path):
        assert path == '/usr/bin/limine-snapper-restore'
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o755, st_uid=0)

    def read_text(self, path):
        if path == '/etc/limine-snapper-sync.conf':
            return 'RESTORE_METHOD=rsync\nSNAPPER_CONFIG_NAME="wrong"\n'
        if path == '/etc/default/limine':
            return ('RESTORE_METHOD=replace\n'
                    'SNAPPER_CONFIG_NAME="root"\n'
                    'ROOT_SUBVOLUME_PATH="/@"\n'
                    'SET_SNAPSHOT_AS_DEFAULT=no\n'
                    'SNAPSHOT_WRITABLE=no\n'
                    f'FS_UUID={FSUUID}\n'
                    'SNAPSHOT_KERNEL_PARAMETERS+=maho.recovery_snapshot=1\n')
        if path == '/proc/cmdline':
            return f'root=UUID={FSUUID} rw rootflags=subvol=/@snapshots/349/snapshot maho.recovery_snapshot=1'
        raise AssertionError(f'unexpected read: {path}')


def main() -> None:
    config = parse_provider_config("A=one\nB='two'\n", 'A="override"\nC+=ignored\n')
    check('provider config parser applies later scalar overrides', config == {'A': 'override', 'B': 'two'})

    probe = FixtureProbe()
    evidence = collect_provider_evidence(POLICY, probe)
    check('exact provider package version is collected', evidence['package'] == 'limine-snapper-sync' and evidence['version'] == '1.31.0-1')
    check('provider file ownership and permissions are collected', evidence['uid'] == 0 and evidence['mode'] == 0o755 and evidence['regular_file'] is True)
    check('package ownership is independently verified', evidence['package_owns_command'] is True)
    check('package integrity is independently verified', evidence['package_files_ok'] is True)
    check('/etc/default/limine overrides base provider config', evidence['config']['RESTORE_METHOD'] == 'replace' and evidence['config']['SNAPPER_CONFIG_NAME'] == 'root')
    check('array-style config is deliberately ignored', 'SNAPSHOT_KERNEL_PARAMETERS' not in evidence['config'])
    check('collector executes only three exact read-only package queries', probe.commands == [
        ('pacman', '-Q', 'limine-snapper-sync'),
        ('pacman', '-Qo', '/usr/bin/limine-snapper-restore'),
        ('pacman', '-Qkk', 'limine-snapper-sync'),
    ])

    altered = collect_provider_evidence(POLICY, FixtureProbe(altered=True))
    check('altered provider package fails integrity evidence', altered['package_files_ok'] is False)

    refused = False
    try:
        SystemEvidenceProbe().run(('pacman', '-S', 'limine-snapper-sync'))
    except RuntimeError:
        refused = True
    check('system evidence adapter refuses mutating package commands', refused)

    refused = False
    try:
        SystemEvidenceProbe().read_text('/etc/shadow')
    except RuntimeError:
        refused = True
    check('system evidence adapter refuses unrelated file reads', refused)

    print('ALL SYSTEM RESTORE EVIDENCE CONTRACTS PASS')


if __name__ == '__main__':
    main()
