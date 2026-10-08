#!/usr/bin/env python3
"""Production certification must reobserve maintenance immediately before live activation."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from maho_update_normal import NormalExecutionPlan, execute_normal_certification
from maho_update_state import create_transaction, transition_transaction, UpdateState

REV = 'c' * 40
TXID = 'upd-20261008T123000Z-abcdefabcdef'


def fixture():
    current = create_transaction(
        transaction_id=TXID, source_revision=REV,
        packages=[{'name':'vulkan-headers','installed_version':'1','candidate_version':'2',
                   'repository':'core','download_size':123,'installed_size':456,'roles':[]}],
        activation_requirements=[], recovery_generation_id=None,
    )
    current = transition_transaction(current, UpdateState.STAGED)
    current = transition_transaction(current, UpdateState.PREPARED)
    plan = NormalExecutionPlan(
        transaction_id=TXID, package_generation_id=current['package_generation']['id'],
        source_provenance_id=current['source_provenance']['id'], payload_paths=('example',),
        effects=('ordinary-files',), activation_requirements=(), selection_kind='coherent-subset',
        execution_environment='production', safe_reserve_bytes=0,
        reserve_after_preparation_bytes=1000000,
    )
    ops = Mock()
    ops.production_safe = True
    ops.install_candidate.return_value = {'ok':True}
    ops.guardian_admit.return_value = {'ok':True}
    ops.activate.return_value = {'ok':True}
    ops.verify.return_value = {'ok':True}
    return current, plan, ops


class CertificationMaintenanceContracts(unittest.TestCase):
    def test_missing_reobservation_refuses_before_any_candidate_operation(self):
        tx, plan, ops = fixture()
        with self.assertRaisesRegex(ValueError, 'fresh activation maintenance evidence'):
            execute_normal_certification(tx,plan,ops,confirmation='CERTIFY-NORMAL:'+REV)
        ops.install_candidate.assert_not_called()

    def test_stale_guardian_or_adaptive_denial_blocks_live_activation(self):
        invalid = [
            {'safe':False,'veto_active':False,'snapshot_id':'sit-test','captured_at':'now'},
            {'safe':True,'veto_active':True,'snapshot_id':'sit-test','captured_at':'now'},
            {'safe':True,'veto_active':False,'snapshot_id':'','captured_at':'now'},
            {'safe':True,'veto_active':False,'snapshot_id':'sit-test'},
            {},
        ]
        for observation in invalid:
            with self.subTest(observation=observation):
                tx,plan,ops=fixture()
                result=execute_normal_certification(
                    tx,plan,ops,confirmation='CERTIFY-NORMAL:'+REV,
                    activation_maintenance_reobserve=lambda:observation,
                )
                self.assertEqual(result.transaction['state'],'ATTENTION_REQUIRED')
                ops.install_candidate.assert_called_once()
                ops.guardian_admit.assert_called_once()
                ops.activate.assert_not_called()

    def test_fresh_observation_occurs_after_guardian_and_before_live_activation(self):
        tx,plan,ops=fixture()
        order=[]
        ops.install_candidate.side_effect=lambda p:order.append('candidate') or {'ok':True}
        ops.guardian_admit.side_effect=lambda p:order.append('guardian') or {'ok':True}
        ops.activate.side_effect=lambda p:order.append('live-activation') or {'ok':True}
        obs=lambda: order.append('maintenance') or {
            'safe':True,'veto_active':False,'snapshot_id':'sit-exact','captured_at':'now',
        }
        result=execute_normal_certification(
            tx,plan,ops,confirmation='CERTIFY-NORMAL:'+REV,
            activation_maintenance_reobserve=obs,
        )
        self.assertEqual(result.transaction['state'],'HEALTHY')
        self.assertEqual(order,['candidate','guardian','maintenance','live-activation'])

    def test_guardian_denial_never_reaches_live_activation_or_maintenance(self):
        tx,plan,ops=fixture()
        ops.guardian_admit.return_value={'ok':False}
        observation=Mock(return_value={
            'safe':True,'veto_active':False,'snapshot_id':'sit-test','captured_at':'now',
        })
        result=execute_normal_certification(
            tx,plan,ops,confirmation='CERTIFY-NORMAL:'+REV,
            activation_maintenance_reobserve=observation,
        )
        self.assertEqual(result.transaction['state'],'ATTENTION_REQUIRED')
        observation.assert_not_called()
        ops.activate.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
