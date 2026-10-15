"""Synthetic-only R17 registry tests. Never count fixture metrics as real game results."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from test_ml_engine_r16 import fixtures, exported
from ml_engine_r16 import train_behavior, read_model
from model_registry_r17 import (read_registry, register_model, compare_candidate,
                                promote_model, rollback_model, _key)


def updated_hash(model):
    model = copy.deepcopy(model)
    model['model_sha256'] = hashlib.sha256(json.dumps({k:v for k,v in model.items() if k != 'model_sha256'},
            ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return model


class R17RegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=fixtures(32,8)
        cls.key=('island_post_patch_v1','JP','JP-2025-07-postbalance','챔피언스 미팅')
        cls.good=train_behavior(cls.rows,cls.key)
        cls.weak=copy.deepcopy(cls.good)
        cls.weak['weights']=[0.0]*len(cls.weak['weights'])
        cls.weak=updated_hash(cls.weak)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def test_register_and_reopen(self):
        mid=register_model(self.root,self.good)
        self.assertEqual(read_model(self.root/'models'/f'{mid}.json')['model_sha256'],mid)
        self.assertIn(mid,read_registry(self.root)['entries'])
    def test_double_register_is_idempotent(self):
        mid=register_model(self.root,self.good)
        rev=read_registry(self.root)['revision']
        self.assertEqual(register_model(self.root,self.good),mid)
        self.assertEqual(read_registry(self.root)['revision'],rev)
    def test_candidate_better_than_weak(self):
        a=register_model(self.root,self.weak)
        first=compare_candidate(self.root,a,self.rows)
        self.assertTrue(first['eligible'],first)
        promote_model(self.root,a,self.rows)
        b=register_model(self.root,self.good)
        report=compare_candidate(self.root,b,self.rows)
        self.assertEqual(report['champion_id'],a)
        self.assertTrue(report['eligible'],report)
        promote_model(self.root,b,self.rows)
        self.assertEqual(read_registry(self.root)['scopes'][_key(self.good['scope'])]['champion'],b)
        self.assertEqual(rollback_model(self.root,self.good['scope']),a)
        self.assertEqual(read_registry(self.root)['scopes'][_key(self.good['scope'])]['champion'],a)
    def test_no_rollback_without_prior(self):
        a=register_model(self.root,self.weak)
        promote_model(self.root,a,self.rows)
        with self.assertRaises(ValueError):rollback_model(self.root,self.weak['scope'])
    def test_no_promotion_if_weaker(self):
        a=register_model(self.root,self.good)
        promote_model(self.root,a,self.rows)
        b=register_model(self.root,self.weak)
        rep=compare_candidate(self.root,b,self.rows)
        self.assertFalse(rep['eligible'])
        with self.assertRaises(ValueError):promote_model(self.root,b,self.rows)
    def test_reject_different_patch(self):
        a=register_model(self.root,self.good)
        altered=copy.deepcopy(self.good)
        altered['scope']['patch_version']='JP-2025-06-early'
        altered=updated_hash(altered)
        register_model(self.root,altered)
        with self.assertRaises(ValueError):compare_candidate(self.root,altered['model_sha256'],self.rows)
    def test_reject_different_server(self):
        changed=copy.deepcopy(self.good)
        changed['scope']['server']='KR'
        changed=updated_hash(changed)
        register_model(self.root,changed)
        with self.assertRaises(ValueError):compare_candidate(self.root,changed['model_sha256'],self.rows)
    def test_dataset_mismatch_blocks(self):
        changed=copy.deepcopy(self.good)
        changed['dataset_id_sha256']='a'*64
        changed=updated_hash(changed)
        register_model(self.root,changed)
        with self.assertRaises(ValueError):compare_candidate(self.root,changed['model_sha256'],self.rows)
    def test_cross_split_leak_rejected(self):
        changed=copy.deepcopy(self.rows)
        changed[0]['provenance_group_hash']=next(r['provenance_group_hash'] for r in changed if r['split']=='validation')
        a=register_model(self.root,self.good)
        with self.assertRaises(ValueError):compare_candidate(self.root,a,changed)
    def test_registry_tampering_rejected(self):
        register_model(self.root,self.good)
        p=self.root/'registry.json'
        data=json.loads(p.read_text('utf-8'))
        data['revision']=9999
        p.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(ValueError):read_registry(self.root)
    def test_model_tampering_rejected(self):
        mid=register_model(self.root,self.good)
        p=self.root/'models'/f'{mid}.json'
        data=json.loads(p.read_text('utf-8'))
        data['weights'][0]=12.0
        p.write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(ValueError):read_registry(self.root)
    def test_stale_revision_rejected(self):
        a=register_model(self.root,self.weak)
        old=read_registry(self.root)['revision']
        register_model(self.root,self.good)
        with self.assertRaises(ValueError):promote_model(self.root,a,self.rows,expected_revision=old)
    def test_no_automatic_champion_from_registration(self):
        register_model(self.root,self.good)
        st=read_registry(self.root)['scopes'][_key(self.good['scope'])]
        self.assertIsNone(st['champion'])
    def test_no_test_split_selection(self):
        # Test labels are modified, while validation stays fixed; selection result must be unchanged.
        mid=register_model(self.root,self.good)
        a=compare_candidate(self.root,mid,self.rows)
        altered=copy.deepcopy(self.rows)
        for r in altered:
            if r['split']=='test':
                r['label']['chosen_action']='지능' if r['label']['chosen_action']=='스피드' else '스피드'
        b=compare_candidate(self.root,mid,altered)
        self.assertEqual(a['eligible'],b['eligible'])
        self.assertEqual(a['validation_sha256'],b['validation_sha256'])
        self.assertEqual(a['candidate'],b['candidate'])
    def test_corrupted_registry_missing_file(self):
        mid=register_model(self.root,self.good)
        (self.root/'models'/f'{mid}.json').unlink()
        with self.assertRaises(ValueError):read_registry(self.root)

if __name__=='__main__':unittest.main()
