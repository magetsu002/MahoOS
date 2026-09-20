#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from maho_aur_source import AurSource, CommandResult, fetch_aur_source

NOW=datetime(2026,9,20,8,45,tzinfo=timezone.utc)
COMMIT='1'*40

def check(name, condition):
    if not condition: raise AssertionError(name)
    print('PASS',name)

def rejected(name, fn, kinds=(ValueError,PermissionError,RuntimeError)):
    try: fn()
    except kinds:
        print('PASS',name); return
    raise AssertionError(name)

class Runner:
    def __init__(self, *, repo_owned=False, version='2-1', ambiguous=False, commit=COMMIT):
        self.repo_owned=repo_owned; self.version=version; self.ambiguous=ambiguous; self.commit=commit; self.commands=[]
    def __call__(self, command, cwd=None):
        command=tuple(command); self.commands.append((command, str(cwd) if cwd else None))
        if command[0]=='/fake/pacman':
            return CommandResult(0,'Repository : extra\nName : demo-aur\n') if self.repo_owned else CommandResult(1,'','not found')
        if command[0]=='/fake/yay' and '--sync' in command and '--info' in command:
            return CommandResult(0,f'Repository : aur\nName : demo-aur\nVersion : {self.version}\n')
        if command[0]=='/fake/yay' and '--getpkgbuild' in command:
            root=Path(cwd)
            first=root/'demo-aur'; first.mkdir(); (first/'PKGBUILD').write_text('pkgname=demo-aur\npkgver=2\npkgrel=1\n'); (first/'.SRCINFO').write_text('pkgbase = demo-base\npkgname = demo-aur\npkgver = 2\npkgrel = 1\n')
            if self.ambiguous:
                second=root/'other'; second.mkdir(); (second/'PKGBUILD').write_text('pkgname=other\n')
            return CommandResult(0,'downloaded')
        if command[0]=='/fake/git' and command[1:]==('rev-parse','HEAD'):
            return CommandResult(0,self.commit+'\n')
        raise AssertionError((command,cwd))

def main():
    with tempfile.TemporaryDirectory(prefix='maho-aur-source-') as temporary:
        root=Path(temporary); config=root/'pacman.conf'; config.write_text('[core]\n[cachyos]\n')
        runner=Runner()
        fetched=fetch_aur_source('demo-aur',expected_version='2-1',cache_root=root/'cache',config_path=config,yay='/fake/yay',pacman='/fake/pacman',git='/fake/git',runner=runner,now=NOW)
        source=Path(fetched.path)
        check('fetch returns private exact AUR source tree',source.is_dir() and (source/'PKGBUILD').is_file())
        check('AUR source binds exact metadata version',fetched.name=='demo-aur' and fetched.version=='2-1')
        check('AUR source binds pkgbase and exact Git commit',fetched.package_base=='demo-base' and fetched.aur_git_commit==COMMIT)
        meta=json.loads((source/'.maho-aur-metadata.json').read_text())
        check('source metadata binds canonical repository authority',meta['repository_config']==str(config.resolve()) and len(meta['repository_config_sha256'])==64)
        check('repo ownership is checked before AUR metadata fetch',runner.commands[0][0][0]=='/fake/pacman' and runner.commands[1][0][0]=='/fake/yay')
        check('fetch command is AUR-only and canonical-config bound','--aur' in runner.commands[2][0] and str(config.resolve()) in runner.commands[2][0])
        check('fetched source directory is transactionally named from pkgbase and commit',source.name=='source-demo-base-'+COMMIT[:12])

        replay=fetch_aur_source('demo-aur',expected_version='2-1',cache_root=root/'cache',config_path=config,yay='/fake/yay',pacman='/fake/pacman',git='/fake/git',runner=Runner(),now=NOW)
        check('same exact AUR source identity replays to same immutable path',replay.path==fetched.path)

        rejected('canonical repo-owned package cannot be fetched from AUR',lambda:fetch_aur_source('demo-aur',expected_version='2-1',cache_root=root/'repo',config_path=config,yay='/fake/yay',pacman='/fake/pacman',git='/fake/git',runner=Runner(repo_owned=True),now=NOW))
        rejected('AUR metadata version drift fails before source acceptance',lambda:fetch_aur_source('demo-aur',expected_version='2-1',cache_root=root/'drift',config_path=config,yay='/fake/yay',pacman='/fake/pacman',git='/fake/git',runner=Runner(version='3-1'),now=NOW))
        rejected('ambiguous multi-tree fetch is rejected',lambda:fetch_aur_source('demo-aur',expected_version='2-1',cache_root=root/'ambiguous',config_path=config,yay='/fake/yay',pacman='/fake/pacman',git='/fake/git',runner=Runner(ambiguous=True),now=NOW))
        rejected('invalid AUR Git identity is rejected',lambda:fetch_aur_source('demo-aur',expected_version='2-1',cache_root=root/'badgit',config_path=config,yay='/fake/yay',pacman='/fake/pacman',git='/fake/git',runner=Runner(commit='bad'),now=NOW))
        link=root/'linked.conf'; link.symlink_to(config)
        rejected('symlinked canonical repository config is rejected',lambda:fetch_aur_source('demo-aur',expected_version='2-1',cache_root=root/'linked',config_path=link,yay='/fake/yay',pacman='/fake/pacman',git='/fake/git',runner=Runner(),now=NOW))
    print('ALL MAHO AUR SOURCE CONTRACTS PASS')
if __name__=='__main__': main()
