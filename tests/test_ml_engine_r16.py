"""R16 regression/adversarial tests: all synthetic data stays in temporary memory."""
import copy
import hashlib
import json
import math
import tempfile
import unittest
from pathlib import Path

from learning_data_r15 import SCHEMA
from ml_engine_r16 import (FEATURES, MODEL_SCHEMA, behavior_preview,
     cohort_summary, load_r15_exports, read_model, save_model, train_behavior)


def h(v):
    return hashlib.sha256(str(v).encode()).hexdigest()


def fixtures(n=32, turns=8):
    rows=[]
    for group in range(n):
        split='train' if group < 22 else 'validation' if group < 27 else 'test'
        for turn in range(turns):
            actual = ('스피드' if (group + turn) % 3 else '지능')
            rows.append({'schema':SCHEMA, 'scenario_id':'island_post_patch_v1',
            'server':'JP', 'patch_version':'JP-2025-07-postbalance',
            'origin':'reviewed_game_video', 'provenance_group_hash':h('group'+str(group)),
            'example_id':h('row'+str(group)+'-'+str(turn)),
            'split':split,
            'features':{'event':'챔피언스 미팅','distance':'중거리','style':'선행',
                'target_stats':{'스피드':1500,'스태미나':1200,'파워':1100,'근성':900,'지능':1200},
                'stats':{'스피드':400,'스태미나':400,'파워':400,'근성':400,'지능':400},
                'remaining_turns':50-turn,'energy':80,'mood':'좋음','skill_points':500},
            'scenario_features':{'island_tickets':0,'development_points':5,
                                 'turns_until_next_ticket':4,'building_levels':{'스피드':2,'지능':2}},
            'observed_options':{'스피드':{'gains':{'스피드':40 if actual=='스피드' else 5},'energy_delta':-15},
                                '지능':{'gains':{'지능':40 if actual=='지능' else 5},'energy_delta':-5}},
            'label':{'chosen_action':actual,'meaning':'human_behavior_not_optimality'},
            'evidence':{'before_sha256':h('b'+str(group)+'-'+str(turn)),
                        'after_sha256':h('a'+str(group)+'-'+str(turn)), 'reviewed_at':'fixture_only'}})
    return rows


def exported(folder, rows):
    folder.mkdir(parents=True, exist_ok=True)
    for split in ('train','validation','test'):
        (folder/f'uma_r15_{split}.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows if x['split']==split),encoding='utf-8')
    (folder/'uma_r15_audit.json').write_text(json.dumps({'schema':SCHEMA,'exportable_rows':len(rows)}),encoding='utf-8')


class R16Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.root=Path(self.t.name)
        self.rows=fixtures()
        exported(self.root,self.rows)
        self.key=('island_post_patch_v1','JP','JP-2025-07-postbalance','챔피언스 미팅')
    def tearDown(self): self.t.cleanup()

    def test_valid_data_eligible(self):
        r=load_r15_exports(self.root)
        self.assertEqual(len(r),256)
        self.assertTrue(cohort_summary(r)[0]['eligible'])

    def test_train_is_real_supervised_model_but_behavior_only(self):
        m=train_behavior(load_r15_exports(self.root),self.key,epochs=30)
        self.assertEqual(m['schema'],MODEL_SCHEMA)
        self.assertEqual(m['deployment_state'],'research_only_NEVER_auto_apply')
        self.assertIn('NOT_optimal_action',m['learning_task'])
        self.assertGreater(len(m['weights']),15)
        self.assertEqual(m['metrics']['test']['rows'],40)
        self.assertTrue(all(math.isfinite(v) for v in m['weights']))
        self.assertTrue(0<=m['metrics']['test']['accuracy']<=1)

    def test_model_json_roundtrip_tamper_guard(self):
        m=train_behavior(self.rows,self.key,epochs=20)
        path=save_model(m,self.root/'model.json')
        self.assertEqual(read_model(path)['model_sha256'],m['model_sha256'])
        tampered=json.loads(path.read_text(encoding='utf-8'))
        tampered['weights'][0]=1.1
        path.write_text(json.dumps(tampered),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'무결성'):
            read_model(path)

    def test_provenance_leak_rejected(self):
        data=copy.deepcopy(self.rows)
        group=data[0]['provenance_group_hash']
        next(x for x in data if x['split']=='validation')['provenance_group_hash']=group
        exported(self.root,data)
        with self.assertRaisesRegex(ValueError,'분할'):
            load_r15_exports(self.root)

    def test_cross_group_same_source_image_rejected(self):
        data=copy.deepcopy(self.rows)
        next(x for x in data if x['split']=='test')['evidence']['before_sha256']=data[0]['evidence']['before_sha256']
        exported(self.root,data)
        with self.assertRaisesRegex(ValueError,'프레임'):
            load_r15_exports(self.root)

    def test_same_example_id_rejected(self):
        data=copy.deepcopy(self.rows)
        data[1]['example_id']=data[0]['example_id']
        exported(self.root,data)
        with self.assertRaisesRegex(ValueError,'중복'):
            load_r15_exports(self.root)

    def test_audit_count_tamper_rejected(self):
        (self.root/'uma_r15_audit.json').write_text(json.dumps({'schema':SCHEMA,'exportable_rows':8}),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'감사'):
            load_r15_exports(self.root)

    def test_wrong_label_or_unobserved_action_rejected(self):
        for field,val in [('meaning','optimal_action'),('chosen_action','레이스')]:
            data=copy.deepcopy(self.rows)
            data[0]['label'][field]=val
            exported(self.root,data)
            with self.assertRaises(ValueError):load_r15_exports(self.root)

    def test_invalid_numeric_nan_inf_and_bool_rejected(self):
        for v in [float('nan'),float('inf'),True,-999]:
            data=copy.deepcopy(self.rows)
            data[0]['features']['energy']=v
            exported(self.root,data)
            with self.assertRaises(ValueError):load_r15_exports(self.root)

    def test_same_group_mixed_cohorts_rejected(self):
        data=copy.deepcopy(self.rows)
        data[1]['patch_version']='JP-2025-09-other'
        exported(self.root,data)
        with self.assertRaisesRegex(ValueError,'혼합'):
            load_r15_exports(self.root)

    def test_duplicate_evidence_pair_rejected(self):
        data=copy.deepcopy(self.rows)
        data[1]['evidence']=copy.deepcopy(data[0]['evidence'])
        exported(self.root,data)
        with self.assertRaisesRegex(ValueError,'중복'):
            load_r15_exports(self.root)

    def test_different_patches_never_pooled(self):
        data=copy.deepcopy(self.rows)
        for r in data:
            if r['split']=='train':r['patch_version']='JP-2025-09-patchB'
        # same source group now single patch, but each individual cohort incomplete
        exported(self.root,data)
        cohorts=cohort_summary(load_r15_exports(self.root))
        self.assertEqual(len(cohorts),2)
        self.assertFalse(any(c['eligible'] for c in cohorts))

    def test_small_data_blocks_learning(self):
        with self.assertRaisesRegex(ValueError,'부족'):
            train_behavior(self.rows[:12],self.key)

    def test_empty_real_export_prevents_model(self):
        exported(self.root,[])
        rows=load_r15_exports(self.root)
        self.assertEqual(rows,[])
        self.assertEqual(cohort_summary(rows),[])
        with self.assertRaises(ValueError):train_behavior(rows,self.key)

    def test_preview_scope_strict(self):
        model=train_behavior(self.rows,self.key,epochs=16)
        preview=behavior_preview(model,self.rows[0])
        self.assertEqual(len(preview),2)
        self.assertAlmostEqual(sum(v['behavior_similarity'] for v in preview),1.,places=3)
        different=copy.deepcopy(self.rows[0]);different['server']='KR'
        with self.assertRaisesRegex(ValueError,'다른 모델'):
            behavior_preview(model,different)

    def test_validation_and_test_are_heldout(self):
        m=train_behavior(self.rows,self.key,epochs=20)
        changed=copy.deepcopy(self.rows)
        for r in changed:
            if r['split']=='test':
                r['label']['chosen_action']='스피드' if r['label']['chosen_action']=='지능' else '지능'
        m2=train_behavior(changed,self.key,epochs=20)
        self.assertEqual(m['weights'],m2['weights'])
        self.assertEqual(m['metrics']['validation'],m2['metrics']['validation'])
        self.assertNotEqual(m['metrics']['test'],m2['metrics']['test'])

    def test_features_no_recommendation_or_post_outcome(self):
        row=copy.deepcopy(self.rows[0])
        row['outcome']={'success':True,'score':1e9}
        row['recommended_by_app']='지능'
        changed=copy.deepcopy(row)
        changed['outcome']={'success':False,'score':0}
        m=train_behavior(self.rows,self.key,epochs=12)
        self.assertEqual(behavior_preview(m,row), behavior_preview(m,changed))

    def test_missing_new_scenario_ml_adapter_rejected(self):
        data=copy.deepcopy(self.rows)
        data[0]['scenario_id']='unknown_future'
        exported(self.root,data)
        with self.assertRaisesRegex(ValueError,'어댑터'):
            load_r15_exports(self.root)

    def test_reject_unknown_action(self):
        data=copy.deepcopy(self.rows)
        data[0]['observed_options']['unsupported_mod']=data[0]['observed_options']['스피드']
        exported(self.root,data)
        with self.assertRaises(ValueError):load_r15_exports(self.root)

    def test_test_partition_cannot_pick_epochs(self):
        m=train_behavior(self.rows,self.key,epochs=30)
        changed=copy.deepcopy(self.rows)
        for r in changed:
            if r['split']=='test':r['observed_options']['지능']['gains']={'지능':90}
        m2=train_behavior(changed,self.key,epochs=30)
        self.assertEqual(m['training']['chosen_epoch'],m2['training']['chosen_epoch'])
        self.assertEqual(m['weights'],m2['weights'])

if __name__=='__main__':unittest.main()
