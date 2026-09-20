#!/usr/bin/env python3
from pathlib import Path
import sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from maho_update_discovery import CommandResult, IsolatedPacmanDiscovery, discover_coherent_subset_updates

def check(name, condition):
    if not condition: raise AssertionError(name)
    print('PASS',name)

def rejected(name, fn):
    try: fn()
    except (ValueError,RuntimeError,LookupError):
        print('PASS',name); return
    raise AssertionError(name)

INFO="""Repository : cachyos
Name : linux-cachyos
Version : 7.2.5-1
Download Size : 140 MiB
Installed Size : 145 MiB

Repository : cachyos
Name : teams-for-linux
Version : 2.21.0-1
Download Size : 102 MiB
Installed Size : 337 MiB

Repository : extra
Name : libfoo
Version : 2-1
Download Size : 1 MiB
Installed Size : 2 MiB
"""

class Runner:
    def __init__(self, extra_subset=False): self.commands=[]; self.extra_subset=extra_subset
    def __call__(self, command):
        command=tuple(command); self.commands.append(command)
        if '--refresh' in command: return CommandResult(0,'')
        if '--query' in command and '--sync' not in command:
            return CommandResult(0,'linux-cachyos 7.1.8-1\nteams-for-linux 2.18.1-1\nlibfoo 1-1\n')
        if '--info' in command: return CommandResult(0,INFO)
        if '--sysupgrade' in command and '--ignore' in command:
            out='cachyos\tteams-for-linux\t2.21.0-1\n'
            if self.extra_subset: out+='extra\tlibfoo\t2-1\n'
            return CommandResult(0,out)
        if '--sysupgrade' in command:
            return CommandResult(0,'cachyos\tlinux-cachyos\t7.2.5-1\ncachyos\tteams-for-linux\t2.21.0-1\nextra\tlibfoo\t2-1\n')
        raise AssertionError(command)

def main():
    with tempfile.TemporaryDirectory(prefix='maho-subset-') as temp:
        backend=IsolatedPacmanDiscovery(Path(temp)/'ok',runner=Runner())
        result=discover_coherent_subset_updates(
            backend,target_packages=['teams-for-linux'],source_revision='a'*40,entropy='123456abcdef')
        packages=result.transaction['package_generation']['packages']
        check('coherent subset contains only explicitly requested package',[x['name'] for x in packages]==['teams-for-linux'])
        proof=result.transaction['selection']['solver_proof']
        check('subset proof binds full solver version and repository',proof['selected_versions_match_full'] is True and proof['selected_repositories_match_full'] is True and proof['production_ignore_execution'] is False)
        check('all other updates are deferred inside isolated solver',proof['deferred_packages']==['libfoo','linux-cachyos'])
        ignores=[c for c in backend.commands if '--ignore' in c]
        check('subset exclusion occurs only in isolated solver',len(ignores)==1 and str(backend.db) in ignores[0])
    with tempfile.TemporaryDirectory(prefix='maho-subset-extra-') as temp:
        bad=IsolatedPacmanDiscovery(Path(temp)/'bad',runner=Runner(extra_subset=True))
        rejected('solver-added unexpected update rejects subset',lambda:discover_coherent_subset_updates(
            bad,target_packages=['teams-for-linux'],source_revision='a'*40,entropy='abcdef123456'))
    print('ALL MAHO COHERENT SUBSET CONTRACTS PASS')

if __name__=='__main__': main()
