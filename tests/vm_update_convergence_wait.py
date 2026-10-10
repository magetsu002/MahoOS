#!/usr/bin/env python3
"""Real root-owned stable waiting proof in an explicitly disposable QEMU VM."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
import maho_update_coordinator as c
from maho_update_state import create_transaction, transition_transaction, UpdateState

if os.geteuid() != 0 or os.environ.get('MAHO_DISPOSABLE_VM_TEST') != '1':
    raise SystemExit('root and disposable VM opt-in required')
dmi = Path('/sys/class/dmi/id/product_name').read_text()
if not any(name in dmi for name in ('QEMU', 'Standard PC')):
    raise SystemExit('disposable QEMU identity required')
revision = (ROOT / 'SOURCE_REVISION').read_text().strip()
now = datetime.now(timezone.utc)
tx = create_transaction(transaction_id='upd-20261010T000000Z-123456abcdef', source_revision=revision,
    packages=[{'name':'maho-vm-own-wait-fixture','installed_version':'1','candidate_version':'2',
               'repository':'core','download_size':1,'installed_size':1,'security_relevant':False,'roles':[]}],
    activation_requirements=[], recovery_generation_id=None, now=now)
tx = transition_transaction(tx, UpdateState.STAGED, now=now)
tx = transition_transaction(tx, UpdateState.PREPARED, now=now)
root = Path(tempfile.mkdtemp(prefix='maho-convergence-wait-', dir='/var/lib'))
os.environ['MAHO_UPDATE_STATE_ROOT'] = str(root)
os.environ['MAHO_UPDATE_AUTO_WORK_ROOT'] = str(root/'own-empty-cache')
c.publish_transaction(root, tx)
transaction_path = c.transaction_path(root, tx['transaction_id'])
before = transaction_path.read_bytes()
state = {**c._base_state(now, revision), 'lane':'normal','active_transaction_id':tx['transaction_id'],
         'first_observed_at':c.stamp(now - timedelta(days=1)), 'repository_hashes':{'core':'a'*64}}
fingerprints = set()
for n in range(32):
    # Real authority loader, root modes, durable fsync/replace, current transaction
    # and disk observer. No mocked authority or resource providers.
    state = c._resume_owned(state, revision, 'unused', {}, {}, now + timedelta(hours=n))
    assert state['phase'] == 'WAITING_AUTHORITY'
    assert state['convergence']['execution_authorized'] is False
    assert state['last_success_at'] is None
    assert state['first_observed_at'] == c.stamp(now - timedelta(days=1))
    assert state['update_debt_seconds'] >= 86400
    fingerprints.add(state['convergence']['evidence_fingerprint'])
    assert transaction_path.read_bytes() == before
    durable = c.read_coordinator_state(root)
    assert durable['convergence'] == state['convergence']
assert len(fingerprints) == 1
assert not (root/'own-empty-cache').exists()
assert len(list((root/'transactions').glob('*.json'))) == 1
assert c.coordinator_path(root).stat().st_uid == 0
assert c.coordinator_path(root).stat().st_mode & 0o777 == 0o644
print(json.dumps({'kind':'maho-convergence-wait-vm-proof','source_revision':revision,
                  'actual_wait_cycles':32,'stable_fingerprints':len(fingerprints),
                  'transaction_sha256':hashlib.sha256(before).hexdigest(),
                  'transaction_documents':1,'staging_created':False,
                  'installation_success_fabricated':False,'real_authority_validation':True,
                  'snapshot_retirement_certified':False},sort_keys=True))
# Only this newly created disposable-VM fixture, never production artifacts.
shutil.rmtree(root)
