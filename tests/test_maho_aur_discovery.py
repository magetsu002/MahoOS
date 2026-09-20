#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from maho_aur_discovery import CommandResult, discover_aur_updates, parse_yay_upgrades

NOW=datetime(2026,9,20,8,0,tzinfo=timezone.utc)

def check(name, condition):
    if not condition: raise AssertionError(name)
    print('PASS',name)

def rejected(name, fn, kinds=(ValueError,RuntimeError)):
    try: fn()
    except kinds:
        print('PASS',name); return
    raise AssertionError(name)

class Runner:
    def __init__(self, repo_owned=()): self.commands=[]; self.repo_owned=set(repo_owned)
    def __call__(self, command):
        command=tuple(command); self.commands.append(command)
        if command[0]=='/fake/yay':
            return CommandResult(0,'chatgpt-desktop 1 -> 2 [1d]\nani-cli 5 -> 6 [2d]\n')
        if command[0]=='/fake/pacman':
            name=command[-1]
            return CommandResult(0,'repo metadata') if name in self.repo_owned else CommandResult(1,'','error: package not found')
        raise AssertionError(command)

def main():
    parsed=parse_yay_upgrades('b 1 -> 2 [1h]\na 3 -> 4\n')
    check('yay rows parse exact versions and sort deterministically',[p.name for p in parsed]==['a','b'])
    rejected('malformed yay row fails closed',lambda:parse_yay_upgrades('garbage'))
    rejected('duplicate AUR candidate fails closed',lambda:parse_yay_upgrades('a 1 -> 2\na 1 -> 3\n'))
    with tempfile.TemporaryDirectory(prefix='maho-aur-discovery-') as temporary:
        config=Path(temporary)/'pacman.conf'; config.write_text('[core]\nInclude = /etc/pacman.d/mirrorlist\n[cachyos]\nInclude = /etc/pacman.d/cachyos-mirrorlist\n')
        runner=Runner()
        result=discover_aur_updates(config_path=config,yay='/fake/yay',pacman='/fake/pacman',runner=runner,now=NOW)
        check('AUR discovery binds exact canonical config',result.pacman_config==str(config.resolve()) and len(result.pacman_config_sha256)==64)
        check('clean AUR candidates survive repository ownership check',[p.name for p in result.packages]==['ani-cli','chatgpt-desktop'])
        check('yay always receives canonical repository universe',runner.commands[0]==('/fake/yay','--config',str(config.resolve()),'-Qua'))
        check('every AUR candidate is cross-checked against canonical repos',sum(1 for c in runner.commands if c[0]=='/fake/pacman')==2)
        owned=Runner(repo_owned={'chatgpt-desktop'})
        rejected('repository-owned package cannot enter AUR discovery',lambda:discover_aur_updates(config_path=config,yay='/fake/yay',pacman='/fake/pacman',runner=owned,now=NOW))
        link=Path(temporary)/'linked.conf'; link.symlink_to(config)
        rejected('symlinked repository authority is refused',lambda:discover_aur_updates(config_path=link,yay='/fake/yay',pacman='/fake/pacman',runner=Runner(),now=NOW))
    print('ALL MAHO AUR DISCOVERY CONTRACTS PASS')
if __name__=='__main__': main()
