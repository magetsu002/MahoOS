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
    rejected('empty artifact inventory fails closed by default', lambda: classify_artifact(package_name='meta',roles=[],files=[]))
    rejected('interior traversal cannot disguise privileged or library paths', lambda: classify_artifact(package_name='demo',roles=[],files=['/usr/share/../lib/demo.so']))
    metadata=classify_artifact(package_name='meta',roles=[],files=[],allow_empty=True)
    check('explicit zero-file package remains complete metadata-only evidence',
          metadata['classification']=='normal' and metadata['file_count']==0 and metadata['effects']==['metadata-only'])
    service=classify_artifact(package_name='demo',roles=[],files=['/usr/lib/systemd/system/demo.service','/usr/bin/demo'])
    check('service file derives service restart requirement', service['activation_requirements']==['affected-system-service-restart'])
    sudoers=classify_artifact(package_name='demo',roles=[],files=['/etc/sudoers.d/demo','/usr/bin/demo'])
    check('privilege authority never looks like an ordinary file update',
          'privilege-authority' in sudoers['effects'] and 'security-boundary-review' in sudoers['activation_requirements'])
    privilege_paths=(
        '/etc/sudoers.d/demo',
        '/usr/share/polkit-1/rules.d/90-demo.rules',
        '/etc/pam.d/demo',
        '/usr/lib/udev/rules.d/90-demo.rules',
        '/usr/lib/sysusers.d/demo.conf',
        '/etc/sysctl.d/90-demo.conf',
        '/usr/share/dbus-1/system.d/demo.conf',
    )
    for path in ('/etc/ssl/certs/ca-certificates.crt', '/usr/share/ca-certificates/trust-source/mozilla.trust.p11-kit', '/usr/share/pacman/keyrings/archlinux.gpg', '/etc/pacman.d/gnupg/trustdb.gpg', '/etc/ca-certificates.conf'):
        effect = classify_artifact(package_name='ordinary-looking-name', roles=[], files=[path])
        check(f'trust-store effects require independent security review: {path}', effect['effects'] == ['trust-store'] and effect['activation_requirements'] == ['security-boundary-review'])
    for path in privilege_paths:
        effect=classify_artifact(package_name='demo',roles=[],files=[path])
        check(f'privilege authority is classified before candidate execution: {path}',
              'privilege-authority' in effect['effects'] and 'security-boundary-review' in effect['activation_requirements'])
    persistence_paths=(
        '/usr/lib/tmpfiles.d/demo.conf',
        '/etc/NetworkManager/dispatcher.d/demo',
        '/usr/lib/systemd/system-generators/demo',
        '/usr/lib/systemd/system-environment-generators/demo',
        '/etc/profile.d/demo.sh',
    )
    for path in persistence_paths:
        effect=classify_artifact(package_name='demo',roles=[],files=[path])
        check(f'startup persistence is classified before candidate execution: {path}',
              'startup-persistence' in effect['effects'] and 'security-boundary-review' in effect['activation_requirements'])
    for path in ('/etc/ld.so.preload','/etc/ld.so.conf.d/demo.conf','/usr/lib/binfmt.d/demo.conf'):
        effect=classify_artifact(package_name='demo',roles=[],files=[path])
        check(f'loader policy is classified before candidate execution: {path}',
              'loader-policy' in effect['effects'] and 'security-boundary-review' in effect['activation_requirements'])
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
