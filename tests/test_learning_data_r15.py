"""R15 adversarial data integrity / label leakage tests (offline fixtures)."""
import json
import sqlite3
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from learning_data_r15 import (SCHEMA, audit_and_collect, canonical_hash, connect_reviews,
                                export_training_pack, verify_turn, _component_groups)
from storage import add_turn, connect, create_run, save_run_outcome
from uma_core import Action, RunProfile, TurnState


class LearningDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runs = connect(self.root / 'runs.sqlite3')
        self.reviews = connect_reviews(self.root / 'reviews.sqlite3')
        self.rid = create_run(self.runs, asdict(RunProfile(character='테스트 마', notes='사적 메모')))
        self.opts = {'스피드': asdict(Action('스피드', observed=True, gains={'스피드': 30})),
                     '지능': asdict(Action('지능', observed=True, gains={'지능': 20}))}
        self.tid = add_turn(self.runs, self.rid, asdict(TurnState()), self.opts,
                            [{'name':'스피드','score':9999}], '스피드', note='민감한 사용자 메모')
        self.before, self.after = self.root / 'before.png', self.root / 'after.png'
        Image.new('RGB', (25, 25), color=(10, 20, 30)).save(self.before)
        Image.new('RGB', (25, 25), color=(20, 40, 50)).save(self.after)

    def tearDown(self):
        self.reviews.close()
        self.runs.close()
        self.tmp.cleanup()

    def verify(self, **kw):
        args = {'run_id': self.rid, 'turn_id': self.tid, 'before': self.before,
                'after': self.after, 'origin': 'game_screenshot', 'server': 'KR',
                'patch_version': 'KR-island-tested-build', 'provenance_group': '',
                'reviewer_note': '선택 전후 변화 확인'}
        args.update(kw)
        return verify_turn(self.runs, self.reviews, **args)

    def test_unreviewed_never_exported(self):
        audit = audit_and_collect(self.runs, self.reviews)
        self.assertEqual(audit['summary']['exportable_rows'], 0)
        self.assertFalse(audit['summary']['training_ready_gate'])

    def test_reviewed_candidate_has_pre_action_features_only(self):
        self.verify()
        audit = audit_and_collect(self.runs, self.reviews)
        self.assertEqual(audit['summary']['exportable_rows'], 1)
        row = audit['records'][0]
        self.assertEqual(row['schema'], SCHEMA)
        self.assertEqual(row['label']['meaning'], 'human_behavior_not_optimality')
        self.assertEqual(row['scenario_id'], 'island_post_patch_v1')
        self.assertNotIn('사적 메모', json.dumps(row, ensure_ascii=False))
        self.assertNotIn('9999', json.dumps(row, ensure_ascii=False))
        self.assertNotIn('민감한 사용자 메모', json.dumps(row, ensure_ascii=False))
        self.assertNotIn('outcome', json.dumps(row, ensure_ascii=False))
        self.assertNotIn('screenshot', row['features'])
        self.assertNotIn('character', row['features'])
        self.assertFalse(audit['summary']['training_ready_gate'])
        report = export_training_pack(self.runs, self.reviews, self.root / 'export')
        self.assertEqual(report['exportable_rows'], 1)
        files = [self.root / 'export'/f'uma_r15_{split}.jsonl' for split in ('train', 'validation', 'test')]
        self.assertEqual(sum(len(x.read_text(encoding='utf-8').splitlines()) for x in files), 1)

    def test_prohibit_wrong_label_and_partial_options(self):
        rid = create_run(self.runs, asdict(RunProfile()))
        bad = add_turn(self.runs, rid, asdict(TurnState()), {'스피드':self.opts['스피드']}, [], '스피드')
        with self.assertRaisesRegex(ValueError, '두 개 이상'):
            self.verify(run_id=rid,turn_id=bad)
        other = add_turn(self.runs, rid, asdict(TurnState()), self.opts, [], '레이스')
        with self.assertRaisesRegex(ValueError, '관측 선택지'):
            self.verify(run_id=rid,turn_id=other)

    def test_patches_and_origins_mandatory(self):
        with self.assertRaisesRegex(ValueError, '패치 버전'):
            self.verify(patch_version='unknown')
        with self.assertRaisesRegex(ValueError, '출처'):
            self.verify(origin='generated_example')
        with self.assertRaisesRegex(ValueError, '영상 출처'):
            self.verify(origin='reviewed_game_video',provenance_group='')

    def test_evidence_before_after_distinct(self):
        with self.assertRaisesRegex(ValueError, '같습니다'):
            self.verify(after=self.before)

    def test_tampered_screenshot_excluded(self):
        self.verify()
        Image.new('RGB',(25,25),'white').save(self.after)
        audit = audit_and_collect(self.runs, self.reviews)
        self.assertEqual(audit['summary']['exportable_rows'], 0)
        self.assertEqual(audit['summary']['excluded_rows'], 1)

    def test_edit_original_turn_excluded(self):
        self.verify()
        self.runs.execute('UPDATE turns SET chosen_action=? WHERE id=?', ('지능', self.tid))
        self.runs.commit()
        audit = audit_and_collect(self.runs, self.reviews)
        self.assertEqual(audit['summary']['exportable_rows'], 0)
        self.assertIn('원본', audit['excluded'][0]['reason'])

    def test_outcome_not_in_features(self):
        self.verify()
        save_run_outcome(self.runs, self.rid, {'status':'도축/중단','reason':'실패'})
        rec = audit_and_collect(self.runs, self.reviews)['records'][0]
        self.assertNotIn('도축/중단', json.dumps(rec, ensure_ascii=False))

    def test_duplicate_before_after_pair_excluded(self):
        self.verify()
        second = add_turn(self.runs,self.rid,asdict(TurnState(turn_label='주니어급 7월 후반')),
                          self.opts,[],'지능')
        self.verify(turn_id=second)
        audit = audit_and_collect(self.runs,self.reviews)
        self.assertEqual(audit['summary']['exportable_rows'],1)
        self.assertEqual(audit['summary']['excluded_rows'],1)

    def test_future_scenario_cannot_train_without_adapter(self):
        p=asdict(RunProfile(scenario='future_unknown'))
        rid=create_run(self.runs,p)
        tid=add_turn(self.runs,rid,asdict(TurnState()),self.opts,[],'스피드')
        with self.assertRaisesRegex(ValueError, '어댑터'):
            self.verify(run_id=rid,turn_id=tid)

    def test_connected_groups_across_multiple_sources_and_runs(self):
        rows=[{'run_id':1,'turn_id':11,'origin':'reviewed_game_video','provenance_group':'video_A'},
              {'run_id':1,'turn_id':12,'origin':'reviewed_game_video','provenance_group':'video_B'},
              {'run_id':2,'turn_id':21,'origin':'reviewed_game_video','provenance_group':'video_B'},
              {'run_id':3,'turn_id':31,'origin':'reviewed_game_video','provenance_group':'video_C'}]
        result=_component_groups(rows,'install')
        self.assertEqual(result[(1,11)],result[(1,12)])
        self.assertEqual(result[(1,12)],result[(2,21)])
        self.assertNotEqual(result[(1,11)],result[(3,31)])

    def test_group_conflicting_servers_rejected(self):
        self.verify()
        tid2=add_turn(self.runs,self.rid,asdict(TurnState(turn_label='주니어급 7월 후반')),
                      self.opts,[],'지능')
        before2=self.root/'b2.png'; after2=self.root/'a2.png'
        Image.new('RGB',(25,25),'red').save(before2)
        Image.new('RGB',(25,25),'blue').save(after2)
        self.verify(turn_id=tid2,before=before2,after=after2,server='JP')
        audit=audit_and_collect(self.runs,self.reviews)
        self.assertEqual(audit['summary']['exportable_rows'],0)
        self.assertEqual(audit['summary']['excluded_rows'],2)

    def test_reviews_stored_separately_from_game_db(self):
        self.verify()
        tables=[x[0] for x in self.runs.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertNotIn('verified_turns',tables)

if __name__ == '__main__':
    unittest.main()
