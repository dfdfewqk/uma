import csv
import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from analytics_r3 import (run_audit, corpus_audit, audit_verified_video_turns,
                          export_r3_report, export_verified_candidates_csv)
from storage import connect, create_run, add_turn, save_run_outcome
from uma_core import RunProfile, TurnState, Action, RankedAction


class R3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.conn = connect(self.root / 'runs.sqlite3')
        self.addCleanup(self.conn.close)
        self.rid = create_run(self.conn, asdict(RunProfile()))

    def record(self, remaining, value, choice='스피드', ranking='스피드', options=None):
        state = asdict(TurnState(remaining_turns=remaining, stats={s:value for s in (
            '스피드','스태미나','파워','근성','지능')}))
        actions = options if options is not None else {
            '스피드': asdict(Action('스피드', gains={'스피드':10}, observed=True)),
            '지능': asdict(Action('지능', gains={'지능':6}, observed=True))}
        ranks = [asdict(RankedAction(ranking, 50., [], {})),
                 asdict(RankedAction('지능' if ranking == '스피드' else '스피드', 20., [], {}))]
        add_turn(self.conn, self.rid, state, actions, ranks, choice)

    def test_empty_run_never_fabricates_predictive_output(self):
        r=run_audit(self.conn, self.rid)
        self.assertEqual(r['total_recorded_turns'], 0)
        self.assertEqual(r['comparison_turns'], 0)
        self.assertIsNone(r['heuristic_agreement_ratio'])
        self.assertEqual(r['status'], '기록 부족')
        self.assertIn('ML_NOT_TRAINED', r['model_status'])

    def test_agreement_not_accuracy_and_outcomes(self):
        self.record(50, 200, choice='지능')
        self.record(49, 210)
        self.record(48, 220, choice='미선택')
        save_run_outcome(self.conn, self.rid, {'status':'도축/중단', 'reason':'플레이어가 중단'})
        r=run_audit(self.conn,self.rid)
        self.assertEqual(r['comparison_turns'],2)
        self.assertEqual(r['heuristic_agreement_turns'],1)
        self.assertEqual(r['heuristic_agreement_ratio'],.5)
        self.assertEqual(corpus_audit(self.conn)['abandoned_with_turns'],1)
        self.assertNotIn('추천',r['status'][:2])
        self.assertEqual(len(r['snapshot_deltas']),2)
        self.assertEqual(r['snapshot_deltas'][0]['delta_stats']['파워'],10)

    def test_skip_nonconsecutive_and_negative_or_outlier(self):
        self.record(50, 200)
        self.record(48, 220) # skip gap
        self.record(47, 210) # bad negative
        self.record(46, 1500) # bad >1000
        self.assertEqual(run_audit(self.conn, self.rid)['consecutive_observed_intervals'],0)
        self.assertEqual(len(run_audit(self.conn, self.rid)['warnings']),2)

    def test_trends_need_five_pairs_and_are_descriptive(self):
        for i in range(6):
            self.record(50-i, 300+i*8)
        r=run_audit(self.conn,self.rid)
        self.assertEqual(r['consecutive_observed_intervals'],5)
        self.assertEqual(r['targets'][0]['observed_median'],8)
        self.assertEqual(r['targets'][0]['observed_p75'],8)
        self.assertIn('포기 근거 아님', r['status'])
        self.assertEqual(r['targets'][0]['sample_count'],5)
        path=self.root/'audit.json'
        export_r3_report(r,path)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['run_id'],self.rid)

    def test_zero_stats_and_verified_zero_action_support(self):
        self.record(50,0,options={
            '스피드':asdict(Action('스피드',observed=True)),
            '지능':asdict(Action('지능',observed=True))})
        self.assertEqual(run_audit(self.conn,self.rid)['comparison_turns'],1)

    def test_missing_video_file_is_not_invented(self):
        x=audit_verified_video_turns(self.root/'unknown.csv')
        self.assertEqual(x['qualified_main_run_turns'],0)
        self.assertFalse(x['ml_ready'])
        target=self.root/'candidate.csv'
        export_verified_candidates_csv(x,target)
        with target.open(encoding='utf-8-sig',newline='') as f:
            self.assertEqual(len(list(csv.DictReader(f))),0)

    def _video_row(self):
        a=self.root/'before.png'
        b=self.root/'after.png'
        a.write_bytes(b'fake-frame-A')
        b.write_bytes(b'fake-frame-B')
        return {
          'annotation_id':'example-1', 'scenario_id':'island_post_patch_v1',
          'server':'JP','patch_status':'post_2025_06_30_confirmed',
          'run_purpose':'champ_main','competition':'챔피언스 미팅',
          'review_grade':'complete','observed_choice':'true','observed_result':'true',
          'energy':'70', 'speed':'800', 'stamina':'600','power':'500','guts':'400','wisdom':'450',
          'alternatives_json':'{"스피드":{"speed":10},"지능":{"wisdom":10}}',
          'post_action_json':'{"speed":10}', 'chosen_action':'스피드',
          'frame_before_path':str(a),'frame_before_sha256':hashlib.sha256(a.read_bytes()).hexdigest(),
          'frame_after_path':str(b),'frame_after_sha256':hashlib.sha256(b.read_bytes()).hexdigest(),
          'source_id':'S011','case_id':'case1',
          'patch_evidence':'2025년 7월 출시 후 영상 수정 후 시나리오 설명과 영상 확인',
          'source_url':'https://www.youtube.com/watch?v=XqNuSH6RQh0'
        }

    def write_video(self,rows):
        p=self.root/'verified.csv'
        cols=list(rows[0].keys())
        with p.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,cols)
            w.writeheader()
            w.writerows(rows)
        return p

    def test_video_verified_candidate_with_hashes(self):
        row=self._video_row()
        path=self.write_video([row])
        a=audit_verified_video_turns(path)
        self.assertEqual(a['qualified_main_run_turns'],1)
        self.assertFalse(a['ml_ready'])
        self.assertNotIn('frame_before_path',a['candidates'][0])
        target=self.root/'out.csv'
        export_verified_candidates_csv(a,target)
        with target.open(encoding='utf-8-sig') as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 1)

    def test_video_reject_forged_source(self):
        row=self._video_row()
        row['source_id']='not_registered_video'
        path=self.write_video([row])
        self.assertEqual(audit_verified_video_turns(path)['excluded']['unverified_source_or_patch_evidence'],1)

    def test_video_reject_changed_frame(self):
        row=self._video_row()
        path=self.write_video([row])
        (self.root/'before.png').write_bytes(b'changed')
        report=audit_verified_video_turns(path)
        self.assertEqual(report['qualified_main_run_turns'],0)
        self.assertEqual(report['excluded']['missing_or_changed_frame'],1)

    def test_video_reject_wrong_purpose_or_patch(self):
        row=self._video_row()
        row['run_purpose']='factor_farming'
        path=self.write_video([row])
        r=audit_verified_video_turns(path)
        self.assertEqual(r['excluded']['not_champ_or_loh_main'],1)
        row['run_purpose']='champ_main'
        row['patch_status']='unknown'
        path=self.write_video([row])
        self.assertEqual(audit_verified_video_turns(path)['excluded']['unconfirmed_patch'],1)

    def test_video_reject_unsafe_labels_and_duplicates(self):
        row=self._video_row()
        row2=row.copy()
        path=self.write_video([row,row2])
        self.assertEqual(audit_verified_video_turns(path)['excluded']['duplicate_or_missing_id'],1)
        row['review_grade']='partial'
        path=self.write_video([row])
        self.assertEqual(audit_verified_video_turns(path)['excluded']['not_complete'],1)

if __name__=='__main__': unittest.main()
