#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
from maho_update_effects import (
    aggregate_effects, aur_build_provenance, classify_artifact,
    preliminary_boot_critical, repository_provenance, validate_provenance,
)

def check(name, condition):
    if not condition: raise AssertionError(name)
    print('PASS', name)

def rejected(name, fn):
    try: fn()
    except ValueError:
        print('PASS', name); return
    raise AssertionError(name)

def main():
    repo=repository_provenance('extra')
    check('repo provenance binds repository trust source', validate_provenance(repo)==repo)
    aur=aur_build_provenance(package_base='demo-bin', source_sha256='a'*64, build_receipt='/state/build.json')
    check('AUR provenance is an artifact-production identity', validate_provenance(aur)['kind']=='aur-built')
    rejected('bad AUR digest fails closed', lambda: aur_build_provenance(package_base='x',source_sha256='bad',build_receipt='x'))
    check('preliminary DKMS role is boot-critical', preliminary_boot_critical(['dkms']))
    ordinary=classify_artifact(package_name='brave-bin',roles=[],files=['/usr/bin/brave','/usr/share/applications/brave.desktop'])
    check('ordinary app artifact is normal', ordinary['classification']=='normal')
    service=classify_artifact(package_name='demo',roles=[],files=['/usr/lib/systemd/system/demo.service','/usr/bin/demo'])
    check('service file derives service restart requirement', service['activation_requirements']==['affected-system-service-restart'])
    sudoers=classify_artifact(package_name='demo',roles=[],files=['/etc/sudoers.d/demo','/usr/bin/demo'])
    check('privilege authority never looks like an ordinary file update',
          'privilege-authority' in sudoers['effects'] and 'security-boundary-review' in sudoers['activation_requirements'])
    udev=classify_artifact(package_name='demo',roles=[],files=['/usr/lib/udev/rules.d/90-demo.rules'])
    check('udev authority is classified before candidate execution',
          'privilege-authority' in udev['effects'])
    tmpfiles=classify_artifact(package_name='demo',roles=[],files=['/usr/lib/tmpfiles.d/demo.conf'])
    check('tmpfiles persistence is classified before candidate execution',
          'startup-persistence' in tmpfiles['effects'])
    loader=classify_artifact(package_name='demo',roles=[],files=['/etc/ld.so.conf.d/demo.conf'])
    check('loader policy is classified before candidate execution',
          'loader-policy' in loader['effects'])
    kernel=classify_artifact(package_name='custom-module',roles=[],files=['/usr/lib/modules/7.2/extra/demo.ko.zst'])
    check('artifact paths can elevate harmless-looking package name to boot-critical', kernel['classification']=='boot-critical')
    dkms=classify_artifact(package_name='custom-dkms',roles=['dkms'],files=['/usr/src/custom-1/Makefile'])
    check('roles can elevate artifact to boot-critical before boot path exists', dkms['classification']=='boot-critical')
    summary=aggregate_effects([
        {'name':'brave-bin','effects':ordinary},
        {'name':'custom-module','effects':kernel},
    ])
    check('aggregate routes by effects not origin', summary['classification']=='boot-critical' and summary['boot_critical_packages']==['custom-module'])
    print('ALL MAHO UPDATE EFFECT CONTRACTS PASS')

if __name__=='__main__': main()
