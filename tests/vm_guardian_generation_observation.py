#!/usr/bin/env python3
"""Root-owned attribution fixture on a real Btrfs guest; no update/reboot proof."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'lib'), str(ROOT/'tests')]
import guardian_generation_observation as g
from test_maho_live_generation import fixture, NOW, TXID, SOURCE
from maho_live_generation import publish_live_generations
from maho_update_state import create_transaction,bind_native_authority,transition_transaction,UpdateState
from maho_update_receipts import build_receipt

base=Path('/var/lib/maho/guardian-observation-vm-fixture')
if base.exists():raise RuntimeError('fixture already exists')
base.mkdir(mode=0o755,parents=True)
rootfd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
physical=g.root_identity(rootfd)
context=g._boot_context(Path('/proc'),rootfd)
version=subprocess.check_output(['pacman','-Q','linux-cachyos'],text=True).split()[1]
# Root-owned synthetic acceptance evidence is a fixture, not an actual update.
tx=create_transaction(transaction_id=TXID,source_revision=SOURCE,
 packages=[dict(name='linux-cachyos',installed_version='old',candidate_version=version,
 repository='cachyos',roles=['kernel'],security_relevant=True,download_size=1,installed_size=1)],
 activation_requirements=['restart','initramfs','boot-artifacts'],recovery_generation_id='g3-623c64a36c689d4d23c82130',now=NOW)
tx=bind_native_authority(tx,recovery_generation_id='g3-623c64a36c689d4d23c82130',m3b_evidence={'fixture':True},update_kind='m4b-campaign',update_evidence={'fixture':True})
for i,state in enumerate((UpdateState.STAGED,UpdateState.PREPARED,UpdateState.MAINTENANCE_READY,UpdateState.INSTALLING,UpdateState.INSTALLED_PENDING_ACTIVATION,UpdateState.ACTIVE_VERIFYING,UpdateState.HEALTHY),1):
 tx=transition_transaction(tx,state,now=NOW+timedelta(minutes=i),evidence={'ok':True,'root_uuid':physical['root_subvolume_uuid'],'fixture':True})
_, journal, _, observation=fixture()
boot=observation.boot_artifacts
for path,content in boot.items():
 target=Path('/boot/maho-observer-fixture')/Path(path).name
 target.parent.mkdir(exist_ok=True);target.write_bytes(content);target.chmod(0o644)
# Publisher's canonical primary paths require the fixture data above; the
# accepted publication is then observed with real guest boot paths instead.
real_boot={path:Path(path).read_bytes() for path in boot if Path(path).is_file()}
for path in boot:
 if path not in real_boot:
  # Guest lacks fallback/microcode; these extra exact fixture artifacts are
  # not claimed as active firmware/kernel evidence.
  Path(path).write_bytes(boot[path]);Path(path).chmod(0o644)
  real_boot[path]=boot[path]
observation=replace(observation,filesystem_uuid=physical['filesystem_uuid'],root_subvolume_uuid=physical['root_subvolume_uuid'],running_kernel=context[1],cmdline=context[2],package_versions={'linux-cachyos':version},boot_artifacts=real_boot)
journal.update(expected_versions=observation.package_versions,candidate={'uuid':physical['root_subvolume_uuid']},home_identity=observation.home_identity)
journal['activation']['boot_sha256']={p:hashlib.sha256(b).hexdigest() for p,b in real_boot.items()}
gen=base/'generations';up=base/'update';(up/'transactions').mkdir(parents=True)
(up/'transactions'/f'{TXID}.json').write_text(json.dumps(tx));(up/'current').write_text('different-staged-candidate')
publication=publish_live_generations(tx,journal,build_receipt(tx),observation,publisher_source_revision='a'*40,root=gen)
assert g.attribute_running_generation(gen,up)==publication
print('PASS real kernel UUIDs, installed package query, protected acceptance and boot hashes')
# Change only the pending pointer during actual package queries.
original=g._packages
def query(expected):
 (up/'current').write_text('concurrent-other-candidate')
 return original(expected)
with patch.object(g,'_packages',query):assert g.attribute_running_generation(gen,up)==publication
print('PASS real observations remain independent of staged/concurrent pointer')
sub=base/'different-root'
subprocess.run(['btrfs','subvolume','create',str(sub)],check=True)
wrongfd=os.open(sub,os.O_RDONLY|os.O_DIRECTORY)
assert g.root_identity(wrongfd)['root_subvolume_uuid']!=physical['root_subvolume_uuid']
actual=g.root_identity
with patch.object(g,'root_identity',lambda fd:actual(wrongfd)):
 assert g.attribute_running_generation(gen,up) is None
print('PASS actual substituted Btrfs UUID with matching acceptance/packages/boot is denied')
os.close(wrongfd);os.close(rootfd)
# Permission and symlink failures use real root-owned inputs, not mocks.
publication_path=gen/'live.json';publication_path.chmod(0o666)
assert g.attribute_running_generation(gen,up) is None
publication_path.chmod(0o644)
publication_path.rename(gen/'original.json');publication_path.symlink_to('original.json')
assert g.attribute_running_generation(gen,up) is None
print('PASS real writable and symlinked acceptance evidence is denied')
print('ALL REAL GUARDIAN ATTRIBUTION VM BOUNDARIES PASS (fixture; no actual update acceptance)')
